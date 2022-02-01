import os
import time
import uuid
from functools import partial
from pathlib import Path
from typing import Union, Iterable, Optional

from core import settings
from common.redis import RedisClient
from common.storage import StorageS3
from common.utils import get_logger
from modules.podcast.models import Episode
from common.enums import EpisodeStatus

logger = get_logger(__name__)


def delete_file(filepath: Union[str, Path]):
    """Delete local file"""

    try:
        os.remove(filepath)
    except IOError as error:
        logger.warning(f"Could not delete file {filepath}: {error}")
    else:
        logger.info(f"File {filepath} deleted")


def get_file_name(video_id: str) -> str:
    return f"{video_id}_{uuid.uuid4().hex}.mp3"


def get_file_size(file_path: str):
    try:
        return os.path.getsize(file_path)
    except FileNotFoundError:
        logger.info("File %s not found. Return size 0", file_path)
        return 0


async def check_state(episodes: Iterable[Episode]) -> list:
    """Allows getting info about download progress for requested episodes"""

    redis_client = RedisClient()
    file_names = {redis_client.get_key_by_filename(episode.file_name) for episode in episodes}
    current_states = await redis_client.async_get_many(file_names, pkey="event_key")
    result = []
    for episode in episodes:
        file_name = episode.file_name
        if not file_name:
            logger.warning(f"Episode {episode} does not contain filename")
            continue

        event_key = redis_client.get_key_by_filename(file_name)
        current_state = current_states.get(event_key)
        if current_state:
            current_file_size = current_state["processed_bytes"]
            total_file_size = current_state["total_bytes"]
            completed = round((current_file_size / total_file_size) * 100, 2)
            status = current_state["status"]
        else:
            current_file_size = 0
            total_file_size = 0
            completed = 0
            status = EpisodeStatus.DL_PENDING

        result.append(
            {
                "status": status,
                "episode_id": episode.id,
                "podcast_id": episode.podcast_id,
                "completed": completed,
                "current_file_size": current_file_size,
                "total_file_size": total_file_size,
            }
        )

    return result


def upload_process_hook(filename: str, chunk: int):
    """
    Allows handling uploading to Yandex.Cloud (S3) and update redis state (for user's progress).
    It is called by `s3.upload_file` (`podcast.utils.upload_episode`)
    """
    episode_process_hook(filename=filename, status=EpisodeStatus.DL_EPISODE_UPLOADING, chunk=chunk)


def post_processing_process_hook(filename: str, target_path: str, total_bytes: int):
    """
    Allows handling progress for ffmpeg file's preparations
    """
    processed_bytes = 0
    while processed_bytes < total_bytes:
        processed_bytes = get_file_size(target_path)
        episode_process_hook(
            filename=filename,
            status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
            total_bytes=total_bytes,
            processed_bytes=processed_bytes,
        )
        time.sleep(1)


def episode_process_hook(
    status: EpisodeStatus,
    filename: str,
    total_bytes: int = 0,
    processed_bytes: int = None,
    chunk: int = 0,
):
    """Allows handling processes of performing episode's file."""
    redis_client = RedisClient()
    filename = os.path.basename(filename)
    event_key = redis_client.get_key_by_filename(filename)
    current_event_data = redis_client.get(event_key) or {}
    total_bytes = total_bytes or current_event_data.get("total_bytes", 0)
    if processed_bytes is None:
        processed_bytes = current_event_data.get("processed_bytes") + chunk

    event_data = {
        "event_key": event_key,
        "status": str(status),
        "processed_bytes": processed_bytes,
        "total_bytes": total_bytes,
    }
    redis_client.set(event_key, event_data, ttl=settings.DOWNLOAD_EVENT_REDIS_TTL)
    if processed_bytes and total_bytes:
        progress = "{0:.2%}".format(processed_bytes / total_bytes)
    else:
        progress = f"processed = {processed_bytes} | total = {total_bytes}"

    logger.debug("[%s] for %s: %s", status, filename, progress)


def upload_episode(filename: str, src_path: str = None) -> Optional[str]:
    """Allows uploading src_path to Yandex.Cloud (aka AWS S3)"""

    src_path = src_path or os.path.join(settings.TMP_AUDIO_PATH, filename)
    episode_process_hook(
        filename=filename,
        status=EpisodeStatus.DL_EPISODE_UPLOADING,
        processed_bytes=0,
        total_bytes=get_file_size(src_path),
    )
    logger.info("Upload for %s started.", filename)
    storage = StorageS3()
    result_url = storage.upload_file(
        src_path=src_path,
        dst_path=settings.S3_BUCKET_AUDIO_PATH,
        callback=partial(upload_process_hook, filename),
    )
    if not result_url:
        logger.warning("Couldn't upload file to S3 storage. SKIP")
        episode_process_hook(filename=filename, status=EpisodeStatus.ERROR, processed_bytes=0)
        return

    logger.info("Great! uploading for %s was done!", filename)
    logger.debug("Finished uploading for file %s. \n Result url is %s", filename, result_url)
    return result_url

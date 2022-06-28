import os
import time
from functools import partial
from pathlib import Path
from typing import Union, Iterable, Optional

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

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


def get_file_size(file_path: str | Path):
    try:
        return os.path.getsize(file_path)
    except FileNotFoundError:
        logger.warning("File %s not found. Return size 0", file_path)
        return 0


async def check_state(episodes: Iterable[Episode]) -> list:
    """Allows getting info about download progress for requested episodes"""

    redis_client = RedisClient()
    filenames = {redis_client.get_key_by_filename(episode.audio_filename) for episode in episodes}
    current_states = await redis_client.async_get_many(filenames, pkey="event_key")
    result = []
    for episode in episodes:
        filename = episode.audio_filename
        event_key = redis_client.get_key_by_filename(filename)
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
    Allows handling uploading to S3 storage and update redis state (for user's progress).
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


def upload_episode(src_path: str | Path) -> Optional[str]:
    """Allows uploading src_path to S3 storage"""

    filename = os.path.basename(src_path)
    episode_process_hook(
        filename=filename,
        status=EpisodeStatus.DL_EPISODE_UPLOADING,
        processed_bytes=0,
        total_bytes=get_file_size(src_path),
    )
    logger.info("Upload for %s started.", filename)
    remote_path = StorageS3().upload_file(
        src_path=str(src_path),
        dst_path=settings.S3_BUCKET_AUDIO_PATH,
        callback=partial(upload_process_hook, filename),
    )
    if not remote_path:
        logger.warning("Couldn't upload file to S3 storage. SKIP")
        episode_process_hook(filename=filename, status=EpisodeStatus.ERROR, processed_bytes=0)
        return

    logger.info("Great! uploading for %s was done!", filename)
    logger.debug("Finished uploading for file %s. \n Result url is %s", filename, remote_path)
    return remote_path


async def save_uploaded_file(uploaded_file: UploadFile, prefix: str, max_file_size: int) -> Path:
    contents = await uploaded_file.read()
    file_ext = uploaded_file.filename.rpartition(".")[-1]
    result_file_path = settings.TMP_IMAGE_PATH / f"{prefix}.{file_ext}"
    with open(result_file_path, "wb") as f:
        await run_in_threadpool(f.write, contents)

    file_size = get_file_size(result_file_path)
    if file_size < 1:
        raise ValueError("result file-size is less than allowed")

    if file_size > max_file_size:
        raise ValueError("result file-size is more than allowed")

    return result_file_path

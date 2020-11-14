import enum
import os
import uuid
from functools import partial
from pathlib import Path
from typing import Union, Iterable, Optional

from core import settings
from common.redis import RedisClient
from common.storage import StorageS3
from common.utils import get_logger
from modules.podcast.models import Episode

logger = get_logger(__name__)


# TODO: use Episode.Status instead
class EpisodeStatuses(str, enum.Enum):
    pending = "pending"
    episode_downloading = "episode_downloading"
    episode_postprocessing = "episode_postprocessing"
    episode_uploading = "episode_uploading"
    cover_downloading = "cover_downloading"
    cover_uploading = "cover_uploading"
    error = "error"
    finished = "finished"


def delete_file(filepath: Union[str, Path]):
    """ Delete local file """

    try:
        os.remove(filepath)
    except IOError as error:
        logger.warning(f"Could not delete file {filepath}: {error}")
    else:
        logger.info(f"File {filepath} deleted")


def get_file_name(video_id: str, file_ext: str = settings.RESULT_FILE_EXT) -> str:
    return f"{video_id}_{uuid.uuid4().hex}.{file_ext}"


def get_file_size(file_path: str):
    try:
        full_path = os.path.join(file_path)
        return os.path.getsize(full_path)
    except FileNotFoundError:
        logger.info("File %s not found. Return size 0", file_path)
        return 0


async def check_state(episodes: Iterable[Episode]) -> list:
    """ Allows to get info about download progress for requested episodes """

    redis_client = RedisClient()
    file_names = {redis_client.get_key_by_filename(episode.file_name) for episode in episodes}
    current_states = await redis_client.async_get_many(file_names, pkey="event_key")
    result = []
    for episode in episodes:
        print(episode)
        file_name = episode.file_name
        if not file_name:
            logger.warning(f"Episode {episode} does not contain filename")
            continue

        event_key = redis_client.get_key_by_filename(file_name)
        current_state = current_states.get(event_key)
        if current_state:
            current_file_size = current_state["processed_bytes"]
            current_file_size_mb = round(current_file_size / 1024 / 1024, 2)
            total_file_size = current_state["total_bytes"]
            total_file_size_mb = round(total_file_size / 1024 / 1024, 2)
            completed = int((100 * current_file_size) / total_file_size)
            status = current_state["status"]
        else:
            current_file_size = 0
            current_file_size_mb = 0
            total_file_size = 0
            total_file_size_mb = 0
            completed = 0
            status = EpisodeStatuses.pending

        result.append(
            {
                "status": status,
                "episode_id": episode.id,
                "episode_title": episode.title,
                "podcast_id": episode.podcast_id,
                "completed": completed,
                "current_file_size": current_file_size,
                "current_file_size__mb": current_file_size_mb,
                "total_file_size": total_file_size,
                "total_file_size__mb": total_file_size_mb,
            }
        )

    return result


def upload_process_hook(filename: str, chunk: int):
    """
    Allows to handle uploading to Yandex.Cloud (S3) and update redis state (for user's progress).
    It is called by `s3.upload_file` (`podcast.utils.upload_episode`)
    """
    episode_process_hook(filename=filename, status=EpisodeStatuses.episode_uploading, chunk=chunk)


def episode_process_hook(
    status: str, filename: str, total_bytes: int = 0, processed_bytes: int = None, chunk: int = 0,
):
    """ Allows to handle processes of performing episode's file.
    """
    redis_client = RedisClient()
    filename = os.path.basename(filename)
    event_key = redis_client.get_key_by_filename(filename)
    current_event_data = redis_client.get(event_key) or {}
    total_bytes = total_bytes or current_event_data.get("total_bytes", 0)
    if processed_bytes is None:
        processed_bytes = current_event_data.get("processed_bytes") + chunk

    event_data = {
        "event_key": event_key,
        "status": status,
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
    """ Allows to upload src_path to Yandex.Cloud (aka AWS S3) """

    src_path = src_path or os.path.join(settings.TMP_AUDIO_PATH, filename)
    episode_process_hook(
        filename=filename,
        status=EpisodeStatuses.episode_uploading,
        processed_bytes=0,
        total_bytes=get_file_size(src_path),
    )
    logger.info("Upload for %s started.", filename)
    storage = StorageS3()
    result_url = storage.upload_file(
        src_path, filename, callback=partial(upload_process_hook, filename)
    )
    if not result_url:
        logger.warning("Couldn't upload file to S3 storage. SKIP")
        episode_process_hook(status=EpisodeStatuses.error, filename=filename)
        return

    logger.info("Great! uploading for %s was done!", filename)
    logger.debug("Finished uploading for file %s. \n Result url is %s", filename, result_url)
    return result_url

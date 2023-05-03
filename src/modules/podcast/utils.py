import json
import os
import time
import logging
from pathlib import Path
from typing import Iterable, Type
from functools import partial

from redis.asyncio.client import Redis
from rq.job import Job
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from core import settings
from common.redis import RedisClient
from common.storage import StorageS3
from common.enums import EpisodeStatus
from modules.podcast.models import Episode
from modules.podcast.tasks import RQTask

logger = logging.getLogger(__name__)


def delete_file(filepath: str | Path):
    """Delete local file"""

    try:
        os.remove(filepath)
    except IOError as exc:
        logger.warning("Could not delete file %s: %r", filepath, exc)
    else:
        logger.info("File %s deleted", filepath)


def get_file_size(file_path: str | Path):
    try:
        return os.path.getsize(file_path)
    except FileNotFoundError:
        logger.warning("File %s not found. Return size 0", file_path)
        return 0


async def check_state(episodes: Iterable[Episode]) -> list[dict]:
    """Allows getting info about download progress for requested episodes"""

    redis_client = RedisClient()
    filenames = {redis_client.get_key_by_filename(episode.audio_filename) for episode in episodes}
    current_states = await redis_client.async_get_many(filenames, pkey="event_key")
    result = []
    for episode in episodes:
        filename = episode.audio_filename
        event_key = redis_client.get_key_by_filename(filename)
        current_state = current_states.get(event_key)
        if episode.status == EpisodeStatus.ERROR:
            current_file_size = 0
            total_file_size = 0
            completed = 0
            status = EpisodeStatus.ERROR
        elif current_state:
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
    redis_client.publish(
        channel=settings.REDIS_PROGRESS_PUBSUB_CH,
        message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
    )
    if processed_bytes and total_bytes:
        progress = f"{processed_bytes / total_bytes:.2%}"
    else:
        progress = f"processed = {processed_bytes} | total = {total_bytes}"

    logger.debug("[%s] for %s: %s", status, filename, progress)


def upload_episode(src_path: str | Path) -> str | None:
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
        return None

    logger.info("Great! uploading for %s was done!", filename)
    logger.debug("Finished uploading for file %s. \n Result url is %s", filename, remote_path)
    return remote_path


def remote_copy_episode(
    src_path: str,
    dst_path: str,
    src_file_size: int = 0,
) -> str | None:
    """Allows uploading src_path to S3 storage"""

    filename = os.path.basename(src_path)
    episode_process_hook(
        filename=filename,
        status=EpisodeStatus.DL_EPISODE_UPLOADING,
        processed_bytes=0,
        total_bytes=src_file_size,
    )
    logger.debug("Remotely copying for %s started.", filename)
    remote_path = StorageS3().copy_file(src_path=str(src_path), dst_path=dst_path)
    if not remote_path:
        logger.warning("Couldn't move file in S3 storage remotely. SKIP")
        episode_process_hook(filename=filename, status=EpisodeStatus.ERROR, processed_bytes=0)
        return None

    logger.debug("Finished moving s3 for file %s. \n Remote path is %s", filename, remote_path)
    return remote_path


async def save_uploaded_file(
    uploaded_file: UploadFile, prefix: str, max_file_size: int, tmp_path: Path
) -> Path:
    _, file_ext = os.path.splitext(uploaded_file.filename)
    result_file_path = tmp_path / f"{prefix}{file_ext}"
    file_content = await uploaded_file.read()
    with open(result_file_path, "wb") as f:
        await run_in_threadpool(f.write, file_content)

    file_size = get_file_size(result_file_path)
    if file_size < 1:
        raise ValueError("result file-size is less than allowed")

    if file_size > max_file_size:
        raise ValueError("result file-size is more than allowed")

    return result_file_path


async def publish_redis_stop_downloading(episode_id: int) -> None:
    await RedisClient().async_publish(
        channel=settings.REDIS_STOP_DOWNLOADING_PUBSUB_CH,
        message=json.dumps({"episode_id": episode_id}),
    )


async def cancel_rq_task(task_class: Type[RQTask], episode_id: int) -> None:
    task_id = task_class.get_task_id(episode_id=episode_id)
    job = Job.fetch(task_id, connection=Redis())
    job.cancel()

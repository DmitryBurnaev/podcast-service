import asyncio
import os
from typing import Optional

from common.db_utils import db_transaction_sync
from core import settings
from common.storage import StorageS3
from common.utils import get_logger
from core.database import db
from modules.podcast.models import Episode, Podcast
from modules.youtube.exceptions import YoutubeException
from modules.youtube import utils as youtube_utils
from modules.podcast import utils as podcast_utils

logger = get_logger(__name__)

EPISODE_DOWNLOADING_OK = 0
EPISODE_DOWNLOADING_IGNORED = 1
EPISODE_DOWNLOADING_ERROR = 2


def _update_all_rss(source_id: str):
    """ Allows to regenerate rss for all podcast with requested episode (by source_id) """

    logger.info(
        "Episodes with source #%s: updating rss for all podcast included for", source_id,
    )

    affected_episodes = list(Episode.select(Episode.podcast).where(Episode.source_id == source_id))
    podcast_ids = [episode.podcast_id for episode in affected_episodes]
    logger.info("Found podcast for rss updates: %s", podcast_ids)

    for podcast_id in podcast_ids:
        generate_rss(podcast_id)


def _update_episode_data(source_id: str, update_data: dict):
    """ Allows to update data for episodes (filtered by source_id)"""

    logger.info("[%s] Episodes update data: %s", source_id, update_data)
    Episode.update(**update_data).where(
        Episode.source_id == source_id, Episode.status != Episode.STATUS_ARCHIVED
    ).execute()


def _update_episodes(source_id: str, file_size: int, status: str = Episode.Status.PUBLISHED):
    """ Allows to mark ALL episodes (exclude archived) with provided source_id as published """

    logger.info(f"Episodes with source #{source_id}: updating states")
    update_data = {"status": status, "file_size": file_size}
    if status == Episode.STATUS_PUBLISHED:
        update_data["published_at"] = Episode.created_at

    _update_episode_data(source_id, update_data)


# TODO: refactor me! use class-style for this task
@db_transaction_sync
def download_episode(youtube_link: str, episode_id: int):
    """ Allows to download youtube video and recreate specific rss (by requested episode_id) """

    episode = Episode.get_by_id(episode_id)
    logger.info(
        "=== [%s] START downloading process URL: %s FILENAME: %s ===",
        episode.source_id,
        youtube_link,
        episode.file_name,
    )
    stored_file_size = StorageS3().get_file_size(episode.file_name)

    if stored_file_size and stored_file_size == episode.file_size:
        logger.info(
            "[%s] Episode already downloaded and file correct. Downloading will be ignored.",
            episode.source_id,
        )
        _update_episodes(episode.source_id, stored_file_size)
        _update_all_rss(episode.source_id)
        return EPISODE_DOWNLOADING_IGNORED

    elif episode.status not in (Episode.STATUS_NEW, Episode.STATUS_DOWNLOADING):
        logger.error(
            "[%s] Episode is %s but file-size seems not correct. "
            "Removing not-correct file %s and reloading it from youtube.",
            episode.source_id,
            episode.status,
            episode.file_name,
        )
        StorageS3().delete_file(episode.file_name)

    logger.info(
        "[%s] Mark all episodes with source_id [%s] as downloading.",
        episode.source_id,
        episode.source_id,
    )
    query = Episode.update(status=Episode.STATUS_DOWNLOADING).where(
        Episode.source_id == episode.source_id, Episode.status != Episode.STATUS_ARCHIVED,
    )
    query.execute()

    try:
        result_filename = youtube_utils.download_audio(youtube_link, episode.file_name)
    except YoutubeException as error:
        logger.exception(
            "=== [%s] Downloading FAILED: Could not download track: %s. "
            "All episodes will be rolled back to NEW state",
            episode.source_id,
            error,
        )
        Episode.update(status=Episode.STATUS_NEW).where(
            Episode.source_id == episode.source_id
        ).execute()
        return EPISODE_DOWNLOADING_ERROR

    logger.info("=== [%s] DOWNLOADING was done ===", episode.source_id)

    youtube_utils.ffmpeg_preparation(result_filename)
    logger.info("=== [%s] POST PROCESSING was done === ", episode.source_id)

    # ----- uploading file to cloud -----
    remote_url = podcast_utils.upload_episode(result_filename)
    if not remote_url:
        logger.warning("=== [%s] UPLOADING was broken === ")
        _update_episodes(episode.source_id, file_size=0, status=Episode.STATUS_ERROR)
        return EPISODE_DOWNLOADING_ERROR

    _update_episode_data(
        episode.source_id, {"file_name": result_filename, "remote_url": remote_url}
    )
    logger.info("=== [%s] UPLOADING was done === ", episode.source_id)
    # -----------------------------------

    # ----- update episodes data -------
    _update_episodes(episode.source_id, file_size=StorageS3().get_file_size(result_filename))
    _update_all_rss(episode.source_id)
    podcast_utils.delete_file(os.path.join(settings.TMP_AUDIO_PATH, result_filename))
    # -----------------------------------

    logger.info("=== [%s] DOWNLOADING total finished ===", episode.source_id)
    return EPISODE_DOWNLOADING_OK


def generate_rss(podcast_id: int) -> Optional[str]:
    """ Allows to download and recreate specific rss (by requested podcast.publish_id) """
    # TODO: move to decorator or class method
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        db.set_bind(
            db.config["dsn"],
            echo=db.config["echo"],
            min_size=db.config["min_size"],
            max_size=db.config["max_size"],
            ssl=db.config["ssl"],
            loop=loop,
            **db.config["kwargs"],
        )
    )

    podcast = Podcast.get(id=podcast_id)

    logger.info("START rss generation for %s", podcast)

    src_file = podcast_utils.render_rss_to_file(podcast)
    filename = os.path.basename(src_file)
    storage = StorageS3()
    result_url = storage.upload_file(src_file, filename, remote_path=settings.S3_BUCKET_RSS_PATH)
    if not result_url:
        logger.error("Couldn't upload RSS file to storage. SKIP")
        exit(1)

    loop.run_until_complete(podcast.update(rss_link=result_url).apply())
    logger.info("RSS file uploaded, podcast record updated")

    if not settings.TEST_MODE:
        logger.info("Removing file [%s]", src_file)
        podcast_utils.delete_file(filepath=src_file)
        src_file = None

    logger.info("FINISH generation")
    loop.close()
    return src_file


def regenerate_rss():
    podcasts = list(Podcast.select())
    for podcast in podcasts:
        generate_rss(podcast.id)

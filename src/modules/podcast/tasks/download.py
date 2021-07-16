from youtube_dl.utils import YoutubeDLError

from core import settings
from common.storage import StorageS3
from common.utils import get_logger
from modules.podcast.models import Episode
from modules.podcast.tasks.base import RQTask, FinishCode
from modules.podcast.tasks.rss import GenerateRSSTask
from modules.youtube import utils as youtube_utils
from modules.podcast import utils as podcast_utils

logger = get_logger(__name__)
status = Episode.Status
__all__ = ["DownloadEpisodeTask"]


class DownloadingInterrupted(Exception):
    def __init__(self, code: FinishCode, message: str = ""):
        self.code = code
        self.message = message


class DownloadEpisodeTask(RQTask):
    """ Allows to download youtube video and recreate specific rss (by requested episode_id) """

    storage: StorageS3 = None

    async def run(self, episode_id: int) -> int:
        self.storage = StorageS3()

        try:
            code = await self.perform_run(int(episode_id))
        except DownloadingInterrupted as error:
            logger.warning("Episode downloading was interrupted with code: %i", error.code)
            return error.code.value
        except Exception as error:
            logger.exception("Unable to download episode: %s", error)
            await Episode.async_update(
                self.db_session,
                filter_kwargs={"id": episode_id},
                update_data={"status": Episode.Status.ERROR},
            )
            return FinishCode.ERROR

        return code.value

    async def perform_run(self, episode_id: int) -> FinishCode:
        """
        Main operation for downloading, performing and uploading audio to the storage.

        :raise: DownloadingInterrupted (if downloading is broken or unnecessary)
        """

        episode = await Episode.async_get(self.db_session, id=episode_id)
        logger.info(
            "=== [%s] START downloading process URL: %s FILENAME: %s ===",
            episode.source_id,
            episode.watch_url,
            episode.file_name,
        )
        await self._check_is_needed(episode)
        await self._remove_unfinished(episode)
        await self._update_episodes(episode.source_id, update_data={"status": status.DOWNLOADING})

        result_filename = await self._download_episode(episode)

        await self._process_file(episode, result_filename)
        await self._upload_file(episode, result_filename)
        await self._update_episodes(
            episode.source_id,
            update_data={
                "status": status.PUBLISHED,
                "file_size": self.storage.get_file_size(result_filename),
                "published_at": episode.created_at,
            },
        )
        await self._update_all_rss(episode.source_id)

        podcast_utils.delete_file(settings.TMP_AUDIO_PATH / result_filename)

        logger.info("=== [%s] DOWNLOADING total finished ===", episode.source_id)
        return FinishCode.OK

    async def _check_is_needed(self, episode: Episode):
        """ Allows to find another episodes with same `source_id` which were already downloaded. """
        stored_file_size = self.storage.get_file_size(episode.file_name)
        if stored_file_size and stored_file_size == episode.file_size:
            logger.info(
                "[%s] Episode already downloaded and file correct. Downloading will be ignored.",
                episode.source_id,
            )
            await self._update_episodes(
                episode.source_id,
                update_data={
                    "status": status.PUBLISHED,
                    "file_size": stored_file_size,
                    "published_at": episode.created_at,
                },
            )
            await self._update_all_rss(episode.source_id)
            raise DownloadingInterrupted(code=FinishCode.SKIP)

    async def _download_episode(self, episode: Episode):
        """ Allows to fetch info from external resource and extract audio from target video """

        await self._update_episodes(episode.source_id, update_data={"status": status.DOWNLOADING})

        try:
            result_filename = youtube_utils.download_audio(episode.watch_url, episode.file_name)
        except YoutubeDLError as error:
            logger.exception(
                "=== [%s] Downloading FAILED: Could not download track: %s. "
                "All episodes will be moved to the ERROR state",
                episode.source_id,
                error,
            )
            await Episode.async_update(
                db_session=self.db_session,
                filter_kwargs={"source_id": episode.source_id},
                update_data={"status": Episode.Status.ERROR},
            )
            raise DownloadingInterrupted(code=FinishCode.ERROR)

        logger.info("=== [%s] DOWNLOADING was done ===", episode.source_id)
        return result_filename

    async def _remove_unfinished(self, episode: Episode):
        """ Allows to find unfinished downloading and remove file from the storage (S3) """

        if episode.status not in (Episode.Status.NEW, Episode.Status.DOWNLOADING):
            logger.warning(
                "[%s] Episode is %s but file-size seems not correct. "
                "Removing not-correct file %s and reloading it from youtube.",
                episode.source_id,
                episode.status,
                episode.file_name,
            )
            self.storage.delete_file(episode.file_name)

    @staticmethod
    async def _process_file(episode: Episode, result_filename: str):
        """ Postprocessing for downloaded audio file """

        logger.info("=== [%s] POST PROCESSING === ", episode.source_id)
        youtube_utils.ffmpeg_preparation(result_filename)
        logger.info("=== [%s] POST PROCESSING was done === ", episode.source_id)

    async def _upload_file(self, episode: Episode, result_filename: str):
        """ Allows to upload file to the storage (S3) """

        logger.info("=== [%s] UPLOADING === ", episode.source_id)
        remote_url = podcast_utils.upload_episode(result_filename)
        if not remote_url:
            logger.warning("=== [%s] UPLOADING was broken === ")
            await self._update_episodes(
                episode.source_id, update_data={"status": status.ERROR, "file_size": 0}
            )
            raise DownloadingInterrupted(code=FinishCode.ERROR)

        await self._update_episodes(
            episode.source_id,
            update_data={"file_name": result_filename, "remote_url": remote_url},
        )
        logger.info("=== [%s] UPLOADING was done === ", episode.source_id)

    async def _update_all_rss(self, source_id: str):
        """ Allows to regenerate rss for all podcast with requested episode (by source_id) """

        logger.info("Episodes with source #%s: updating rss for all podcast", source_id)
        affected_episodes = await Episode.async_filter(self.db_session, source_id=source_id)
        podcast_ids = sorted([episode.podcast_id for episode in affected_episodes])
        logger.info("Found podcasts for rss updates: %s", podcast_ids)
        await GenerateRSSTask(db_session=self.db_session).run(*podcast_ids)

    async def _update_episodes(self, source_id: str, update_data: dict):
        """ Allows to update data for episodes (filtered by source_id)"""

        filter_kwargs = {"source_id": source_id, "status__ne": status.ARCHIVED}
        logger.debug("Episodes update filter: %s | data: %s", filter_kwargs, update_data)
        await Episode.async_update(
            self.db_session, filter_kwargs=filter_kwargs, update_data=update_data
        )

import os.path
import logging
from pathlib import Path

from yt_dlp.utils import YoutubeDLError

from core import settings
from common.redis import RedisClient
from common.storage import StorageS3
from common.enums import EpisodeStatus
from common.db_utils import make_session_maker
from common.exceptions import (
    DownloadingInterrupted,
    UserCancellationError,
)
from modules.media.models import File
from modules.podcast.models import Episode, cookie_file_ctx, Podcast
from modules.podcast.tasks.base import RQTask, TaskResultCode
from modules.podcast.tasks.rss import GenerateRSSTask
from modules.providers import utils as provider_utils
from modules.podcast import utils as podcast_utils
from modules.providers.utils import SOURCE_CFG_MAP, SourceConfig
from modules.providers import ffmpeg

log_levels = {
    TaskResultCode.SUCCESS: logging.INFO,
    TaskResultCode.SKIP: logging.INFO,
    TaskResultCode.ERROR: logging.ERROR,
    TaskResultCode.CANCEL: logging.WARNING,
}
logger = logging.getLogger(__name__)
__all__ = [
    "DownloadEpisodeTask",
    "UploadedEpisodeTask",
]


async def _async_episode_update(episode_id: int, new_status: Episode.Status):
    session_maker = make_session_maker()
    async with session_maker() as db_session:
        await Episode.async_update(
            db_session,
            filter_kwargs={"id": episode_id},
            update_data={"status": new_status},
        )
        await db_session.commit()


class DownloadEpisodeTask(RQTask):
    """
    Allows downloading media from the source and recreate podcast's rss (by requested episode_id)
    """

    storage: StorageS3
    tmp_audio_path: Path

    # pylint: disable=arguments-differ
    async def run(self, episode_id: int) -> TaskResultCode:
        self.storage = StorageS3()
        self.task_context = self.task_context or self._prepare_task_context(episode_id)

        try:
            code = await self.perform_run(int(episode_id))
            code_value = code.value

        except UserCancellationError as exc:
            message = "Episode downloading was interrupted by user canceling: %r"
            logger.log(log_levels[TaskResultCode.CANCEL], message, exc)
            code_value = TaskResultCode.CANCEL
            await Episode.async_update(
                self.db_session,
                filter_kwargs={"id": episode_id},
                update_data={"status": Episode.Status.NEW},
            )

        except DownloadingInterrupted as exc:
            message = "Episode downloading was interrupted: %r"
            logger.log(log_levels[exc.code], message, exc)
            code_value = exc.code.value

        except Exception as exc:
            logger.exception("Unable to prepare/publish episode: %r", exc)
            await Episode.async_update(
                self.db_session,
                filter_kwargs={"id": episode_id},
                update_data={"status": Episode.Status.ERROR},
            )
            code_value = TaskResultCode.ERROR

        finally:
            await self._publish_redis_signal()

        return code_value

    async def perform_run(self, episode_id: int) -> TaskResultCode:
        """
        Main operation for downloading, performing and uploading audio to the storage.

        :raise: DownloadingInterrupted (if downloading is broken or unnecessary)
        """

        episode: Episode = await Episode.async_get(self.db_session, id=episode_id)
        podcast: Podcast = await Podcast.async_get(self.db_session, id=episode.podcast_id)
        logger.info(
            "=== [%s] START downloading process URL: %s ===",
            episode.source_id,
            episode.watch_url,
        )

        await self._save_job_id(episode)
        await self._check_is_needed(episode)
        await self._remove_unfinished(episode)
        await self._update_episodes(episode, update_data={"status": Episode.Status.DOWNLOADING})
        self.tmp_audio_path = await self._download_episode(episode)

        await self._process_file(podcast, episode, self.tmp_audio_path)
        remote_file_size = await self._upload_file(episode, self.tmp_audio_path)
        await self._update_episodes(
            episode,
            update_data={
                "status": Episode.Status.PUBLISHED,
                "published_at": episode.created_at,
            },
        )
        await self._update_files(episode, {"size": remote_file_size, "available": True})
        await self._update_all_rss(episode.source_id)

        podcast_utils.delete_file(self.tmp_audio_path)

        logger.info("=== [%s] DOWNLOADING total finished ===", episode.source_id)
        return TaskResultCode.SUCCESS

    async def _save_job_id(self, episode: Episode) -> None:
        logger.info(
            "Saving taskID by episodes' filename: %s | jobID: %s",
            episode.audio_filename,
            self.task_context.job_id,
        )
        self.task_context.save_to_redis(filename=episode.audio_filename)

    async def _check_is_needed(self, episode: Episode) -> None:
        """Finding already downloaded file for episode's audio file path"""

        if not (audio_path := episode.audio.path):
            logger.debug(
                "[%s] No audio path is stored file on the DB: %s",
                episode.source_id,
                audio_path,
            )
            return

        stored_file_size = self.storage.get_file_size(dst_path=audio_path)
        if stored_file_size and stored_file_size == episode.audio.size:
            logger.info(
                "[%s] Episode already downloaded and file correct. Downloading will be ignored.",
                episode.source_id,
            )
            await self._update_episodes(
                episode,
                update_data={
                    "status": Episode.Status.PUBLISHED,
                    "published_at": episode.created_at,
                },
            )
            await self._update_files(episode, {"size": stored_file_size, "available": True})
            await self._update_all_rss(episode.source_id)
            raise DownloadingInterrupted(code=TaskResultCode.SKIP)

    async def _download_episode(self, episode: Episode) -> Path:
        """Fetching info from external resource and extract audio from target source"""
        source_config: SourceConfig = SOURCE_CFG_MAP[episode.source_type]
        if not source_config.need_downloading:
            if result_path := episode.audio.path:
                return Path(result_path)

            raise DownloadingInterrupted(
                code=TaskResultCode.ERROR,
                message="Episode [source: UPLOAD] does not contain audio with predefined path",
            )

        async with cookie_file_ctx(self.db_session, cookie_id=episode.cookie_id) as cookie:
            try:
                result_path = await provider_utils.download_audio(
                    episode.watch_url,
                    filename=episode.audio_filename,
                    cookie_path=(cookie.file_path if cookie else None),
                    proxy_url=source_config.proxy_url,
                )
            except YoutubeDLError as exc:
                logger.exception(
                    "=== [%s] Downloading FAILED: Could not download track: %r. "
                    "All episodes will be moved to the ERROR state",
                    episode.source_id,
                    exc,
                )
                await self._update_episodes(episode, {"status": Episode.Status.ERROR})
                await self._update_files(episode, {"available": False})
                raise DownloadingInterrupted(code=TaskResultCode.ERROR) from exc

        logger.info("=== [%s] DOWNLOADING was done ===", episode.source_id)
        return result_path

    async def _remove_unfinished(self, episode: Episode) -> None:
        """Finding unfinished downloading and remove file from the storage (S3)"""

        if not (audio_path := episode.audio.path):
            return

        if episode.status not in (Episode.Status.NEW, Episode.Status.DOWNLOADING):
            logger.warning(
                "[%s] Episode is %s but file-size seems not correct. "
                "Removing not-correct file %s and reloading it from providers.",
                episode.source_id,
                episode.status,
                audio_path,
            )
            self.storage.delete_file(audio_path)

    @staticmethod
    async def _process_file(podcast: Podcast, episode: Episode, tmp_audio_path: Path) -> None:
        """Postprocessing for downloaded audio file"""
        source_config: SourceConfig = SOURCE_CFG_MAP[episode.source_type]
        if source_config.need_postprocessing:
            logger.info("=== [%s] POST PROCESSING === ", episode.source_id)
            ffmpeg.ffmpeg_preparation(src_path=tmp_audio_path)
            ffmpeg.ffmpeg_set_metadata(
                src_path=tmp_audio_path,
                podcast_name=podcast.name,
                episode_id=episode.id,
                episode_title=episode.title,
                episode_chapters=episode.list_chapters or [],
            )
            logger.info("=== [%s] POST PROCESSING was done === ", episode.source_id)
        else:
            logger.info("=== [%s] POST PROCESSING SKIP === ", episode.source_id)

    async def _upload_file(self, episode: Episode, tmp_audio_path: Path) -> int:
        """Uploading file to the storage (S3)"""

        logger.info("=== [%s] UPLOADING === ", episode.source_id)
        remote_path = podcast_utils.upload_episode(tmp_audio_path)
        if not remote_path:
            logger.warning("=== [%s] UPLOADING was broken === ")
            await self._update_episodes(episode, {"status": Episode.Status.ERROR})
            raise DownloadingInterrupted(code=TaskResultCode.ERROR)

        await self._update_files(episode, {"path": remote_path})
        result_file_size = self.storage.get_file_size(tmp_audio_path.name)
        logger.info(
            "=== [%s] UPLOADING was done (%i bytes) === ",
            episode.source_id,
            result_file_size,
        )
        return result_file_size

    async def _update_all_rss(self, source_id: str) -> None:
        """Regenerating rss for all podcast with requested episode (by source_id)"""

        logger.info("=== [%s] Updating rss for all podcast === ", source_id)
        affected_episodes = await Episode.async_filter(self.db_session, source_id=source_id)
        podcast_ids = sorted([episode.podcast_id for episode in affected_episodes])
        logger.info("[%s] Found podcasts for rss updates: %s", source_id, podcast_ids)
        generate_rss_task = GenerateRSSTask(db_session=self.db_session)
        await generate_rss_task.run(*podcast_ids)

    async def _update_episodes(self, episode: Episode, update_data: dict) -> None:
        """Updating data for episodes (filtered by source_id and source_type)"""

        filter_kwargs = {
            "source_id": episode.source_id,
            "source_type": episode.source_type,
            "status__ne": Episode.Status.ARCHIVED,
        }
        logger.debug("Episodes update filter: %s | data: %s", filter_kwargs, update_data)
        await Episode.async_update(
            self.db_session,
            filter_kwargs=filter_kwargs,
            update_data=update_data,
            db_commit=True,
        )

    async def _update_files(self, episode: Episode, update_data: dict) -> None:
        """Updating data for stored files"""

        source_url = episode.audio.source_url
        logger.debug("Files update: source_url: %s | data: %s", source_url, update_data)
        await File.async_update(
            self.db_session,
            filter_kwargs={"source_url": source_url},
            update_data=update_data,
            db_commit=True,
        )

    @staticmethod
    async def _publish_redis_signal() -> None:
        await RedisClient().async_publish(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )


class UploadedEpisodeTask(DownloadEpisodeTask):
    """
    Allows preparations for already uploaded episodes (such as manually uploaded episodes)
    """

    async def perform_run(self, episode_id: int) -> TaskResultCode:
        """
        Main operation for downloading, performing and uploading audio to the storage.

        :raise: DownloadingInterrupted (if downloading is broken or unnecessary)
        """

        episode: Episode = await Episode.async_get(self.db_session, id=episode_id)
        logger.info(
            "=== [%s] START performing uploaded episodes: %s ===",
            episode.source_id,
            episode.audio.path,
        )
        remote_size = self.storage.get_file_size(dst_path=episode.audio.path)
        if episode.status == EpisodeStatus.PUBLISHED and remote_size == episode.audio.size:
            raise DownloadingInterrupted(
                code=TaskResultCode.SKIP,
                message=f"Episode #{episode_id} already published.",
            )

        if remote_size != episode.audio.size:
            raise DownloadingInterrupted(
                code=TaskResultCode.ERROR,
                message=(
                    f"Performing uploaded file failed: incorrect remote file size: {remote_size}"
                ),
            )

        remote_path = await self._copy_file(episode)
        remote_size = self.storage.get_file_size(os.path.basename(remote_path))

        await episode.update(
            self.db_session,
            status=Episode.Status.PUBLISHED,
            published_at=episode.created_at,
        )
        await episode.audio.update(
            self.db_session,
            path=remote_path,
            size=remote_size,
            available=True,
        )
        await self._update_all_rss(episode.source_id)
        await self.db_session.flush()
        # self._delete_tmp_file(old_path)
        logger.info("=== [%s] DOWNLOADING total finished ===", episode.source_id)
        return TaskResultCode.SUCCESS

    async def _copy_file(self, episode: Episode) -> str:
        """Uploading file to the storage (S3)"""

        logger.info("=== [%s] REMOTE COPYING === ", episode.source_id)
        dst_path = os.path.join(settings.S3_BUCKET_AUDIO_PATH, episode.audio_filename)
        remote_path = podcast_utils.remote_copy_episode(
            src_path=episode.audio.path,
            dst_path=dst_path,
            src_file_size=episode.audio.size,
            # task_context=self.task_context,
        )
        if not remote_path:
            logger.warning("=== [%s] REMOTE COPYING was broken === ")
            await episode.update(self.db_session, status=Episode.Status.ERROR)
            raise DownloadingInterrupted(code=TaskResultCode.ERROR)

        logger.info(
            "=== [%s] REMOTE COPYING was done (%s -> %s):  === ",
            episode.source_id,
            episode.audio.path,
            remote_path,
        )
        return remote_path

    def _delete_tmp_file(self, old_file_path: str):
        logger.debug("Removing old file %s...", old_file_path)
        self.storage.delete_file(dst_path=old_file_path)
        logger.debug("Removing done for old file %s.", old_file_path)

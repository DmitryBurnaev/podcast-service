import asyncio
import logging
from pathlib import Path

from core import settings
from common.utils import download_content
from common.storage import StorageS3
from common.exceptions import NotFoundError, MaxAttemptsReached
from modules.media.models import File
from modules.podcast.models import Episode
from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import TaskResultCode
from modules.podcast.utils import get_file_size
from modules.providers import ffmpeg

logger = logging.getLogger(__name__)


class BaseEpisodePostProcessTask(RQTask):
    storage: StorageS3
    MAX_UPLOAD_ATTEMPT = 5

    # pylint: disable=arguments-differ
    async def run(self, episode_id: int | None = None) -> TaskResultCode:
        self.storage = StorageS3()
        try:
            code = await self.perform_run(episode_id)
        except Exception as exc:
            logger.exception("Unable to process episode: episode %s | error: %r", episode_id, exc)
            return TaskResultCode.ERROR

        return code

    async def perform_run(self, episode_id: int | None) -> TaskResultCode:
        raise NotImplementedError()


class DownloadEpisodeImageTask(BaseEpisodePostProcessTask):
    """Allows fetching episodes image (cover), prepare them and upload to S3"""

    async def perform_run(self, episode_id: int | None) -> TaskResultCode:
        filter_kwargs = {}
        if episode_id:
            filter_kwargs["id"] = int(episode_id)

        episodes = list(await Episode.async_filter(self.db_session, **filter_kwargs))
        episodes_count = len(episodes)

        for index, episode in enumerate(episodes, start=1):
            logger.info("=== Episode %i from %i ===", index, episodes_count)
            image: File = episode.image
            if image.path.startswith(settings.S3_BUCKET_IMAGES_PATH):
                logger.info("Skip episode %i | image URL: %s", episode.id, episode.image_url)
                continue

            if tmp_path := await self._download_and_crop_image(episode):
                remote_path = await self._upload_cover(episode, tmp_path)
                available = True
                size = get_file_size(tmp_path)
            else:
                remote_path, available, size = "", False, None

            logger.info("Saving new image URL: episode %s | remote %s", episode.id, remote_path)
            await image.update(
                self.db_session,
                path=remote_path,
                available=available,
                public=False,
                size=size,
            )

        return TaskResultCode.SUCCESS

    @staticmethod
    async def _download_and_crop_image(episode: Episode) -> Path | None:
        try:
            tmp_path = await download_content(episode.image.source_url, file_ext="jpg")
        except NotFoundError:
            return None

        ffmpeg.ffmpeg_preparation(src_path=tmp_path, ffmpeg_params=["-vf", "scale=600:-1"])
        return tmp_path

    async def _upload_cover(self, episode: Episode, tmp_path: Path) -> str:
        attempt = 1
        while attempt <= self.MAX_UPLOAD_ATTEMPT:
            if remote_path := self.storage.upload_file(
                src_path=str(tmp_path),
                dst_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH,
                filename=Episode.generate_image_name(episode.source_id),
            ):
                return remote_path

            attempt += 1
            await asyncio.sleep(attempt)

        raise MaxAttemptsReached("Couldn't upload cover for episode")


class ApplyMetadataEpisodeTask(BaseEpisodePostProcessTask):

    async def perform_run(self, episode_id: int) -> TaskResultCode:
        # getting episode from DB
        episode: Episode = await Episode.async_get(self.db_session, id=int(episode_id))
        if not episode:
            logger.error("EpisodeMetaData %s: unable to find episode", episode_id)
            return TaskResultCode.ERROR

        if not episode.chapters:
            logger.error("EpisodeMetaData %r: unable to find episode chapters (skipping)", episode)
            return TaskResultCode.SKIP

        logger.info(f"Applying metadata for episode %s", episode_id)
        logger.debug(f"EpisodeMetaData: %r | got chapters: %s", episode, episode.list_chapters)

        # downloading already exists file from S3 storage
        local_file_path = await self._download_episode(episode)
        logger.debug(f"EpisodeMetaData: %r | episode downloaded: %r", episode, local_file_path)

        # apply prepared metadata to the downloaded fiel
        ffmpeg.ffmpeg_set_metadata(
            src_path=local_file_path,
            episode_title=episode.title,
            episode_chapters=episode.list_chapters,
        )
        logger.debug("EpisodeMetaData: %r | applied metadata %s", episode, episode.list_chapters)

        # upload file back to S3
        remote_path = await self._upload_episode(episode=episode, tmp_path=local_file_path)
        logger.info(
            "EpisodeMetaData %r | metadata applied and episode uploaded to %s",
            episode,
            remote_path,
        )
        return TaskResultCode.SUCCESS

    async def _download_episode(self, episode: Episode) -> Path:
        """Download episode from S3 with our client and returns path to tmp file with it"""
        # tmp_path = settings.TMP_AUDIO_PATH / f"tmp_episode_{episode.source_id}.mp3"
        tmp_path = Path(".misc") / "audio" / f"tmp_episode_{episode.source_id}.mp3"
        result_path = self.storage.download_file(
            src_path=str(episode.audio.path),
            dst_path=str(tmp_path),
        )
        if result_path is None:
            raise FileNotFoundError(f"Episode {episode.id} could not be downloaded")

        return tmp_path

    async def _upload_episode(self, episode: Episode, tmp_path: Path) -> str:
        """Upload episode back to S3"""
        attempt = 1
        while attempt <= self.MAX_UPLOAD_ATTEMPT:
            if remote_path := self.storage.upload_file(
                src_path=str(tmp_path),
                dst_path=settings.S3_BUCKET_AUDIO_PATH,
                filename=episode.audio_filename,
            ):
                return remote_path

            attempt += 1
            await asyncio.sleep(attempt)

        raise MaxAttemptsReached("Couldn't upload episode")

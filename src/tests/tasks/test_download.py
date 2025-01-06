import uuid
import os.path
from typing import TYPE_CHECKING
from pathlib import Path
from unittest.mock import patch, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yt_dlp.utils import DownloadError

from common.exceptions import NotFoundError
from core import settings
from modules.media.models import File
from modules.podcast.models import Episode, Podcast, Cookie
from common.enums import EpisodeStatus, SourceType
from modules.podcast.tasks import DownloadEpisodeTask
from modules.podcast.tasks.process import DownloadEpisodeImageTask
from modules.podcast.tasks.base import TaskResultCode
from modules.providers.utils import download_process_hook, SOURCE_CFG_MAP
from tests.api.test_base import BaseTestCase
from tests.helpers import get_podcast_data, create_episode
from tests.mocks import (
    MockYoutubeDL,
    MockRedisClient,
    MockS3Client,
    MockGenerateRSS,
    MockSensitiveData,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

pytestmark = pytest.mark.asyncio


class TestDownloadEpisodeTask(BaseTestCase):
    @staticmethod
    async def _source_file(dbs, episode: Episode) -> Path:
        audio: File = await File.async_get(dbs, id=episode.audio_id)
        file_path = settings.TMP_AUDIO_PATH / audio.name
        with open(file_path, "wb") as f:
            f.write(b"EpisodeData")
        return file_path

    async def test_downloading_ok(
        self,
        dbs: AsyncSession,
        podcast: Podcast,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_ffmpeg_set_meta: Mock,
        mocked_redis: MockRedisClient,
        mocked_s3: MockS3Client,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        mocked_s3.get_file_size.return_value = 123

        file_path = await self._source_file(dbs, episode)
        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)
        episode: Episode = await Episode.async_get(dbs, id=episode.id)

        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(src_path=file_path)
        mocked_ffmpeg_set_meta.assert_called_with(
            src_path=file_path,
            metadata=episode.generate_metadata(),
        )
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)
        mocked_redis.publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH, message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        )

        assert result == TaskResultCode.SUCCESS
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

        created_audio = await File.async_get(dbs, id=episode.audio_id)
        assert created_audio is not None
        assert created_audio.available
        assert created_audio.path == mocked_s3.get_mocked_remote_path(file_path)
        assert created_audio.owner_id == episode.owner_id
        assert created_audio.size == 123

    async def test_downloading__using_cookies__ok(
        self,
        dbs: AsyncSession,
        cookie: Cookie,
        podcast: Podcast,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_ffmpeg_set_meta: Mock,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
        mocked_sens_data: MockSensitiveData,
    ):
        file_path = await self._source_file(dbs, episode)
        await episode.update(dbs, cookie_id=cookie.id, db_commit=True)

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.SUCCESS

        mocked_youtube.assert_called_with(cookiefile=await cookie.as_file())
        mocked_ffmpeg.assert_called_with(src_path=file_path)
        mocked_ffmpeg_set_meta.assert_called_with(
            src_path=file_path,
            metadata=episode.generate_metadata(),
        )

        episode = await Episode.async_get(dbs, id=episode.id)
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at
        mocked_sens_data.decrypt.assert_called_with(cookie.data)

    async def test_downloading__using_proxy__ok(
        self,
        dbs: AsyncSession,
        episode: Episode,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_ffmpeg_set_meta: Mock,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
        mocked_sens_data: MockSensitiveData,
        monkeypatch: "MonkeyPatch",
    ):
        proxy_url = "socks5://socks5user:pass@socks5host:2080"
        monkeypatch.setattr(SOURCE_CFG_MAP[SourceType.YOUTUBE], "proxy_url", proxy_url)
        file_path = await self._source_file(dbs, episode)

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.SUCCESS

        mocked_youtube.assert_called_with(proxy=proxy_url)
        mocked_ffmpeg.assert_called_with(src_path=file_path)
        mocked_ffmpeg_set_meta.assert_called_with(
            src_path=file_path,
            metadata=episode.generate_metadata(),
        )

        episode = await Episode.async_get(dbs, id=episode.id)
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    async def test_skip_postprocessing(
        self,
        dbs: AsyncSession,
        cookie: Cookie,
        podcast: Podcast,
        episode: Episode,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_ffmpeg: Mock,
        mocked_youtube: MockYoutubeDL,
        mocked_generate_rss_task: MockGenerateRSS,
        mocked_source_info_yandex: Mock,
        mocked_sens_data: MockSensitiveData,
    ):
        file_path = await self._source_file(dbs, episode)
        await episode.update(
            dbs, cookie_id=cookie.id, source_type=SourceType.YANDEX, db_commit=True
        )

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)

        mocked_ffmpeg.assert_not_called()
        assert result == TaskResultCode.SUCCESS
        assert episode.status == Episode.Status.PUBLISHED
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_sens_data.decrypt.assert_called_with(cookie.data)

    async def test_file_correct__skip(
        self,
        dbs: AsyncSession,
        episode_data: dict,
        podcast_data: dict,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_ffmpeg: Mock,
        mocked_youtube: MockYoutubeDL,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data())
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data())

        episode_data.update(
            {
                "status": EpisodeStatus.PUBLISHED,
                "source_id": mocked_youtube.source_id,
                "watch_url": mocked_youtube.watch_url,
                "podcast_id": podcast_1.id,
            }
        )
        episode = await create_episode(dbs, episode_data=episode_data)
        await episode.audio.update(dbs, size=1024)

        episode_data["status"] = EpisodeStatus.NEW
        episode_data["podcast_id"] = podcast_2.id
        episode_data["audio_path"] = episode.audio.path
        episode_2 = await create_episode(dbs, episode_data=episode_data)
        await episode_2.audio.update(dbs, size=1024)

        await dbs.commit()

        mocked_s3.get_file_size.return_value = 1024
        result = await DownloadEpisodeTask(db_session=dbs).run(episode_2.id)
        await dbs.refresh(episode_2)
        mocked_generate_rss_task.run.assert_called_with(podcast_1.id, podcast_2.id)
        assert result == TaskResultCode.SKIP
        assert not mocked_youtube.download.called
        assert not mocked_ffmpeg.called
        assert episode_2.status == Episode.Status.PUBLISHED
        assert episode_2.published_at == episode_2.created_at

        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

    async def test_file_bad_size__ignore(
        self,
        dbs: AsyncSession,
        podcast: Podcast,
        episode_data: dict,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_ffmpeg: Mock,
        mocked_ffmpeg_set_meta: Mock,
        mocked_youtube: MockYoutubeDL,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        episode_data.update(
            {
                "status": EpisodeStatus.PUBLISHED,
                "source_id": mocked_youtube.source_id,
                "watch_url": mocked_youtube.watch_url,
            }
        )
        episode = await create_episode(dbs, episode_data=episode_data)
        await episode.audio.update(dbs, size=1024)

        file_path = await self._source_file(dbs, episode)

        mocked_s3.get_file_size.return_value = 32

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)

        await dbs.refresh(episode)
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(src_path=file_path)
        mocked_ffmpeg_set_meta.assert_called_with(
            src_path=file_path,
            metadata=episode.generate_metadata(),
        )
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

        assert result == TaskResultCode.SUCCESS
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

    async def test_downloading_failed__roll_back_changes__ok(
        self,
        dbs: AsyncSession,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_s3: MockS3Client,
        mocked_generate_rss_task: MockGenerateRSS,
        mocked_redis: MockRedisClient,
    ):
        await self._source_file(dbs, episode)
        mocked_youtube.download.side_effect = DownloadError("Video is not available")

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)

        episode = await Episode.async_get(dbs, id=episode.id)
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

        assert result == TaskResultCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    async def test_unexpected_error__ok(
        self,
        dbs: AsyncSession,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
        mocked_redis: MockRedisClient,
    ):
        mocked_youtube.download.side_effect = RuntimeError("Oops")
        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)
        episode = await Episode.async_get(dbs, id=episode.id)
        assert result == TaskResultCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None
        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

    async def test_upload_to_s3_failed__fail(
        self,
        dbs: AsyncSession,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        await self._source_file(dbs, episode)

        mocked_s3.upload_file.side_effect = lambda *_, **__: ""

        result = await DownloadEpisodeTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.ERROR

        mocked_generate_rss_task.run.assert_not_called()
        episode = await Episode.async_get(dbs, id=episode.id)
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None
        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

    @patch("modules.providers.utils.episode_process_hook")
    async def test_download_process_hook__ok(self, mocked_process_hook):
        event = {
            "total_bytes": 1024,
            "filename": "test-episode.mp3",
            "downloaded_bytes": 24,
        }
        download_process_hook(event)
        self.assert_called_with(
            mocked_process_hook,
            status=EpisodeStatus.DL_EPISODE_DOWNLOADING,
            filename="test-episode.mp3",
            total_bytes=1024,
            processed_bytes=24,
        )

    async def test_download__cancel__check_teardown_logic(
        self,
        mocked_youtube: MockYoutubeDL,
        mocked_ffmpeg: Mock,
        mocked_redis: MockRedisClient,
        mocked_s3: MockS3Client,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        assert True
        # TODO: implement test with real calling teardown method (and checking ffmpeg calling)
        # await episode.update(dbs, status=Episode.Status.CANCELING)
        #
        # state_data = StateData(
        #     action=TaskInProgressAction.DOWNLOADING, data={"episode_id": episode.id}
        # )
        # DownloadEpisodeTask(db_session=dbs).teardown(state_data=state_data)
        #
        # await dbs.refresh(episode)
        # assert episode.status == Episode.Status.NEW


class TestDownloadEpisodeImageTask(BaseTestCase):
    @patch("modules.podcast.models.Episode.generate_image_name")
    @patch("modules.podcast.tasks.process.get_file_size")
    @patch("modules.podcast.tasks.process.download_content")
    async def test_image_ok(
        self,
        mocked_download_content: Mock,
        mocked_file_size: Mock,
        mocked_name: Mock,
        dbs: AsyncSession,
        episode: Episode,
        mocked_s3: MockS3Client,
        mocked_ffmpeg: Mock,
    ):
        tmp_path: Path = settings.TMP_IMAGE_PATH / f"{episode.source_id}.jpg"
        mocked_download_content.return_value = tmp_path
        mocked_file_size.return_value = 25

        # we mark image as "public" in order to access before it downloaded
        await episode.image.update(dbs, public=True, db_commit=True)

        source_image_url = episode.image.source_url
        new_remote_path = f"/remote/path/to/images/episode_{uuid.uuid4().hex}_image.png"
        mocked_s3.upload_file.side_effect = lambda *_, **__: new_remote_path
        mocked_name.return_value = f"episode-image-name-{episode.source_id}.jpg"

        result = await DownloadEpisodeImageTask(db_session=dbs).run(episode.id)
        await dbs.refresh(episode)
        assert result == TaskResultCode.SUCCESS
        assert episode.image_id is not None

        image = await File.async_get(dbs, id=episode.image_id)
        assert image.path == new_remote_path
        assert image.available is True
        assert image.public is False
        assert image.size == 25

        mocked_ffmpeg.assert_called_with(src_path=tmp_path, ffmpeg_params=["-vf", "scale=600:-1"])
        mocked_download_content.assert_called_with(source_image_url, file_ext="jpg")
        mocked_s3.upload_file.assert_called_with(
            src_path=str(tmp_path),
            dst_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH,
            filename=f"episode-image-name-{episode.source_id}.jpg",
        )

    @patch("modules.podcast.tasks.process.download_content")
    async def test_image_not_found__use_default(
        self,
        mocked_download_content: Mock,
        dbs: AsyncSession,
        episode: Episode,
    ):
        mocked_download_content.side_effect = NotFoundError()
        result = await DownloadEpisodeImageTask(db_session=dbs).run(episode.id)
        await dbs.refresh(episode)
        assert result == TaskResultCode.SUCCESS
        assert episode.image.public is False
        assert episode.image.available is False
        assert episode.image_url == settings.DEFAULT_EPISODE_COVER

    @patch("modules.podcast.tasks.process.download_content")
    async def test_skip_already_downloaded(
        self,
        mocked_download_content: Mock,
        dbs: AsyncSession,
        episode: Episode,
    ):
        remote_path = os.path.join(
            settings.S3_BUCKET_IMAGES_PATH, "episode_{uuid.uuid4().hex}_image.png"
        )
        await episode.image.update(dbs, path=remote_path, available=True)
        result = await DownloadEpisodeImageTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.SUCCESS

        await dbs.refresh(episode)
        image: File = await File.async_get(dbs, id=episode.image_id)
        assert image.path == remote_path
        assert mocked_download_content.assert_not_awaited

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from modules.auth.models import User
from modules.media.models import File
from modules.podcast.models import Episode, Podcast
from common.enums import EpisodeStatus, SourceType, FileType
from modules.podcast.tasks import UploadedEpisodeTask
from modules.podcast.tasks.base import TaskResultCode
from tests.api.test_base import BaseTestCase
from tests.helpers import get_episode_data, get_source_id
from tests.mocks import MockS3Client, MockRedisClient, MockGenerateRSS

pytestmark = pytest.mark.asyncio


class TestUploadedEpisodeTask(BaseTestCase):
    @staticmethod
    async def _episode(
        dbs: AsyncSession,
        podcast: Podcast,
        creator: User,
        file_size: int = 32,
        source_id: str | None = None,
    ) -> Episode:
        episode_data = get_episode_data(podcast=podcast, creator=creator, source_id=source_id)
        episode_data["source_type"] = SourceType.UPLOAD
        episode_data["watch_url"] = ""

        audio = await File.create(
            dbs,
            FileType.AUDIO,
            size=file_size,
            available=False,
            owner_id=creator.id,
            path=f"/tmp/remote/episode_{episode_data['source_id']}.mp3",
        )
        episode_data["audio_id"] = audio.id
        episode = await Episode.async_create(dbs, **episode_data)
        await dbs.commit()
        episode.audio = audio
        return episode

    async def test_run_ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        mocked_s3.get_file_size.return_value = 1024
        source_id = get_source_id(prefix="upl")
        episode = await self._episode(dbs, podcast, user, file_size=1024, source_id=source_id)

        tmp_remote = f"/tmp/remote/episode_{episode.source_id}.mp3"
        new_remote = f"audio/episode_{episode.source_id}.mp3"
        mocked_s3.copy_file.return_value = new_remote

        result = await UploadedEpisodeTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.SUCCESS

        await dbs.refresh(episode)
        await dbs.refresh(episode.audio)

        assert episode.status == EpisodeStatus.PUBLISHED
        assert episode.published_at == episode.created_at
        assert episode.audio.available is True
        assert episode.audio.path == new_remote

        self.assert_called_with(mocked_s3.copy_file, src_path=tmp_remote)
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)
        mocked_redis.publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH, message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        )
        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH, message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        )

    async def test_file_bad_size__error(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        mocked_s3.get_file_size.return_value = 32
        episode = await self._episode(dbs, podcast, user, file_size=1024)

        result = await UploadedEpisodeTask(db_session=dbs).run(episode.id)
        await dbs.refresh(episode)

        assert result == TaskResultCode.ERROR
        assert episode.status == Episode.Status.NEW
        assert episode.published_at is None
        assert not episode.audio.available

        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()
        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

    async def test_move_s3_failed__error(
        self,
        dbs: AsyncSession,
        podcast: Podcast,
        user: User,
        mocked_s3: MockS3Client,
        mocked_redis: MockRedisClient,
        mocked_generate_rss_task: MockGenerateRSS,
    ):
        mocked_s3.get_file_size.return_value = 1024
        mocked_s3.copy_file.side_effect = RuntimeError("Oops")
        episode = await self._episode(dbs, podcast, user, file_size=1024)

        result = await UploadedEpisodeTask(db_session=dbs).run(episode.id)
        assert result == TaskResultCode.ERROR

        mocked_generate_rss_task.run.assert_not_called()
        episode = await Episode.async_get(dbs, id=episode.id)
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None
        assert not episode.audio.available
        mocked_redis.async_publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH,
            message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL,
        )

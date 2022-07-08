import os.path
import uuid
from pathlib import Path
from typing import Coroutine
from unittest.mock import patch

from youtube_dl.utils import DownloadError

from common.exceptions import NotFoundError
from core import settings
from modules.auth.models import User
from modules.media.models import File
from modules.podcast.models import Episode, Podcast
from common.enums import EpisodeStatus, SourceType, FileType
from modules.podcast.tasks import DownloadEpisodeTask, DownloadEpisodeImageTask, UploadedEpisodeTask
from modules.podcast.tasks.base import FinishCode
from modules.providers.utils import download_process_hook
from tests.api.test_base import BaseTestCase
from tests.helpers import get_podcast_data, await_, create_episode, get_episode_data


class TestUploadedEpisodeTask(BaseTestCase):

    @staticmethod
    async def _episode(dbs, podcast: Podcast, creator: User, file_size: int = 32) -> Episode:
        episode_data = get_episode_data(podcast, creator=creator)
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

    def test_run_ok(self, dbs, podcast, user, mocked_s3, mocked_generate_rss_task):
        episode = await_(self._episode(dbs, podcast, user))
        mocked_s3.move_file.return_value = f'/remote/path/episode_{episode.source_id}.mp3'

        result = await_(UploadedEpisodeTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        await_(dbs.refresh(episode.audio))

        assert result == FinishCode.OK
        assert episode.status == EpisodeStatus.PUBLISHED
        assert episode.audio.available is True
        assert episode.audio.path == f'/remote/path/episode_{episode.source_id}.mp3'

        self.assert_called_with(
            mocked_s3.move_file,
            src_path=episode.audio.path,
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    def test_file_bad_size__ignore(
        self,
        dbs,
        user,
        podcast,
        mocked_s3,
        mocked_generate_rss_task,
    ):
        episode = await_(self._episode(dbs, podcast, user, file_size=1024))
        mocked_s3.get_file_size.return_value = 32

        result = await_(UploadedEpisodeTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))

        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.NEW
        assert episode.published_at is None
        assert episode.audio.available is False

        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

    def test_unexpected_error__ok(self, episode, mocked_youtube, dbs):
        mocked_youtube.download.side_effect = RuntimeError("Oops")
        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))
        episode = await_(Episode.async_get(dbs, id=episode.id))
        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    def test_upload_to_s3_failed__fail(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task, dbs
    ):
        self._source_file(dbs, episode)

        mocked_s3.upload_file.side_effect = lambda *_, **__: ""

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))
        assert result == FinishCode.ERROR

        mocked_generate_rss_task.run.assert_not_called()
        episode = await_(Episode.async_get(dbs, id=episode.id))
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    @patch("modules.providers.utils.episode_process_hook")
    def test_download_process_hook__ok(self, mocked_process_hook):
        event = {
            "total_bytes": 1024,
            "filename": "test-episode.mp3",
            "downloaded_bytes": 24,
        }
        download_process_hook(event)
        mocked_process_hook.assert_called_with(
            status=EpisodeStatus.DL_EPISODE_DOWNLOADING,
            filename="test-episode.mp3",
            total_bytes=1024,
            processed_bytes=24,
        )

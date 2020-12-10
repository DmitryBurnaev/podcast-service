from unittest.mock import patch

from youtube_dl.utils import DownloadError

from core import settings
from modules.podcast.models import Episode, Podcast
from modules.podcast.tasks import DownloadEpisodeTask
from modules.podcast.tasks.base import FinishCode
from modules.podcast.utils import EpisodeStatuses
from modules.youtube.utils import download_process_hook
from tests.api.test_base import BaseTestCase
from tests.helpers import get_podcast_data, async_run


class TestDownloadEpisodeTask(BaseTestCase):
    def test_download_episode__ok(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        result = async_run(DownloadEpisodeTask().run(episode.id))
        episode = async_run(Episode.async_get(id=episode.id))

        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(episode.file_name)
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    def test_download_episode__file_correct__ignore(
        self,
        episode_data,
        podcast_data,
        mocked_youtube,
        mocked_ffmpeg,
        mocked_s3,
        mocked_generate_rss_task,
    ):
        podcast_1 = async_run(Podcast.create(**get_podcast_data()))
        podcast_2 = async_run(Podcast.create(**get_podcast_data()))

        episode_data.update(
            {
                "status": "published",
                "source_id": mocked_youtube.video_id,
                "watch_url": mocked_youtube.watch_url,
                "file_size": 1024,
                "podcast_id": podcast_1.id,
            }
        )
        async_run(Episode.create(**episode_data))

        episode_data["status"] = "new"
        episode_data["podcast_id"] = podcast_2.id
        episode_2 = async_run(Episode.create(**episode_data))

        mocked_s3.get_file_size.return_value = episode_2.file_size

        result = async_run(DownloadEpisodeTask().run(episode_2.id))
        episode_2 = async_run(Episode.async_get(id=episode_2.id))

        mocked_generate_rss_task.run.assert_called_with(podcast_1.id, podcast_2.id)
        assert result == FinishCode.SKIP
        assert not mocked_youtube.download.called
        assert not mocked_ffmpeg.called
        assert episode_2.status == Episode.Status.PUBLISHED
        assert episode_2.published_at == episode_2.created_at

    def test_download_episode__file_bad_size__ignore(
        self, episode_data, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task
    ):

        episode_data.update(
            {
                "status": "published",
                "source_id": mocked_youtube.video_id,
                "watch_url": mocked_youtube.watch_url,
                "file_size": 1024,
            }
        )
        episode = async_run(Episode.create(**episode_data))

        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        mocked_s3.get_file_size.return_value = 32

        result = async_run(DownloadEpisodeTask().run(episode.id))

        episode = async_run(Episode.async_get(id=episode.id))
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(episode.file_name)
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    def test_download_episode__downloading_failed__roll_back_changes__ok(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        mocked_youtube.download.side_effect = DownloadError("Video is not available")

        result = async_run(DownloadEpisodeTask().run(episode.id))

        episode = async_run(Episode.async_get(id=episode.id))
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.NEW
        assert episode.published_at is None

    def test_download_episode__upload_to_s3_failed__fail(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        mocked_s3.upload_file.side_effect = lambda *_, **__: ""

        result = async_run(DownloadEpisodeTask().run(episode.id))
        assert result == FinishCode.ERROR

        mocked_generate_rss_task.run.assert_not_called()
        episode = async_run(Episode.async_get(id=episode.id))
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    @patch("modules.youtube.utils.episode_process_hook")
    def test_download_process_hook__ok(self, mocked_process_hook):
        event = {
            "total_bytes": 1024,
            "filename": "test-episode.mp3",
            "downloaded_bytes": 24,
        }
        download_process_hook(event)
        mocked_process_hook.assert_called_with(
            status=EpisodeStatuses.episode_downloading,
            filename="test-episode.mp3",
            total_bytes=1024,
            processed_bytes=24,
        )

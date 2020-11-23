from core import settings
from modules.podcast.models import Episode
from modules.podcast.tasks import DownloadEpisodeTask
from tests.integration.api.test_base import BaseTestCase


class TestDownloadEpisodeTask(BaseTestCase):

    @staticmethod
    def assert_called_with(mock_callable, *args, **kwargs):
        assert mock_callable.called
        mock_call_args = mock_callable.call_args_list[-1]
        assert mock_call_args.args == args
        for key, value in kwargs.items():
            assert key in mock_call_args.kwargs, mock_call_args.kwargs
            assert mock_call_args.kwargs[key] == value

    def test_download_episode__ok(
        self,
        episode,
        mocked_youtube,
        mocked_ffmpeg,
        mocked_s3,
        mocked_redis,
        mocked_generate_rss_task
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        task = DownloadEpisodeTask()
        self.async_run(task.run(episode.id))

        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(episode.file_name)
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

        episode = self.async_run(Episode.async_get(id=episode.id))
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

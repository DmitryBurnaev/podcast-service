import uuid
from unittest.mock import patch
from urllib.parse import urljoin

from youtube_dl.utils import DownloadError

from common.exceptions import NotFoundError
from core import settings
from modules.podcast.models import Episode, Podcast, EpisodeStatus
from modules.podcast.tasks import DownloadEpisodeTask, DownloadEpisodeImageTask
from modules.podcast.tasks.base import FinishCode
from modules.providers.utils import download_process_hook
from tests.api.test_base import BaseTestCase
from tests.helpers import get_podcast_data, await_


class TestDownloadEpisodeTask(BaseTestCase):
    def test_download_episode__ok(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task, dbs
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))
        episode = await_(Episode.async_get(dbs, id=episode.id))

        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(src_path=file_path)
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
        dbs,
    ):
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data()))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data()))

        episode_data.update(
            {
                "status": "published",
                "remote_id": mocked_youtube.video_id,
                "watch_url": mocked_youtube.watch_url,
                "file_size": 1024,
                "podcast_id": podcast_1.id,
            }
        )
        await_(Episode.async_create(dbs, **episode_data))
        episode_data["status"] = "new"
        episode_data["podcast_id"] = podcast_2.id
        episode_2 = await_(Episode.async_create(dbs, **episode_data))
        await_(dbs.commit())

        mocked_s3.get_file_size.return_value = episode_2.file_size
        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode_2.id))
        await_(dbs.refresh(episode_2))
        mocked_generate_rss_task.run.assert_called_with(podcast_1.id, podcast_2.id)
        assert result == FinishCode.SKIP
        assert not mocked_youtube.download.called
        assert not mocked_ffmpeg.called
        assert episode_2.status == Episode.Status.PUBLISHED
        assert episode_2.published_at == episode_2.created_at

    def test_download_episode__file_bad_size__ignore(
        self,
        episode_data,
        mocked_youtube,
        mocked_ffmpeg,
        mocked_s3,
        mocked_generate_rss_task,
        dbs,
    ):

        episode_data.update(
            {
                "status": "published",
                "remote_id": mocked_youtube.video_id,
                "watch_url": mocked_youtube.watch_url,
                "file_size": 1024,
            }
        )
        episode = await_(Episode.async_create(dbs, db_commit=True, **episode_data))

        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        mocked_s3.get_file_size.return_value = 32

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))

        await_(dbs.refresh(episode))
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_ffmpeg.assert_called_with(src_path=file_path)
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
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task, dbs
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

        mocked_youtube.download.side_effect = DownloadError("Video is not available")

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))

        episode = await_(Episode.async_get(dbs, id=episode.id))
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    def test_download_episode__unexpected_error__ok(self, episode, mocked_youtube, dbs):
        mocked_youtube.download.side_effect = RuntimeError("Oops")
        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))
        episode = await_(Episode.async_get(dbs, id=episode.id))
        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

    def test_download_episode__upload_to_s3_failed__fail(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task, dbs
    ):
        file_path = settings.TMP_AUDIO_PATH / episode.file_name
        with open(file_path, "wb") as file:
            file.write(b"EpisodeData")

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


class TestDownloadEpisodeImageTask(BaseTestCase):
    @patch("modules.podcast.models.Episode.generate_image_name")
    @patch("modules.podcast.tasks.download.ffmpeg_preparation")
    @patch("modules.podcast.tasks.download.download_content")
    def test_download_image__ok(
        self, mocked_download_content, mocked_ffmpeg, mocked_name, episode, mocked_s3, dbs
    ):
        tmp_path = settings.TMP_IMAGE_PATH / f"{episode.remote_id}.jpg"
        mocked_download_content.return_value = tmp_path
        old_image_url = episode.image_url
        new_url = f"https://url-to-image.com/cover-{uuid.uuid4().hex}"
        mocked_s3.upload_file.side_effect = lambda *_, **__: new_url
        mocked_name.return_value = "episode-test-random-name.jpg"

        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        assert episode.image_url == new_url
        mocked_ffmpeg.assert_called_with(src_path=tmp_path, ffmpeg_params=["-vf", "scale=600:-1"])
        mocked_download_content.assert_called_with(old_image_url, file_ext="jpg")
        mocked_s3.upload_file.assert_called_with(
            src_path=str(tmp_path),
            dst_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH,
            filename="episode-test-random-name.jpg",
        )

    @patch("modules.podcast.tasks.download.download_content")
    def test_download__image_not_found__use_default(self, mocked_download_content, episode, dbs):
        mocked_download_content.side_effect = NotFoundError()
        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        assert episode.image_url == settings.DEFAULT_EPISODE_COVER

    @patch("modules.podcast.tasks.download.download_content")
    def test_download__skip_already_downloaded(self, mocked_download_content, episode, dbs):
        url = urljoin(settings.S3_STORAGE_URL, "images/episode-default.jpg")
        await_(episode.update(dbs, image_url=url))
        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        assert episode.image_url == url
        assert mocked_download_content.assert_not_awaited

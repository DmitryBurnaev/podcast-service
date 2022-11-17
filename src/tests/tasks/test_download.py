import os.path
import uuid
from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from common.exceptions import NotFoundError
from core import settings
from modules.media.models import File
from modules.podcast.models import Episode, Podcast
from common.enums import EpisodeStatus, SourceType
from modules.podcast.tasks import DownloadEpisodeTask, DownloadEpisodeImageTask
from modules.podcast.tasks.base import FinishCode
from modules.providers.utils import download_process_hook
from tests.api.test_base import BaseTestCase
from tests.helpers import get_podcast_data, await_, create_episode


class TestDownloadEpisodeTask(BaseTestCase):
    @staticmethod
    def _source_file(dbs, episode: Episode) -> Path:
        audio: File = await_(File.async_get(dbs, id=episode.audio_id))
        file_path = settings.TMP_AUDIO_PATH / audio.name
        with open(file_path, "wb") as f:
            f.write(b"EpisodeData")
        return file_path

    def test_downloading_ok(
        self,
        episode,
        mocked_youtube,
        mocked_ffmpeg,
        mocked_redis,
        mocked_s3,
        mocked_generate_rss_task,
        dbs,
    ):
        file_path = self._source_file(dbs, episode)
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
        mocked_redis.publish.assert_called_with(settings.REDIS_PROGRESS_PUBSUB_SIGNAL)

        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    def test_downloading__using_cookies__ok(
        self,
        episode,
        mocked_youtube,
        mocked_ffmpeg,
        mocked_s3,
        mocked_generate_rss_task,
        dbs,
        cookie,
    ):
        file_path = self._source_file(dbs, episode)
        await_(episode.update(dbs, cookie_id=cookie.id))
        await_(dbs.commit())

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))
        episode = await_(Episode.async_get(dbs, id=episode.id))

        mocked_youtube.assert_called_with(cookiefile=cookie.as_file())
        mocked_ffmpeg.assert_called_with(src_path=file_path)

        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        assert episode.published_at == episode.created_at

    def test_skip_postprocessing(
        self,
        dbs,
        cookie,
        episode,
        mocked_s3,
        mocked_ffmpeg,
        mocked_youtube,
        mocked_generate_rss_task,
        mocked_source_info_yandex,
    ):
        file_path = self._source_file(dbs, episode)
        await_(episode.update(dbs, cookie_id=cookie.id, source_type=SourceType.YANDEX))
        await_(dbs.commit())

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))

        mocked_ffmpeg.assert_not_called()
        assert result == FinishCode.OK
        assert episode.status == Episode.Status.PUBLISHED
        self.assert_called_with(
            mocked_s3.upload_file,
            src_path=str(file_path),
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )

    def test_file_correct__skip(
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
                "status": EpisodeStatus.PUBLISHED,
                "source_id": mocked_youtube.source_id,
                "watch_url": mocked_youtube.watch_url,
                "podcast_id": podcast_1.id,
            }
        )
        episode = create_episode(dbs, episode_data=episode_data)
        await_(episode.audio.update(dbs, size=1024))

        episode_data["status"] = "new"
        episode_data["podcast_id"] = podcast_2.id
        episode_data["audio_path"] = episode.audio.path
        episode_2 = create_episode(dbs, episode_data=episode_data)
        await_(episode_2.audio.update(dbs, size=1024))

        await_(dbs.commit())

        mocked_s3.get_file_size.return_value = 1024
        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode_2.id))
        await_(dbs.refresh(episode_2))
        mocked_generate_rss_task.run.assert_called_with(podcast_1.id, podcast_2.id)
        assert result == FinishCode.SKIP
        assert not mocked_youtube.download.called
        assert not mocked_ffmpeg.called
        assert episode_2.status == Episode.Status.PUBLISHED
        assert episode_2.published_at == episode_2.created_at

    def test_file_bad_size__ignore(
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
                "status": EpisodeStatus.PUBLISHED,
                "source_id": mocked_youtube.source_id,
                "watch_url": mocked_youtube.watch_url,
            }
        )
        episode = create_episode(dbs, episode_data=episode_data)
        await_(episode.audio.update(dbs, size=1024))

        file_path = self._source_file(dbs, episode)

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

    def test_downloading_failed__roll_back_changes__ok(
        self, episode, mocked_youtube, mocked_ffmpeg, mocked_s3, mocked_generate_rss_task, dbs
    ):
        self._source_file(dbs, episode)
        mocked_youtube.download.side_effect = DownloadError("Video is not available")

        result = await_(DownloadEpisodeTask(db_session=dbs).run(episode.id))

        episode = await_(Episode.async_get(dbs, id=episode.id))
        mocked_youtube.download.assert_called_with([episode.watch_url])
        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None

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


class TestDownloadEpisodeImageTask(BaseTestCase):
    @patch("modules.podcast.models.Episode.generate_image_name")
    @patch("modules.podcast.tasks.download.get_file_size")
    @patch("modules.podcast.tasks.download.ffmpeg_preparation")
    @patch("modules.podcast.tasks.download.download_content")
    def test_image_ok(
        self,
        mocked_download_content,
        mocked_ffmpeg,
        mocked_file_size,
        mocked_name,
        episode,
        mocked_s3,
        dbs,
    ):
        tmp_path = settings.TMP_IMAGE_PATH / f"{episode.source_id}.jpg"
        mocked_download_content.return_value = tmp_path
        mocked_file_size.return_value = 25

        # we mark image as "public" in order to access before it downloaded
        await_(episode.image.update(dbs, public=True))
        await_(dbs.commit())

        source_image_url = episode.image.source_url
        new_remote_path = f"/remote/path/to/images/episode_{uuid.uuid4().hex}_image.png"
        mocked_s3.upload_file.side_effect = lambda *_, **__: new_remote_path
        mocked_name.return_value = f"episode-image-name-{episode.source_id}.jpg"

        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        assert episode.image_id is not None

        image = await_(File.async_get(dbs, id=episode.image_id))
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

    @patch("modules.podcast.tasks.download.download_content")
    def test_image_not_found__use_default(self, mocked_download_content, episode, dbs):
        mocked_download_content.side_effect = NotFoundError()
        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        assert episode.image.public is False
        assert episode.image.available is False
        assert episode.image_url == settings.DEFAULT_EPISODE_COVER

    @patch("modules.podcast.tasks.download.download_content")
    def test_skip_already_downloaded(self, mocked_download_content, episode, dbs):
        remote_path = os.path.join(
            settings.S3_BUCKET_IMAGES_PATH, "episode_{uuid.uuid4().hex}_image.png"
        )
        await_(episode.image.update(dbs, path=remote_path, available=True))
        result = await_(DownloadEpisodeImageTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))
        assert result == FinishCode.OK
        image: File = await_(File.async_get(dbs, id=episode.image_id))
        assert image.path == remote_path
        assert mocked_download_content.assert_not_awaited

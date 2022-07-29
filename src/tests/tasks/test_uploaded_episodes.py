from modules.auth.models import User
from modules.media.models import File
from modules.podcast.models import Episode, Podcast
from common.enums import EpisodeStatus, SourceType, FileType
from modules.podcast.tasks import UploadedEpisodeTask
from modules.podcast.tasks.base import FinishCode
from tests.api.test_base import BaseTestCase
from tests.helpers import await_, get_episode_data, get_source_id


class TestUploadedEpisodeTask(BaseTestCase):
    @staticmethod
    async def _episode(
        dbs, podcast: Podcast, creator: User, file_size: int = 32, source_id: str = None
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

    def test_run_ok(self, dbs, podcast, user, mocked_s3, mocked_generate_rss_task):
        mocked_s3.get_file_size.return_value = 1024
        source_id = get_source_id(prefix="upl")
        episode = await_(self._episode(dbs, podcast, user, file_size=1024, source_id=source_id))

        tmp_remote = f"/tmp/remote/episode_{episode.source_id}.mp3"
        new_remote = f"audio/episode_{episode.source_id}.mp3"
        mocked_s3.copy_file.return_value = new_remote

        result = await_(UploadedEpisodeTask(db_session=dbs).run(episode.id))
        assert result == FinishCode.OK

        await_(dbs.refresh(episode))
        await_(dbs.refresh(episode.audio))

        assert episode.status == EpisodeStatus.PUBLISHED
        assert episode.published_at == episode.created_at
        assert episode.audio.available is True
        assert episode.audio.path == new_remote

        self.assert_called_with(mocked_s3.copy_file, src_path=tmp_remote)
        mocked_generate_rss_task.run.assert_called_with(episode.podcast_id)

    def test_file_bad_size__error(
        self,
        dbs,
        user,
        podcast,
        mocked_s3,
        mocked_generate_rss_task,
    ):
        mocked_s3.get_file_size.return_value = 32
        episode = await_(self._episode(dbs, podcast, user, file_size=1024))

        result = await_(UploadedEpisodeTask(db_session=dbs).run(episode.id))
        await_(dbs.refresh(episode))

        assert result == FinishCode.ERROR
        assert episode.status == Episode.Status.NEW
        assert episode.published_at is None
        assert not episode.audio.available

        mocked_s3.upload_file.assert_not_called()
        mocked_generate_rss_task.run.assert_not_called()

    def test_move_s3_failed__error(self, dbs, podcast, user, mocked_s3, mocked_generate_rss_task):
        mocked_s3.get_file_size.return_value = 1024
        mocked_s3.copy_file.side_effect = RuntimeError("Oops")
        episode = await_(self._episode(dbs, podcast, user, file_size=1024))

        result = await_(UploadedEpisodeTask(db_session=dbs).run(episode.id))
        assert result == FinishCode.ERROR

        mocked_generate_rss_task.run.assert_not_called()
        episode = await_(Episode.async_get(dbs, id=episode.id))
        assert episode.status == Episode.Status.ERROR
        assert episode.published_at is None
        assert not episode.audio.available

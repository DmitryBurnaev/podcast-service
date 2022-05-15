import os
from datetime import datetime

from common.enums import FileType
from modules.media.models import File
from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast
from modules.podcast.tasks.base import FinishCode
from modules.podcast.utils import get_file_size
from tests.helpers import get_episode_data, get_podcast_data, await_, create_episode


class TestGenerateRSSTask:
    """Checks RSS generation logic"""

    def test_generate__single_podcast__ok(self, user, mocked_s3, dbs):

        podcast_1: Podcast = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        podcast_2: Podcast = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_new = create_episode(dbs, episode_data, status=Episode.Status.NEW)

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_downloading = create_episode(dbs, episode_data, status=Episode.Status.DOWNLOADING)

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["published_at"] = datetime.now()
        episode_published = create_episode(dbs, episode_data, status=Episode.Status.PUBLISHED)

        episode_data = get_episode_data(podcast_2, creator=user)
        episode_podcast_2 = create_episode(dbs, episode_data, status=Episode.Status.PUBLISHED)

        await_(dbs.commit())

        expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast_1.publish_id}.xml"
        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast_1.id))
        assert result_code == FinishCode.OK

        assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"
        with open(expected_file_path) as file:
            generated_rss_content = file.read()

        assert episode_published.title in generated_rss_content
        assert episode_published.description in generated_rss_content
        audio: File = await_(File.async_get(dbs, id=episode_published.audio_id))
        assert audio.url in generated_rss_content

        for episode in [episode_new, episode_downloading, episode_podcast_2]:
            audio: File = await_(File.async_get(dbs, id=episode.audio_id))
            assert audio.url not in generated_rss_content, f"wrong {episode} in RSS {podcast_1}"

        podcast_1 = await_(Podcast.async_get(dbs, id=podcast_1.id))
        assert podcast_1.rss_id is not None
        rss: File = await_(File.async_get(dbs, id=podcast_1.rss_id))
        assert rss.available is True
        assert rss.type == FileType.RSS
        assert rss.path == str(expected_file_path)
        assert rss.size == get_file_size(expected_file_path)

    def test_regenerate__replace_rss(self, podcast, mocked_s3, dbs):
        old_rss_id = podcast.rss_id
        expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast.id))
        assert result_code == FinishCode.OK

        await_(dbs.refresh(podcast))
        assert podcast.rss_id == old_rss_id

        rss: File = await_(File.async_get(dbs, id=podcast.rss_id))
        assert rss.available is True
        assert rss.type == FileType.RSS
        assert rss.path == str(expected_file_path)
        assert rss.size == get_file_size(expected_file_path)

    def test_generate__several_podcasts__ok(self, user, mocked_s3, dbs):
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        await_(dbs.commit())

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast_1.id, podcast_2.id))
        assert result_code == FinishCode.OK

        for podcast in [podcast_1, podcast_2]:
            expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
            assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"

    def test_generate__upload_failed__fail(self, podcast, mocked_s3, dbs):
        old_path = "/remote/old_path.rss"
        mocked_s3.upload_file.side_effect = lambda *_, **__: ""
        await_(
            File.async_update(
                dbs, filter_kwargs={"id": podcast.rss_id}, update_data={"path": old_path}
            )
        )

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast.id))
        assert result_code == FinishCode.ERROR

        podcast_1 = await_(Podcast.async_get(dbs, id=podcast.id))
        assert podcast_1.rss_id is not None
        rss: File = await_(File.async_get(dbs, id=podcast.rss_id))
        assert rss.path == old_path

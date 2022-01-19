import os
from datetime import datetime

from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast
from modules.podcast.tasks.base import FinishCode
from tests.helpers import get_episode_data, get_podcast_data, await_


class TestGenerateRSSTask:
    """Checks RSS generation logic"""

    def test_generate__single_podcast__ok(self, user, mocked_s3, dbs):

        podcast_1: Podcast = await_(Podcast.async_create(dbs, **get_podcast_data()))
        podcast_2: Podcast = await_(Podcast.async_create(dbs, **get_podcast_data()))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.NEW
        episode_new = await_(Episode.async_create(dbs, **episode_data))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.DOWNLOADING
        episode_downloading = await_(Episode.async_create(dbs, **episode_data))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["published_at"] = datetime.now()
        episode_published = await_(Episode.async_create(dbs, **episode_data))

        episode_data = get_episode_data(podcast_2, creator=user)
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_podcast_2 = await_(Episode.async_create(dbs, **episode_data))
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
        assert episode_published.file_name in generated_rss_content

        for episode in [episode_new, episode_downloading, episode_podcast_2]:
            assert episode.source_id not in generated_rss_content, f"{episode} in RSS {podcast_1}"

        podcast_1 = await_(Podcast.async_get(dbs, id=podcast_1.id))
        assert podcast_1.rss_link == str(expected_file_path)

    def test_generate__several_podcasts__ok(self, user, mocked_s3, dbs):
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data()))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data()))
        await_(dbs.commit())

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast_1.id, podcast_2.id))
        assert result_code == FinishCode.OK

        for podcast in [podcast_1, podcast_2]:
            expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
            assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"

    def test_generate__upload_failed__fail(self, podcast, mocked_s3, dbs):
        mocked_s3.upload_file.side_effect = lambda *_, **__: ""

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await_(generate_rss_task.run(podcast.id))
        assert result_code == FinishCode.ERROR

        podcast_1 = await_(Podcast.async_get(dbs, id=podcast.id))
        assert podcast_1.rss_link is None

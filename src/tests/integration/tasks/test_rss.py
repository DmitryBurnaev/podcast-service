import os
from datetime import datetime

from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast
from tests.integration.api.test_base import BaseTestCase
from tests.integration.helpers import get_episode_data, get_podcast_data


class TestGenerateRSSTask(BaseTestCase):

    def test_generate__single_podcast__ok(self, user, mocked_s3):

        podcast_1: Podcast = self.async_run(Podcast.create(**get_podcast_data()))
        podcast_2: Podcast = self.async_run(Podcast.create(**get_podcast_data()))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.NEW
        episode_new = self.async_run(Episode.create(**episode_data))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.DOWNLOADING
        episode_downloading = self.async_run(Episode.create(**episode_data))

        episode_data = get_episode_data(podcast_1, creator=user)
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["published_at"] = datetime.now()
        episode_published = self.async_run(Episode.create(**episode_data))

        episode_data = get_episode_data(podcast_2, creator=user)
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_podcast_2 = self.async_run(Episode.create(**episode_data))

        expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast_1.publish_id}.xml"
        generate_rss_task = tasks.GenerateRSSTask()
        self.async_run(generate_rss_task.run(podcast_1.id))

        assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"
        with open(expected_file_path) as file:
            generated_rss_content = file.read()

        assert episode_published.title in generated_rss_content
        assert episode_published.description in generated_rss_content
        assert episode_published.file_name in generated_rss_content

        for episode in [episode_new, episode_downloading, episode_podcast_2]:
            assert episode.source_id not in generated_rss_content, f"{episode} in RSS {podcast_1}"

        podcast_1 = self.async_run(Podcast.async_get(id=podcast_1.id))
        assert podcast_1.rss_link == str(expected_file_path)

    def test_generate__several_podcasts__ok(self, user, mocked_s3):
        podcast_1 = self.async_run(Podcast.create(**get_podcast_data()))
        podcast_2 = self.async_run(Podcast.create(**get_podcast_data()))

        generate_rss_task = tasks.GenerateRSSTask()
        self.async_run(generate_rss_task.run(podcast_1.id, podcast_2.id))

        for podcast in [podcast_1, podcast_2]:
            expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
            assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"

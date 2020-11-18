from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Podcast, Episode
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import get_podcast_data, get_episode_data


class TestEpisodeCreator(BaseTestAPIView):

    def test_create__ok(self, podcast, user, mocked_youtube):
        source_id = mocked_youtube.video_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_creator = EpisodeCreator(
            podcast_id=podcast.id,
            youtube_link=watch_url,
            user_id=user.id,
        )
        episode = self.async_run(episode_creator.create())
        assert episode is not None
        assert episode.watch_url == watch_url
        assert episode.source_id == source_id

    def test_create__same_episode_in_podcast__ok(self, podcast, user, mocked_youtube):
        source_id = mocked_youtube.video_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_data = get_episode_data()
        episode_data["podcast_id"] = podcast.id
        episode_data["source_id"] = source_id
        episode_data["watch_url"] = watch_url

        episode = self.async_run(Episode.create(**episode_data))
        episode_creator = EpisodeCreator(
            podcast_id=podcast.id,
            youtube_link=watch_url,
            user_id=user.id,
        )
        new_episode = self.async_run(episode_creator.create())
        assert episode is not None
        assert new_episode.id == episode.id
        assert new_episode.source_id == source_id
        assert new_episode.watch_url == watch_url

    def test_create__same_episode_in_other_podcast__ok(self, podcast, user, mocked_youtube):
        source_id = mocked_youtube.video_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_data = get_episode_data()
        episode_data["source_id"] = source_id
        episode_data["watch_url"] = watch_url

        episode = self.async_run(Episode.create(**episode_data))

        new_podcast = self.async_run(Podcast.create(**get_podcast_data()))
        episode_creator = EpisodeCreator(
            podcast_id=new_podcast.id,
            youtube_link=episode.watch_url,
            user_id=user.id,
        )
        new_episode = self.async_run(episode_creator.create())
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.watch_url == episode.watch_url
        assert new_episode.source_id == episode.source_id

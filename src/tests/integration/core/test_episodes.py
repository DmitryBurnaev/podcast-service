from modules.podcast.episodes import EpisodeCreator
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import video_id


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

from core import settings
from modules.podcast.utils import episode_process_hook, EpisodeStatuses


class TestEpisodeProcessHooks:

    def test_call_hook__ok(self, mocked_redis):
        mocked_redis.get.return_value = {"total_bytes": 1024}
        episode_process_hook(
            EpisodeStatuses.episode_downloading,
            "test-episode.mp3",
            total_bytes=1024,
            processed_bytes=124,
        )
        mocked_redis.set.assert_called_with(
            "test-episode",
            {
                "event_key": "test-episode",
                "status": EpisodeStatuses.episode_downloading,
                "processed_bytes": 124,
                "total_bytes": 1024,
            },
            ttl=settings.DOWNLOAD_EVENT_REDIS_TTL
        )

    def test_call_hook__with_chunks__ok(self, mocked_redis):
        mocked_redis.get.return_value = {
            "total_bytes": 1024,
            "processed_bytes": 200
        }

        episode_process_hook(
            EpisodeStatuses.episode_downloading,
            "test-episode.mp3",
            chunk=100
        )
        mocked_redis.set.assert_called_with(
            "test-episode",
            {
                "event_key": "test-episode",
                "status": EpisodeStatuses.episode_downloading,
                "processed_bytes": 200 + 100,
                "total_bytes": 1024,
            },
            ttl=settings.DOWNLOAD_EVENT_REDIS_TTL
        )

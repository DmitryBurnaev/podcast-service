from core import settings
from modules.podcast.utils import episode_process_hook
from common.enums import EpisodeStatus


class TestEpisodeProcessHooks:

    def test_call__get_task_context(self):
        assert False

    def test_call_hook__ok(self, mocked_redis):
        # TODO: return with side-effect method for getting job_id / hook-data
        mocked_redis.get.return_value = {"total_bytes": 1024}
        episode_process_hook(
            EpisodeStatus.DL_EPISODE_DOWNLOADING,
            "test-episode.mp3",
            total_bytes=1024,
            processed_bytes=124,
        )
        mocked_redis.set.assert_called_with(
            "test-episode",
            {
                "event_key": "test-episode",
                "status": str(EpisodeStatus.DL_EPISODE_DOWNLOADING),
                "processed_bytes": 124,
                "total_bytes": 1024,
            },
            ttl=settings.DOWNLOAD_EVENT_REDIS_TTL,
        )
        mocked_redis.publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH, message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        )

    def test_call_hook__with_chunks__ok(self, mocked_redis):
        mocked_redis.get.return_value = {"total_bytes": 1024, "processed_bytes": 200}

        episode_process_hook(EpisodeStatus.DL_EPISODE_DOWNLOADING, "test-episode.mp3", chunk=100)
        mocked_redis.set.assert_called_with(
            "test-episode",
            {
                "event_key": "test-episode",
                "status": str(EpisodeStatus.DL_EPISODE_DOWNLOADING),
                "processed_bytes": 200 + 100,
                "total_bytes": 1024,
            },
            ttl=settings.DOWNLOAD_EVENT_REDIS_TTL,
        )
        mocked_redis.publish.assert_called_with(
            channel=settings.REDIS_PROGRESS_PUBSUB_CH, message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        )

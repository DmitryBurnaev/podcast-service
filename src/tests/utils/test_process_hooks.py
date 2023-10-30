from unittest.mock import patch, Mock

import pytest

from core import settings
from modules.podcast.utils import episode_process_hook, TaskContext
from common.enums import EpisodeStatus
from tests.mocks import MockRedisClient


def _get_redis_call_value(expected_key: str, expected_value: str | dict):
    def inner(key):
        if key == expected_key:
            return expected_value
        return None

    return inner


class TestEpisodeProcessHooks:
    def test_call__get_task_context(self, mocked_redis: MockRedisClient):
        test_file_name = "test_episode.mp3"
        mocked_redis.get.side_effect = _get_redis_call_value(
            expected_key=f"jobid_for_file__{test_file_name}",
            expected_value=f"test_job_id_for_file__{test_file_name}",
        )
        context = TaskContext.create_from_redis(test_file_name)
        assert context.job_id == f"test_job_id_for_file__{test_file_name}"

    @patch("rq.job.Job.fetch")
    @pytest.mark.parametrize("canceled", (True, False))
    def test_call__get_task_canceled(
        self,
        mocked_job_fetch: Mock,
        mocked_redis: MockRedisClient,
        canceled: bool,
    ):
        class MockJob:
            id = None
            get_status = Mock(return_value=("canceled" if canceled else "in_progress"))

        job = MockJob()
        mocked_job_fetch.return_value = job
        context = TaskContext(
            f"jobid_for_file__test_episode.mp3",
        )
        assert context.task_canceled() is canceled
        job.get_status.assert_called()

    def test_call_hook__ok(self, mocked_redis: MockRedisClient):
        mocked_redis.get.side_effect = _get_redis_call_value(
            expected_key="test-episode", expected_value={"total_bytes": 1024}
        )
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

    def test_call_hook__with_chunks__ok(self, mocked_redis: MockRedisClient):
        mocked_redis.get.side_effect = _get_redis_call_value(
            expected_key="test-episode",
            expected_value={"total_bytes": 1024, "processed_bytes": 200},
        )
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

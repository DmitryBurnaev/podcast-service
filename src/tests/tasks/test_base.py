import logging
import multiprocessing
from unittest.mock import patch, MagicMock

import pytest

from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import TaskState

pytestmark = pytest.mark.asyncio
test_logger = logging.getLogger(__name__)


class TaskForTest(RQTask):
    def __call__(self, *args, **kwargs) -> TaskState:
        """Base __call__ closes event loop (tests needed for running one)"""
        task_state_queue = multiprocessing.Queue()
        finish_code = self._perform_and_run(task_state_queue, *args, **kwargs)
        return finish_code

    async def run(self, raise_error=False):
        if raise_error:
            raise RuntimeError("Oops")

        return TaskState.FINISHED


class TestRunTask:
    @patch("multiprocessing.get_logger")
    def test_run__ok(self, mocked_logger):
        mocked_logger.return_value = test_logger
        task = TaskForTest()
        assert task() == TaskState.FINISHED

    @patch("multiprocessing.get_logger")
    def test_run__fail(self, mocked_logger):
        mocked_logger.return_value = test_logger
        task = TaskForTest()
        assert task(raise_error=True) == TaskState.ERROR

    async def test_tasks__eq__ok(self):
        task_1 = TaskForTest()
        task_2 = TaskForTest()
        assert task_1 == task_2

    async def test_check_name__ok(self):
        task = TaskForTest()
        assert task.name == "TaskForTest"

    async def test_subclass__ok(self):
        task_classes = list(RQTask.get_subclasses())
        assert TaskForTest in task_classes


class MockJob:
    def __int__(self, *_, **__):
        self.cancel = MagicMock()


@patch("rq.job.Job.cancel")
@patch("rq.job.Job.fetch")
def test_cancel_task(mocked_job_fetch, mocked_job_cancel):
    mocked_job_fetch.return_value = MockJob()
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)

    TaskForTest.cancel_task(1, 2, kwarg=123)

    mocked_job_fetch.assert_called_with(job_id)
    mocked_job_cancel.asseert_called_once()


def test_get_job_id():
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)
    assert job_id == "taskfortest_1_2_kwarg=123_"

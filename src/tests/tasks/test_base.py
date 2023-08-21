import logging
import multiprocessing
import time
import uuid
from unittest.mock import patch, MagicMock

import pytest
from redis.client import Redis

from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import TaskState, StateData, TaskInProgressAction

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


class TaskForSubprocessCallTesting(RQTask):
    def __init__(self, *args, **kwargs):
        self.started = False
        super().__init__(*args, **kwargs)

    async def run(self, raise_error: bool = False, wait_for_cancel: bool = False):
        if raise_error:
            raise RuntimeError("Oops")

        self.started = True
        self._set_queue_action(
            TaskInProgressAction.CHECKING, state_data={"local_filename": "test-file.mp3"}
        )

        if wait_for_cancel:
            while self.started:
                time.sleep(1)

        return TaskState.FINISHED

    def teardown(self, state_data: StateData):
        self.started = False


class MockJob:
    def __init__(self, *_, **__):
        self.cancel = MagicMock()
        self.id = uuid.uuid4().hex
        self.key = TaskForSubprocessCallTesting.get_job_id()
        self.get_status = MagicMock()


@patch("multiprocessing.get_logger", lambda: test_logger)
class TestRunTask:
    def test_run__ok(self):
        task = TaskForTest()
        assert task() == TaskState.FINISHED

    def test_run__fail(self):
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

    @patch("rq.job.Job.fetch")
    async def test_run_with_subprocess__ok(self, mocked_job_fetch):
        mocked_job_fetch.return_value = MockJob()
        task = TaskForSubprocessCallTesting()
        assert task() == TaskState.FINISHED

    @patch("rq.job.Job.fetch")
    async def test_run_with_subprocess__fail(self, mocked_job_fetch):
        mocked_job_fetch.return_value = MockJob()
        task = TaskForSubprocessCallTesting()
        assert task(raise_error=True) == TaskState.ERROR

    @patch("rq.job.Job.fetch")
    async def test_run_with_subprocess__cancel(self, mocked_job_fetch):
        # TODO: fix subprocess call's test
        ...
        # mocked_job_fetch.return_value = MockJob()
        # task = TaskForSubprocessCallTesting()
        # task(wait_for_cancel=True)
        # assert task(raise_error=True) == TaskState.ERROR


@patch("rq.job.Job.cancel")
@patch("rq.job.Job.fetch")
def test_cancel_task(mocked_job_fetch, mocked_job_cancel):
    mocked_job_fetch.return_value = MockJob()
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)

    TaskForTest.cancel_task(1, 2, kwarg=123)

    mocked_job_fetch.assert_called_with(job_id, connection=Redis())
    mocked_job_cancel.asseert_called_once()


def test_get_job_id():
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)
    assert job_id == "taskfortest_1_2_kwarg=123_"

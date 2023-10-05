import logging
import time
import uuid
from unittest.mock import patch, MagicMock

import pytest

from common.redis import RedisClient
from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import TaskResultCode

pytestmark = pytest.mark.asyncio
test_logger = logging.getLogger(__name__)


class TaskForTest(RQTask):
    async def run(self, raise_error=False):
        if raise_error:
            raise RuntimeError("Oops")

        return TaskResultCode.SUCCESS


class TaskForSubprocessCallTesting(RQTask):
    def __init__(self, *args, **kwargs):
        self.started = False
        super().__init__(*args, **kwargs)

    async def run(self, raise_error: bool = False, wait_for_cancel: bool = False):
        if raise_error:
            raise RuntimeError("Oops")

        self.started = True

        if wait_for_cancel:
            while self.started:
                time.sleep(1)

        return TaskResultCode.SUCCESS


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
        assert task() == TaskResultCode.SUCCESS

    def test_run__fail(self):
        task = TaskForTest()
        assert task(raise_error=True) == TaskResultCode.ERROR

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


@patch("rq.job.Job.cancel")
@patch("rq.job.Job.fetch")
def test_cancel_task(mocked_job_fetch, mocked_job_cancel):
    mocked_job_fetch.return_value = MockJob()
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)

    TaskForTest.cancel_task(1, 2, kwarg=123)

    mocked_job_fetch.assert_called_with(job_id, connection=RedisClient().sync_redis)
    mocked_job_cancel.asseert_called_once()


def test_get_job_id():
    job_id = TaskForTest.get_job_id(1, 2, kwarg=123)
    assert job_id == "taskfortest_1_2_kwarg=123_"

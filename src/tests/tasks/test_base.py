import multiprocessing

import pytest

from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import TaskState

pytestmark = pytest.mark.asyncio


class TaskForTest(RQTask):
    async def __call__(self, *args, **kwargs) -> TaskState:
        """Base __call__ closes event loop (tests needed for running one)"""
        task_state_queue = multiprocessing.Queue()
        finish_code = await self._perform_and_run(task_state_queue, *args, **kwargs)
        return finish_code

    async def run(self, raise_error=False):
        if raise_error:
            raise RuntimeError("Oops")

        return TaskState.FINISHED


class TestRunTask:
    async def test_run__ok(self):
        task = TaskForTest()
        assert await task() == TaskState.FINISHED

    async def test_run__fail(self):
        task = TaskForTest()
        assert await task(raise_error=True) == TaskState.ERROR

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


def test_cancel_task():
    assert False


def test_get_job_id():
    assert False

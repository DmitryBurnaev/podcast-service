import asyncio

from modules.podcast.tasks import RQTask
from modules.podcast.tasks.base import FinishCode
from tests.api.test_base import BaseTestCase


class TaskForTest(RQTask):

    def __call__(self, *args, **kwargs) -> FinishCode:
        """ Base __call__ closes event loop (tests needed for running one) """
        loop = asyncio.get_event_loop()
        finish_code = loop.run_until_complete(self._perform_and_run(*args, **kwargs))
        return finish_code

    async def run(self, raise_error=False):
        if raise_error:
            raise RuntimeError("Oops")

        return FinishCode.OK


class TestRunTask(BaseTestCase):

    def test_run__ok(self):
        task = TaskForTest()
        assert task() == FinishCode.OK

    def test_run__fail(self):
        task = TaskForTest()
        assert task(raise_error=True) == FinishCode.ERROR

    def test_tasks__eq__ok(self):
        task_1 = TaskForTest()
        task_2 = TaskForTest()
        assert task_1 == task_2

    def test_check_name__ok(self):
        task = TaskForTest()
        assert task.name == "TaskForTest"

    def test_subclass__ok(self):
        task_classes = list(RQTask.get_subclasses())
        assert TaskForTest in task_classes

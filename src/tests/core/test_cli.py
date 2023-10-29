from typing import NamedTuple, Type

import pytest

from cli import run_task
from modules.podcast.tasks import RQTask, GenerateRSSTask, DownloadEpisodeTask
from tests.mocks import MockArgumentParser, MockRQQueue


class RunTaskParams(NamedTuple):
    task_name: str
    task_args: list[str]


class TestCLIRunTask:
    @pytest.mark.parametrize(
        "task_name, task_args, task_class",
        [
            ["GenerateRSSTask", ["1", "2"], GenerateRSSTask],
            ["DownloadEpisodeTask", ["123"], DownloadEpisodeTask],
        ],
    )
    def test_run_task__ok(
        self,
        mocked_arg_parser: MockArgumentParser,
        mocked_rq_queue: MockRQQueue,
        task_name: str,
        task_args: list[str],
        task_class: Type[RQTask],
    ):
        mocked_arg_parser.parse_args.return_value = RunTaskParams(task_name, task_args)
        run_task.main()
        mocked_rq_queue.enqueue.assert_called_with(task_class(), *task_args)

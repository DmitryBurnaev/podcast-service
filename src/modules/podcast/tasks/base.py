import dataclasses
import enum
import asyncio
import logging
import multiprocessing
import queue
import time
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

from redis.client import Redis
from rq.job import Job
from sqlalchemy.ext.asyncio import AsyncSession

from common.db_utils import make_session_maker
from core import settings

logger = logging.getLogger(__name__)
# multiprocessing.
multiprocessing.log_to_stderr(level=logging.INFO)
# logger = multiprocessing.Manager
# TODO: implement logging for multiprocessing mode.


class TaskState(enum.StrEnum):
    PENDING = "PENDING"
    FINISHED = "FINISHED"
    SKIP = "SKIP"
    ERROR = "ERROR"
    IN_PROGRESS = "IN_PROGRESS"


class TaskInProgressAction(enum.StrEnum):
    CHECKING = "CHECKING"
    DOWNLOADING = "DOWNLOADING"
    POST_PROCESSING = "POST_PROCESSING"
    UPLOADING = "UPLOADING"


@dataclasses.dataclass
class StateData:
    action: TaskInProgressAction
    # TODO: may be we have to use dict here?
    local_filename: str | Path = None
    error_details: str | None = None


class TaskStateInfo(NamedTuple):
    state: TaskState | None = None
    state_data: StateData | None = None


class RQTask:
    """Base class for RQ tasks implementation."""

    db_session: AsyncSession
    task_state_queue: multiprocessing.Queue

    def __init__(self, db_session: AsyncSession = None):
        self.db_session = db_session
        self.logger = multiprocessing.log_to_stderr(level=settings.LOG_LEVEL)

    async def run(self, *args, **kwargs):
        """We need to override this method to implement main task logic"""
        raise NotImplementedError

    def __call__(self, *args, **kwargs) -> TaskState:
        logger.info("==== STARTED task %s ====", self.name)
        finish_code = self._run_with_subprocess(*args, **kwargs)
        logger.info("==== FINISHED task %s | code %s ====", self.name, finish_code)
        return finish_code

    def __eq__(self, other):
        """Can be used for test's simplify"""
        return isinstance(other, self.__class__) and self.__class__ == other.__class__

    def _run_with_subprocess(self, *task_args, **task_kwargs) -> TaskState:
        """ Run logic in subprocess allows to terminate run task in the background"""

        def extract_state_info(source_queue: multiprocessing.Queue) -> TaskStateInfo | None:
            with suppress(queue.Empty):
                return source_queue.get(block=False)

        def task_in_progress(state_info: TaskStateInfo | None):
            if not state_info:
                return True

            return state_info.state not in (TaskState.FINISHED, TaskState.ERROR)

        task_state_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=self._perform_and_run,
            args=(task_state_queue, *task_args),
            kwargs=task_kwargs,
        )
        process.start()

        job = Job.fetch(self.get_job_id(*task_args, **task_kwargs), connection=Redis())

        if not (state_info := extract_state_info(task_state_queue)):
            state_info = TaskStateInfo(state=TaskState.PENDING)

        while task_in_progress(state_info):
            if new_state_info := extract_state_info(task_state_queue):
                state_info = new_state_info

            job_status = job.get_status()
            logger.debug("jobid: %s | job_status: %s | state_info: %s", job.id, job_status, state_info)
            if job_status == "canceled":  # status can be changed by RQTask.cancel_task()
                if state_info and state_info.state == TaskState.IN_PROGRESS:
                    self.teardown(state_info.state_data)

                process.terminate()
                logger.warning(f"Process '%s' terminated!", process)
                break

            time.sleep(1)

        return state_info.state if state_info else None

        #
        # finish_code = None
        # while finish_code is None:
        #     if result := self.extract_result(task_state_queue):
        #         finish_code = result.state
        #     else:
        #         finish_code = None
        #
        #     status = job.get_status()
        #     logger.debug("jobid: %s | status: %s", job.id, status)
        #     if status == "canceled":  # status can be changed by RQTask.cancel_task()
        #         self.teardown()
        #         process.terminate()
        #         logger.warning(f"Process '%s' terminated!", process)
        #         break
        #
        #     time.sleep(1)

    def _perform_and_run(self, task_state_queue, *args, **kwargs):
        """
        Runs async code, implemented in `self.run` and stores result to the queue
        (for retrieving results above)
        """
        print("_perform_and_run")
        self.task_state_queue = task_state_queue

        async def run_async(*args, **kwargs):
            """Allows calling `self.run` in transaction block with catching any exceptions"""

            session_maker = make_session_maker()
            print("Run async")
            try:
                async with session_maker() as db_session:
                    self.db_session = db_session
                    result = await self.run(*args, **kwargs)
                    await self.db_session.commit()

            except Exception as exc:
                await self.db_session.rollback()
                result = TaskState.ERROR
                logger.exception("Couldn't perform task %s | error %r", self.name, exc)

            return result

        finish_code = asyncio.run(run_async(*args, **kwargs))
        print("queue.put", self.task_state_queue, finish_code)

        self.task_state_queue.put(TaskStateInfo(state=TaskState.FINISHED, state_data=finish_code))

    @property
    def name(self):
        return self.__class__.__name__

    @classmethod
    def get_subclasses(cls):
        for subclass in cls.__subclasses__():
            yield from subclass.get_subclasses()
            yield subclass

    @classmethod
    def get_job_id(cls, *task_args, **task_kwargs) -> str:
        kw_pairs = [f"{key}={value}" for key, value in task_kwargs.items()]
        return f"{cls.__name__.lower()}_{'_'.join(map(str, task_args))}_{'_'.join(kw_pairs)}_"

    @classmethod
    def cancel_task(cls, *task_args, **task_kwargs) -> None:
        job_id = cls.get_job_id(*task_args, **task_kwargs)
        logger.debug("Trying to cancel task %s", job_id)
        try:
            job = Job.fetch(job_id, connection=Redis())
            job.cancel()
        except Exception as exc:
            logger.exception("Couldn't cancel task %s: %r", job_id, exc)
        else:
            logger.info("Canceled task %s", job_id)

    def teardown(self, state_data: StateData):
        logger.debug("Teardown for %s | state_data: %s", self.__class__.__name__, state_data)

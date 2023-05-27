import dataclasses
import enum
import asyncio
import logging
import multiprocessing
import queue
import time
from typing import Any, NamedTuple

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


class CurrentState(enum.StrEnum):
    OK = "OK"
    SKIP = "SKIP"
    ERROR = "ERROR"
    IN_PROGRESS = "IN_PROGRESS"


@dataclasses.dataclass
class StateData:
    tmp_filename: str = None


class MultiprocessResult(NamedTuple):
    current_state: CurrentState | None = None
    state_data: StateData | None = None


class RQTask:
    """Base class for RQ tasks implementation."""

    db_session: AsyncSession

    def __init__(self, db_session: AsyncSession = None):
        self.db_session = db_session
        self.logger = multiprocessing.log_to_stderr(level=settings.LOG_LEVEL)

    async def run(self, *args, **kwargs):
        """We need to override this method to implement main task logic"""
        raise NotImplementedError

    def __call__(self, *args, **kwargs) -> CurrentState:
        logger.info("==== STARTED task %s ====", self.name)
        finish_code = self._run_with_subprocess(*args, **kwargs)
        logger.info("==== FINISHED task %s | code %s ====", self.name, finish_code)
        return finish_code

    def __eq__(self, other):
        """Can be used for test's simplify"""
        return isinstance(other, self.__class__) and self.__class__ == other.__class__

    def _run_with_subprocess(self, *task_args, **task_kwargs) -> CurrentState:
        """ Run logic in subprocess allows to terminate run task in the background"""

        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=self._perform_and_run,
            args=(result_queue, *task_args),
            kwargs=task_kwargs,
        )
        process.start()

        job = Job.fetch(self.get_job_id(**task_kwargs), connection=Redis())
        finish_code = None
        while finish_code is None:
            if result := self.extract_result(result_queue):
                finish_code = result.current_state
            else:
                finish_code = None

            status = job.get_status()
            logger.debug("jobid: %s | status: %s", job.id, status)
            if status == "canceled":  # status can be changed by RQTask.cancel_task()
                self.teardown()
                process.terminate()
                logger.warning(f"Process '%s' terminated!", process)
                break

            time.sleep(1)

        return finish_code

    def _perform_and_run(self, queue, *args, **kwargs):
        """
        Runs async code, implemented in `self.run` and stores result to the queue
        (for retrieving results above)
        """
        print("_perform_and_run")
        self.queue = queue

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
                result = CurrentState.ERROR
                logger.exception("Couldn't perform task %s | error %r", self.name, exc)

            return result

        finish_code = asyncio.run(run_async(*args, **kwargs))
        print("queue.put", self.queue, finish_code)
        self.queue.put(finish_code)

    @property
    def name(self):
        return self.__class__.__name__

    @classmethod
    def get_subclasses(cls):
        for subclass in cls.__subclasses__():
            yield from subclass.get_subclasses()
            yield subclass

    @classmethod
    def get_job_id(cls, **task_kwargs) -> str:
        kw_pairs = [f"{key}={value}" for key, value in task_kwargs.items()]
        return f"{cls.__name__.lower()}_{'_'.join(kw_pairs)}"

    @classmethod
    def cancel_task(cls, **task_kwargs) -> None:
        job_id = cls.get_job_id(**task_kwargs)
        logger.debug("Trying to cancel task %s", job_id)
        try:
            job = Job.fetch(job_id, connection=Redis())
            job.cancel()
        except Exception as exc:
            logger.exception("Couldn't cancel task %s: %r", job_id, exc)
        else:
            logger.info("Canceled task %s", job_id)

    def teardown(self):
        pass

    @staticmethod
    def extract_result(result_queue: multiprocessing.Queue, block: bool = False) -> MultiprocessResult | None:
        try:
            return result_queue.get(block=block)
        except queue.Empty:
            return None

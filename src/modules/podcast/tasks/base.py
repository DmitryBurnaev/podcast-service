import enum
import asyncio
import logging

from rq.job import Job
from sqlalchemy.ext.asyncio import AsyncSession

from common.db_utils import make_session_maker
from common.redis import RedisClient
from modules.podcast.utils import TaskContext

logger = logging.getLogger(__name__)


class TaskResultCode(enum.StrEnum):
    SUCCESS = "SUCCESS"
    SKIP = "SKIP"
    ERROR = "ERROR"
    CANCEL = "CANCEL"


class RQTask:
    """Base class for RQ tasks implementation."""

    db_session: AsyncSession
    # task_state_queue: multiprocessing.Queue
    task_context: TaskContext

    def __init__(self, db_session: AsyncSession = None):
        self.db_session = db_session
        self.logger = logger

    async def run(self, *args, **kwargs):
        """We need to override this method to implement main task logic"""
        raise NotImplementedError

    def __call__(self, *args, **kwargs) -> TaskResultCode:
        logger.info("==== STARTED task %s ====", self.name)
        finish_code = asyncio.run(self._perform_and_run(*args, **kwargs))
        logger.info("==== SUCCESS task %s | code %s ====", self.name, finish_code)
        return finish_code

    def __eq__(self, other):
        """Can be used for test's simplify"""
        return isinstance(other, self.__class__) and self.__class__ == other.__class__

    # def _run_with_subprocess(self, *task_args, **task_kwargs) -> TaskResultCode:
    #     """Run logic in subprocess allows to terminate run task in the background"""
    #
    #     def extract_state_info(source_queue: multiprocessing.Queue) -> TaskStateInfo | None:
    #         with suppress(queue.Empty):
    #             return source_queue.get(block=False)
    #
    #     def task_in_progress(state_info: TaskStateInfo | None) -> bool:
    #         if not state_info:
    #             return True
    #
    #         return state_info.state not in (TaskResultCode.SUCCESS, TaskResultCode.ERROR)
    #
    #     task_state_queue = multiprocessing.Queue()
    #     process = multiprocessing.Process(
    #         target=self._perform_and_run,
    #         args=(task_state_queue, *task_args),
    #         kwargs=task_kwargs,
    #     )
    #     process.start()
    #
    #     job = Job.fetch(self.get_job_id(*task_args, **task_kwargs), connection=Redis())
    #
    #     if not (state_info := extract_state_info(task_state_queue)):
    #         state_info = TaskStateInfo(state=TaskResultCode.PENDING)
    #
    #     while task_in_progress(state_info):
    #         if new_state_info := extract_state_info(task_state_queue):
    #             state_info = new_state_info
    #
    #         job_status = job.get_status()
    #         logger.debug(
    #             "jobid: %s | job_status: %s | state_info: %s", job.id, job_status, state_info
    #         )
    #         if job_status == "canceled":  # status can be changed by RQTask.cancel_task()
    #             if state_info and state_info.state == TaskResultCode.IN_PROGRESS:
    #                 self.teardown(state_info.state_data)
    #
    #             process.terminate()
    #             logger.warning("Process '%s' terminated!", process)
    #             break
    #
    #         time.sleep(1)
    #
    #     return state_info.state if state_info else None

    async def _perform_and_run(self, *args, **kwargs) -> TaskResultCode:
        """Allows calling `self.run` in transaction block with catching any exceptions"""

        session_maker = make_session_maker()
        self.task_context = TaskContext(job_id=self.get_job_id(*args, **kwargs))

        try:
            async with session_maker() as db_session:
                self.db_session = db_session
                result = await self.run(*args, **kwargs)
                await self.db_session.commit()

        except Exception as exc:
            await self.db_session.rollback()
            result = TaskResultCode.ERROR
            logger.exception("Couldn't perform task %s | error %r", self.name, exc)

        return result

    # def _perform_and_run(self, *args, **kwargs) -> TaskResultCode:
    #     """
    #     Runs async code, implemented in `self.run` and stores result to the queue
    #     (for retrieving results above)
    #     """
    #     # self.task_state_queue = task_state_queue
    #     # self.logger = log_to_stderr()
    #
    #     async def run_async(*args, **kwargs):
    #         """Allows calling `self.run` in transaction block with catching any exceptions"""
    #
    #         session_maker = make_session_maker()
    #         try:
    #             async with session_maker() as db_session:
    #                 self.db_session = db_session
    #                 result = await self.run(*args, **kwargs)
    #                 await self.db_session.commit()
    #
    #         except Exception as exc:
    #             await self.db_session.rollback()
    #             result = TaskResultCode.ERROR
    #             self.logger.exception("Couldn't perform task %s | error %r", self.name, exc)
    #
    #         return result
    #
    #     return asyncio.run(run_async(*args, **kwargs))
    # result_state = asyncio.run(run_async(*args, **kwargs))
    # self.task_state_queue.put(TaskStateInfo(state=result_state))

    # def _set_queue_action(
    #     self,
    #     action: TaskInProgressAction,
    #     state: TaskResultCode = TaskResultCode.IN_PROGRESS,
    #     state_data: dict[str, str | Path | int] | None = None,
    # ):
    #     state_data = state_data or {}
    #     if hasattr(self, "task_state_queue"):
    #         self.task_state_queue.put(
    #             TaskStateInfo(state=state, state_data=StateData(action=action, data=state_data))
    #         )
    #     else:
    #         logger.debug("No 'task_state_queue' attribute exist for %s", self.__class__.__name__)

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
        logger.warning("Trying to cancel task %s", job_id)
        try:
            job = Job.fetch(job_id, connection=RedisClient().sync_redis)
            job.cancel()
        except Exception as exc:
            logger.exception("Couldn't cancel task %s: %r", job_id, exc)
        else:
            logger.info("Canceled task %s", job_id)

    # def teardown(self, state_data: StateData) -> None:
    #     """
    #     Preparing some extra actions for cancelling current task
    #     (ex.: killing subprocess, remove tmp files, etc.)
    #     """
    #     logger.warning("Teardown for %s | state_data: %s", self.__class__.__name__, state_data)

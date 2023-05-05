import enum
import asyncio
import logging

from redis.client import Redis
from rq.job import Job
from sqlalchemy.ext.asyncio import AsyncSession

from common.db_utils import make_session_maker


logger = logging.getLogger(__name__)


class FinishCode(int, enum.Enum):
    OK = 0
    SKIP = 1
    ERROR = 2


class RQTask:
    """Base class for RQ tasks implementation."""

    db_session: AsyncSession

    def __init__(self, db_session: AsyncSession = None):
        self.db_session = db_session

    async def run(self, *args, **kwargs):
        """We need to override this method to implement main task logic"""
        raise NotImplementedError

    def __call__(self, *args, **kwargs) -> FinishCode:
        logger.info("==== STARTED task %s ====", self.name)
        finish_code = asyncio.run(self._perform_and_run(*args, **kwargs))
        logger.info("==== FINISHED task %s | code %s ====", self.name, finish_code)
        return finish_code

    def __eq__(self, other):
        """Can be used for test's simplify"""
        return isinstance(other, self.__class__) and self.__class__ == other.__class__

    async def _perform_and_run(self, *args, **kwargs):
        """Allows calling `self.run` in transaction block with catching any exceptions"""

        session_maker = make_session_maker()
        try:
            async with session_maker() as db_session:
                self.db_session = db_session
                result = await self.run(*args, **kwargs)
                await self.db_session.commit()

        except Exception as exc:
            await self.db_session.rollback()
            result = FinishCode.ERROR
            logger.exception("Couldn't perform task %s | error %r", self.name, exc)

        return result

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

import asyncio
import enum

from common.utils import get_logger
from core.database import db

logger = get_logger(__name__)


class FinishCode(int, enum.Enum):
    OK = 0
    SKIP = 1
    ERROR = 2


class RQTask:
    """ Base class for RQ tasks implementation. """

    async def run(self, *args, **kwargs):
        """ We need to override this method to implement main task logic """
        raise NotImplementedError

    def __call__(self, *args, **kwargs) -> FinishCode:
        logger.info(f"==== STARTED task %s ====", self.name)
        finish_code = asyncio.run(self._perform_and_run(*args, **kwargs))
        logger.info(f"==== FINISHED task %s | code %s ====", self.name, finish_code)
        return finish_code

    def __eq__(self, other):
        """ Can be used for test's simplify """
        return isinstance(other, self.__class__) and self.__class__ == other.__class__

    async def _perform_and_run(self, *args, **kwargs):
        await db.set_bind(
            db.config["dsn"],
            echo=db.config["echo"],
            min_size=db.config["min_size"],
            max_size=db.config["max_size"],
            ssl=db.config["ssl"],
            **db.config["kwargs"],
        )
        try:
            async with db.transaction():
                result = await self.run(*args, **kwargs)
        except Exception as err:
            result = FinishCode.ERROR
            logger.exception("Couldn't perform task %s | error %s (%s)", self.name, type(err), err)

        return result

    @property
    def name(self):
        return self.__class__.__name__

    @classmethod
    def get_subclasses(cls):
        for subclass in cls.__subclasses__():
            yield from subclass.get_subclasses()
            yield subclass

import dataclasses
import logging
from functools import lru_cache
from typing import Optional

from rq.job import Job

from common.redis import RedisClient

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TaskContext:
    job_id: str
    canceled: bool = False
    _redis_key_pattern = "jobid_for_file_{}"

    def task_canceled(self) -> bool:
        job = Job.fetch(self.job_id, connection=RedisClient().sync_redis)
        job_status = job.get_status()
        logger.debug("Check for canceling: jobid: %s | status: %s", job.id, job_status)
        return job_status == "canceled"

    def save_to_redis(self, filename: str) -> None:
        key = self._redis_key_pattern.format(filename)
        RedisClient().set(key, self.job_id)

    @classmethod
    @lru_cache  # TODO: do we need caching?
    def create_from_redis(cls, filename: str) -> Optional["TaskContext"]:
        key = cls._redis_key_pattern.format(filename)
        if job_id := RedisClient().get(key):
            return TaskContext(job_id=job_id)

        return None

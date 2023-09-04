import dataclasses
import logging

from rq.job import Job

from common.redis import RedisClient

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TaskContext:
    job_id: str
    canceled: bool = False

    def task_canceled(self) -> bool:
        job = Job.fetch(self.job_id, connection=RedisClient().sync_redis)
        job_status = job.get_status()
        logger.debug("Check for canceling: jobid: %s | status: %s", job.id, job_status)
        return job_status == "canceled"

import sys
import logging
import logging.config

from redis import Redis
from rq import Worker
import sentry_sdk
from sentry_sdk.integrations.rq import RqIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from core import settings


def run_worker():
    """Runs RQ worker for consuming background tasks (like downloading providers tracks)"""

    logging.config.dictConfig(settings.LOGGING)

    if settings.SENTRY_DSN:
        sentry_logging = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(settings.SENTRY_DSN, integrations=[RqIntegration(), sentry_logging])

    queues = sys.argv[1:] or ["default"]
    Worker(queues, connection=Redis(*settings.REDIS_CON)).work()


if __name__ == "__main__":
    run_worker()

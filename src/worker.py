import sys
import logging
import logging.config

from redis import Redis
from rq import Connection, Worker
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.rq import RqIntegration

from core import settings


def run_worker():
    """Allows to run RQ worker for consuming background tasks (like downloading youtube tracks)"""

    logging.config.dictConfig(settings.LOGGING)

    if settings.SENTRY_DSN:
        sentry_logging = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(settings.SENTRY_DSN, integrations=[RqIntegration(), sentry_logging])

    with Connection(Redis(*settings.REDIS_CON)):
        qs = sys.argv[1:] or ["default"]
        Worker(qs).work()


if __name__ == "__main__":
    run_worker()

import logging
import logging.config

import rq
import sentry_sdk
from redis import Redis
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from sentry_sdk.integrations.logging import LoggingIntegration
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from starlette.applications import Starlette
from starlette.middleware import Middleware
from webargs_starlette import WebargsHTTPException

from core import settings
# from core.database import db
from core.routes import routes
from common.utils import custom_exception_handler
from common.exceptions import BaseApplicationError


exception_handlers = {
    BaseApplicationError: custom_exception_handler,
    WebargsHTTPException: custom_exception_handler,
}


class PodcastApp(Starlette):
    """ Simple adaptation of Starlette APP for podcast-service. Small addons here. """

    rq_queue: rq.Queue
    db_engine: AsyncEngine

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rq_queue = rq.Queue(
            name=settings.RQ_QUEUE_NAME,
            connection=Redis(*settings.REDIS_CON),
            default_timeout=settings.RQ_DEFAULT_TIMEOUT,
        )
        self.db_engine = create_async_engine(settings.DATABASE_DSN, echo=True)


def get_app():
    app = PodcastApp(
        routes=routes,
        exception_handlers=exception_handlers,
        debug=settings.APP_DEBUG,
        middleware=[Middleware(SentryAsgiMiddleware)],
    )
    # db.init_app(app)
    logging.config.dictConfig(settings.LOGGING)
    if settings.SENTRY_DSN:
        logging_integration = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(settings.SENTRY_DSN, integrations=[logging_integration])

    return app

import logging
import logging.config

import rq
import sentry_sdk
from redis import Redis
from sqlalchemy.orm import sessionmaker
from starlette.middleware import Middleware
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette_web.common.database import make_session_maker
from webargs_starlette import WebargsHTTPException
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from sentry_sdk.integrations.logging import LoggingIntegration

from core import settings
from core.routes import routes
# from common.db_utils import make_session_maker
# from common.utils import custom_exception_handler
from common.exceptions import BaseApplicationError

exception_handlers = {
    BaseApplicationError: custom_exception_handler,
    WebargsHTTPException: custom_exception_handler,
}


class PodcastApp(Starlette):
    """Simple adaptation of Starlette APP for podcast-service. Small addons are here."""

    rq_queue: rq.Queue
    session_maker: sessionmaker

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rq_queue = rq.Queue(
            name=settings.RQ_QUEUE_NAME,
            connection=Redis(*settings.REDIS_CON),
            default_timeout=settings.RQ_DEFAULT_TIMEOUT,
        )
        self.session_maker = make_session_maker()


def get_app() -> PodcastApp:
    middlewares = [Middleware(SentryAsgiMiddleware)]
    if settings.APP_DEBUG:
        middlewares.append(
            Middleware(
                CORSMiddleware,
                allow_origins="*",
                allow_methods="*",
                allow_headers="*",
                allow_credentials=True,
            ),
        )

    app = PodcastApp(
        routes=routes,
        exception_handlers=exception_handlers,
        debug=settings.APP_DEBUG,
        middleware=middlewares,
    )
    logging.config.dictConfig(settings.LOGGING)
    if settings.SENTRY_DSN:
        logging_integration = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(settings.SENTRY_DSN, integrations=[logging_integration])

    return app

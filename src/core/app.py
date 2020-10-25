import rq
from redis import Redis
from starlette.applications import Starlette
from webargs_starlette import WebargsHTTPException

from core import settings
from core.database import db
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rq_queue = rq.Queue(
            name=settings.RQ_QUEUE_NAME,
            connection=Redis(*settings.REDIS_CON),
            default_timeout=settings.RQ_DEFAULT_TIMEOUT,
        )


def get_app():
    app = PodcastApp(routes=routes, exception_handlers=exception_handlers, debug=settings.APP_DEBUG)
    db.init_app(app)
    return app

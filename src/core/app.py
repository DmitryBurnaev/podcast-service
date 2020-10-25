import logging

from starlette.applications import Starlette
from webargs_starlette import WebargsHTTPException

from core import settings
from core.database import db
from core.routes import routes
from common.utils import custom_exception_handler
from common.exceptions import BaseApplicationError

logger = logging.getLogger(__name__)


exception_handlers = {
    BaseApplicationError: custom_exception_handler,
    WebargsHTTPException: custom_exception_handler,
}


def get_app():
    app = Starlette(routes=routes, exception_handlers=exception_handlers, debug=settings.APP_DEBUG)
    db.init_app(app)
    return app

import logging

from starlette.applications import Starlette

from core import settings
from core.database import db
from core.routes import routes
from common.utils import custom_exception_handler

logger = logging.getLogger(__name__)

exception_handlers = {
    Exception: custom_exception_handler
}


def get_app():
    app = Starlette(routes=routes, exception_handlers=exception_handlers, debug=settings.APP_DEBUG)
    db.init_app(app)
    return app

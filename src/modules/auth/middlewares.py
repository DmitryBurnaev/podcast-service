import logging

from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from modules.auth.models import UserIP

logger = logging.getLogger(__name__)


class RegisterUserIPMiddleware(BaseHTTPMiddleware):
    allowed_routes = (
        "/api/auth/me/",
        "/api/auth/sign-in/",
        "/api/auth/sign-up/",
    )
    ip_header = "X-Real-IP"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        logger.debug(request.url.path)
        if request.url.path in self.allowed_routes:
            await self._register(request)

        return response

    async def _register(self, request: Request):
        user_id = request.user.id
        logger.debug("Requested register IP from: user: %i | headers: %s", user_id, request.headers)
        if not (ip_address := request.headers.get(self.ip_header)):
            logger.warning("Not found ip for user: %i | headers %s", user_id, request.headers)
            return

        ip_data = {"user_id": request.user.id, "ip_address": ip_address}

        try:
            async with request.app.session_maker() as db_session:
                # TODO: use upsert if possible
                if await UserIP.async_get(db_session, **ip_data):
                    logger.debug("Found UserIP record for: %s", ip_data)
                else:
                    await UserIP.async_create(db_session, **ip_data)
                    logger.debug("Created NEW UserIP record for: %s", ip_data)

                await db_session.commit()

        except Exception as err:
            await db_session.rollback()
            logger.exception("Couldn't register new IP: %r", err)

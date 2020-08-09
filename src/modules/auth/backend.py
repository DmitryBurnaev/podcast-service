import logging

from jose import JWTError

from common.exceptions import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    PermissionDeniedError
)
from modules.auth.models import User
from modules.auth.utils import decode_jwt

logger = logging.getLogger(__name__)


class BaseAuthJWTBackend:

    keyword = "Bearer"

    async def authenticate(self, request):
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if not auth_header:
            raise AuthenticationRequiredError("Invalid token header. No credentials provided.")

        auth = auth_header.split()
        if len(auth) != 2:
            logger.warning("Trying to authenticate with header %s", auth_header)
            raise AuthenticationFailedError("Invalid token header. Token should be format as JWT")

        if auth[0] != self.keyword:
            raise AuthenticationFailedError("Invalid token header. Keyword mismatch.")

        return await self._authenticate_user(jwt_token=auth[1])

    async def _authenticate_user(self, jwt_token):
        logger.info("Logging via JWT auth. Got token: %s", jwt_token)
        try:
            jwt_payload = decode_jwt(jwt_token)
        except JWTError as error:
            msg = "Token could not be decoded: %s"
            logger.exception(msg, error)
            raise AuthenticationFailedError(msg % (error,))

        user_id = jwt_payload.get("user_id")
        user = await User.get_active(user_id)
        if not user:
            msg = "Couldn't found active user with id=%s"
            logger.warning(msg, user_id)
            raise AuthenticationFailedError(details=(msg % (user_id,)))

        return user


class LoginRequiredAuthBackend(BaseAuthJWTBackend):
    ...


class AdminRequiredAuthBackend(BaseAuthJWTBackend):

    # @staticmethod
    async def _authenticate_user(self, jwt_token):
        user = await super()._authenticate_user(jwt_token)
        if not user.is_superuser:
            raise PermissionDeniedError("You don't have an admin privileges.")

        return user

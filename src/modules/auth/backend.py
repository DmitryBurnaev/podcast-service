from typing import Tuple

from jwt import InvalidTokenError, ExpiredSignatureError
from starlette.requests import Request

from common.exceptions import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    PermissionDeniedError,
    SignatureExpiredError,
)
from common.utils import get_logger
from common.views import PRequest
from modules.auth.models import User, UserSession
from modules.auth.utils import decode_jwt, TOKEN_TYPE_ACCESS

logger = get_logger(__name__)


class BaseAuthJWTBackend:
    """ Core of authenticate system, based on JWT auth approach """

    keyword = "Bearer"

    async def authenticate(self, request: PRequest):
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if not auth_header:
            raise AuthenticationRequiredError("Invalid token header. No credentials provided.")

        auth = auth_header.split()
        if len(auth) != 2:
            logger.warning("Trying to authenticate with header %s", auth_header)
            raise AuthenticationFailedError("Invalid token header. Token should be format as JWT.")

        if auth[0] != self.keyword:
            raise AuthenticationFailedError("Invalid token header. Keyword mismatch.")

        user, _ = await self.authenticate_user(request, jwt_token=auth[1])
        return user

    async def authenticate_user(
        self, request: PRequest, jwt_token: str, token_type: str = TOKEN_TYPE_ACCESS,
    ) -> Tuple[User, dict]:
        """ Allows to find active user by jwt_token """

        logger.debug("Logging via JWT auth. Got token: %s", jwt_token)
        try:
            jwt_payload = decode_jwt(jwt_token)
        except ExpiredSignatureError:
            logger.debug("JWT signature was expired for token %s", jwt_token)
            raise SignatureExpiredError
        except InvalidTokenError as error:
            msg = "Token could not be decoded: %s"
            logger.exception(msg, error)
            raise AuthenticationFailedError(msg % (error,))

        if jwt_payload["token_type"] != token_type:
            raise AuthenticationFailedError(
                f"Token type '{token_type}' expected, got '{jwt_payload['token_type']}' instead."
            )

        user_id = jwt_payload.get("user_id")
        user = await User.get_active(user_id)
        if not user:
            msg = "Couldn't found active user with id=%s."
            logger.warning(msg, user_id)
            raise AuthenticationFailedError(details=(msg % (user_id,)))

        user_session = await UserSession.async_get(
            request.db_session, user_id=user.id, is_active=True
        )
        if not user_session:
            raise AuthenticationFailedError(f"Couldn't found active session for user #{user_id}.")

        return user, jwt_payload


class LoginRequiredAuthBackend(BaseAuthJWTBackend):
    """ Each request must have filled `user` attribute """


class AdminRequiredAuthBackend(BaseAuthJWTBackend):
    """ Login-ed used must have `is_superuser` attribute """

    async def authenticate_user(self, jwt_token: str, token_type: str = TOKEN_TYPE_ACCESS):
        user, jwt_payload = await super().authenticate_user(jwt_token)
        if not user.is_superuser:
            raise PermissionDeniedError("You don't have an admin privileges.")

        return user, jwt_payload

import logging
from typing import NamedTuple

from jwt import InvalidTokenError, ExpiredSignatureError
from sqlalchemy.ext.asyncio import AsyncSession

from common.exceptions import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    PermissionDeniedError,
    SignatureExpiredError,
)
from common.utils import hash_string, utcnow
from modules.auth.models import User, UserSession, UserAccessToken
from modules.auth.utils import decode_jwt
from modules.auth.constants import LENGTH_USER_ACCESS_TOKEN, AuthTokenType

logger = logging.getLogger(__name__)


class ByTokenData(NamedTuple):
    user_id: int
    session_id: str = ""
    payload: dict | None = None


class BaseAuthBackend:
    """Core of authenticate system, based on JWT auth approach"""

    keyword = "Bearer"

    def __init__(self, request, db_session: AsyncSession | None = None):
        self.request = request
        self.db_session: AsyncSession = db_session or request.db_session

    async def authenticate(self) -> tuple[User, str]:
        request = self.request
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if not auth_header:
            raise AuthenticationRequiredError("Invalid token header. No credentials provided.")

        auth = auth_header.split()
        if len(auth) != 2:
            logger.warning("Trying to authenticate with header %s", auth_header)
            raise AuthenticationFailedError("Invalid token header. Token should be format as JWT.")

        if auth[0] != self.keyword:
            raise AuthenticationFailedError("Invalid token header. Keyword mismatch.")

        user, _, session_id = await self.authenticate_user(jwt_token=auth[1])
        return user, session_id

    async def authenticate_user(
        self,
        jwt_token: str,
        token_type: AuthTokenType = AuthTokenType.ACCESS,
    ) -> tuple[User, dict, str | None]:
        """Allows to find active user by jwt_token"""

        if self._seems_like_user_access_token(jwt_token):
            by_token_data = await self._encode_user_access_token(jwt_token)
            token_type = AuthTokenType.USER_ACCESS
        else:
            by_token_data = self._encode_jwt(jwt_token, token_type)

        user_id = by_token_data.user_id
        user = await User.get_active(self.db_session, user_id)
        if not user:
            msg = "Couldn't found active user with id=%s."
            logger.warning(msg, user_id)
            raise AuthenticationFailedError(details=(msg % (user_id,)))

        if token_type in (AuthTokenType.RESET_PASSWORD, AuthTokenType.USER_ACCESS):
            return user, by_token_data.payload, None

        session_id = by_token_data.session_id
        if not session_id:
            raise AuthenticationFailedError("Incorrect data in JWT: session_id is missed")

        user_session = await UserSession.async_get(
            self.db_session, public_id=session_id, is_active=True
        )
        if not user_session:
            raise AuthenticationFailedError(
                f"Couldn't found active session: {user_id=} | {session_id=}."
            )

        return user, by_token_data.payload, session_id

    @staticmethod
    def _encode_jwt(token: str, token_type: AuthTokenType) -> ByTokenData:
        """
        Encodes given JWT token and extract stored data in a JWT payload

        :param token: JWT token
        :return: ByTokenData instance (stores token-specific info)
        """
        logger.debug("Logging via JWT auth. Got token: %s", token)
        try:
            jwt_payload = decode_jwt(token)
        except ExpiredSignatureError as exc:
            logger.debug("JWT signature has been expired for %s token", token_type)
            exception_class = (
                SignatureExpiredError
                if token_type == AuthTokenType.ACCESS
                else AuthenticationFailedError
            )
            raise exception_class("JWT signature has been expired for token") from exc

        except InvalidTokenError as exc:
            msg = "Token could not be decoded: %s"
            logger.exception(msg, exc)
            raise AuthenticationFailedError(msg % (exc,)) from exc

        expected_token_type = str(token_type).lower()
        if jwt_payload["token_type"].lower() != expected_token_type:
            raise AuthenticationFailedError(
                f"Token type '{expected_token_type}' expected, "
                f"got '{jwt_payload['token_type'].lower()}' instead."
            )

        return ByTokenData(
            user_id=jwt_payload["user_id"],
            payload=jwt_payload,
            session_id=jwt_payload.get("session_id"),
        )

    async def _encode_user_access_token(self, token: str) -> ByTokenData:
        """
        Finds active UserAccessToken instance by provided token

        :param token: access token (will be hashed for finding stored in DB)
        :return: ByTokenData instance (stores token-specific info)
        """
        logger.debug("Logging via UserAccess token. Got token: %s", token)
        user_access_token: UserAccessToken = await UserAccessToken.async_get(
            self.db_session,
            token=hash_string(token),
        )
        if not user_access_token:
            raise AuthenticationFailedError("Provided access token is unknown.")

        logger.debug("UserAccess token has been decoded: %r", user_access_token)
        if not user_access_token.enabled or user_access_token.expires_in < utcnow():
            raise AuthenticationFailedError("Provided access token is disabled or expired.")

        return ByTokenData(user_id=user_access_token.user_id)

    @staticmethod
    def _seems_like_user_access_token(token: str) -> bool:
        return len(token) == LENGTH_USER_ACCESS_TOKEN and len(token.split(".")) == 1


class LoginRequiredAuthBackend(BaseAuthBackend):
    """Each request must have filled `user` attribute"""


class AdminRequiredAuthBackend(BaseAuthBackend):
    """Login-ed used must have `is_superuser` attribute"""

    async def authenticate_user(
        self,
        jwt_token: str,
        token_type: AuthTokenType = AuthTokenType.ACCESS,
    ) -> tuple[User, dict, str]:
        """
        Authenticate user by jwt_token and check that current user is superuser

        :param jwt_token: Currently detected JWT token
        :param token_type: expected token's type (access or refresh)
        """
        user, jwt_payload, session_id = await super().authenticate_user(jwt_token)
        if not user.is_superuser:
            raise PermissionDeniedError("You don't have an admin privileges.")

        return user, jwt_payload, session_id

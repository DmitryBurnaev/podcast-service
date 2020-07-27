import logging
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import and_
from starlette import status

from common.excpetions import AuthenticationFailedError, InvalidParameterError
from common.views import BaseHTTPEndpoint
from modules.auth.hasher import PBKDF2PasswordHasher
from modules.auth.models import User, UserSession, UserInvite
from modules.auth.serializers import (
    JWTResponse,
    SignInRequestSerializer,
    SignUpRequestSerializer,
    RefreshTokenRequestSerializer,
)
from modules.auth.utils import encode_jwt, decode_jwt

logger = logging.getLogger(__name__)


class JWTSessionMixin:

    class TokenCollection(NamedTuple):
        refresh_token: str
        refresh_token_expired_at: str
        access_token: str
        access_token_expired_at: str

    def _get_tokens(self, user: User) -> TokenCollection:
        refresh_token, refresh_token_expired_at = encode_jwt({"user_id": user.id}, refresh=True)
        access_token, access_token_expired_at = encode_jwt({"user_id": user.id})
        return self.TokenCollection(**{
            "refresh_token": refresh_token,
            "refresh_token_expired_at": refresh_token_expired_at,
            "access_token": access_token,
            "access_token_expired_at": access_token_expired_at,
        })

    async def _update_session(self, user: User) -> TokenCollection:
        token_collection = self._get_tokens(user)
        user_session = await UserSession.query.where(
            UserSession.user_id == user.id
        ).gino.first()
        if user_session:
            await user_session.update(
                refresh_token=token_collection.refresh_token,
                expired_at=token_collection.refresh_token_expired_at,
                last_login=datetime.utcnow()
            ).apply()

        else:
            await UserSession.create(
                user_id=user.id,
                refresh_token=token_collection.refresh_token,
                expired_at=token_collection.refresh_token_expired_at
            )

        return token_collection


class SignInAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    serializer_class = SignInRequestSerializer
    response_serializer_class = JWTResponse
    auth_backend = None

    async def post(self, request):
        cleaned_data = await self._validate(request)
        user = await self.authenticate(cleaned_data.email, cleaned_data.password)
        token_collection = await self._update_session(user)
        return self._response(data=token_collection._asdict())

    @staticmethod
    async def authenticate(email, password):
        user = await User.query.where(
            and_(User.email == email, User.is_active.is_(True))
        ).gino.first()
        if not user:
            logger.info("Not found user with email [%s]", email)
            raise AuthenticationFailedError("Not found user with provided email.")

        hasher = PBKDF2PasswordHasher()
        if not hasher.verify(password, encoded=user.password):
            logger.error("Password didn't verify with encoded version (email: [%s])", email)
            raise AuthenticationFailedError("Email or password is invalid.")

        return user


class SignUpAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    serializer_class = SignUpRequestSerializer
    response_serializer_class = JWTResponse
    auth_backend = None

    async def post(self, request):
        cleaned_data: SignUpRequestSerializer = await self._validate(request)
        user = await User.create(
            email=cleaned_data.email,
            password=User.make_password(cleaned_data.password_1),
        )
        token_collection = await self._update_session(user)
        return self._response(data=token_collection._asdict())

    async def _validate(self, request) -> serializer_class:
        serializer: SignUpRequestSerializer = await super()._validate(request)
        if serializer.password_1 != serializer.password_2:
            raise InvalidParameterError("Passwords should be equal")

        invite_token = serializer.invite_token
        email = serializer.email
        user_invite = await self._get_user_invite(invite_token)
        if not user_invite:
            details = "Invitation link is expired or unavailable"
            logger.error("Couldn't signup user token: %s | details: %s", invite_token, details)
            raise InvalidParameterError(details=details)

        if await User.query.where(and_(User.email == email)).gino.scalar():
            raise InvalidParameterError(details=f"User with email '{email}' already exists")

        return serializer

    @staticmethod
    async def _get_user_invite(invite_token: str) -> UserInvite:
        user_invite = await UserInvite.query.where(
            and_(
                UserInvite.token == invite_token,
                UserInvite.is_applied.is_(False),
                UserInvite.expired_at > datetime.utcnow()
            )
        ).gino.first()
        if not user_invite:
            logger.error(f"Couldn't get UserInvite invite_token={invite_token}.")

        return user_invite


class SignOutAPIView(BaseHTTPEndpoint):

    async def post(self, request):
        user = request.user
        logger.info("Log out for user %s", user)
        user_session = await UserSession.query.where(
            and_(
                UserSession.user_id == user.id,
                UserSession.is_active.is_(False)
            )
        ).first()
        if user_session:
            logger.info("Session %s exists and active. It will be updated.", user_session)
            await user_session.update(is_active=False).apply()
        else:
            logger.info("Not found active sessions for user %s. Skip.", user)

        return self._response(status_code=status.HTTP_204_NO_CONTENT)


class RefreshTokenAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    serializer_class = RefreshTokenRequestSerializer
    response_serializer_class = JWTResponse
    auth_backend = None

    async def post(self, request):
        cleaned_data: RefreshTokenRequestSerializer = await self._validate(request)
        token_payload = decode_jwt(cleaned_data.refresh_token)
        user_id = token_payload.get("user_id")
        token_type = token_payload.get("token_type")
        if not user_id:
            raise InvalidParameterError("Refresh token doesn't contain 'user_id'")

        if token_type != "refresh":
            raise InvalidParameterError("Refresh token has invalid token-type")

        user = await User.query.where(
            and_(User.id == user_id, User.is_active.is_(True))
        ).gino.first()
        if not user:
            raise AuthenticationFailedError("Active user not found")

        user_session: UserSession = await UserSession.query.where(
            and_(
                UserSession.user_id == user_id,
                UserSession.is_active.is_(True)
            )
        ).gino.first()
        if not user_session:
            raise AuthenticationFailedError("There is not active session for user")

        if user_session.refresh_token != cleaned_data.refresh_token:
            raise AuthenticationFailedError("Refresh token is not active for user session")

        token_collection = await self._update_session(user)
        return self._response(data=token_collection._asdict())

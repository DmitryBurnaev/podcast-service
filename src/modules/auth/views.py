import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple

from starlette import status

from core import settings
from common.views import BaseHTTPEndpoint
from common.db_utils import db_transaction
from common.utils import send_email, get_logger
from common.exceptions import AuthenticationFailedError, InvalidParameterError
from modules.auth.models import User, UserSession, UserInvite
from modules.auth.hasher import PBKDF2PasswordHasher, get_salt
from modules.auth.backend import AdminRequiredAuthBackend, LoginRequiredAuthBackend
from modules.auth.utils import encode_jwt, TOKEN_TYPE_REFRESH, TOKEN_TYPE_RESET_PASSWORD
from modules.auth.schemas import (
    SignInSchema,
    SignUpSchema,
    JWTResponseSchema,
    RefreshTokenSchema,
    UserResponseSchema,
    ChangePasswordSchema,
    UserInviteRequestSchema,
    UserInviteResponseSchema,
    ResetPasswordRequestSchema,
    ResetPasswordResponseSchema,
)
from modules.podcast.models import Podcast

logger = get_logger(__name__)


@dataclass
class TokenCollection:
    refresh_token: str
    refresh_token_expired_at: datetime
    access_token: str
    access_token_expired_at: datetime


class JWTSessionMixin:
    """ Allows to update session and prepare usual / refresh JWT tokens """

    schema_response = JWTResponseSchema

    @staticmethod
    def _get_tokens(user: User) -> TokenCollection:
        access_token, access_token_expired_at = encode_jwt({"user_id": user.id})
        refresh_token, refresh_token_expired_at = encode_jwt(
            {"user_id": user.id},
            token_type=TOKEN_TYPE_REFRESH,
        )
        return TokenCollection(
            refresh_token=refresh_token,
            refresh_token_expired_at=refresh_token_expired_at,
            access_token=access_token,
            access_token_expired_at=access_token_expired_at,
        )

    async def _update_session(self, user: User) -> TokenCollection:
        token_collection = self._get_tokens(user)
        user_session = await UserSession.async_get(user_id=user.id)
        if user_session:
            await user_session.update(
                refresh_token=token_collection.refresh_token,
                expired_at=token_collection.refresh_token_expired_at,
                last_login=datetime.utcnow(),
                is_active=True,
            ).apply()

        else:
            await UserSession.create(
                user_id=user.id,
                refresh_token=token_collection.refresh_token,
                expired_at=token_collection.refresh_token_expired_at,
            )

        return token_collection


class SignInAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """ Allows to Log-In user and update/create his session """

    schema_request = SignInSchema
    auth_backend = None

    async def post(self, request):
        cleaned_data = await self._validate(request)
        user = await self.authenticate(cleaned_data["email"], cleaned_data["password"])
        token_collection = await self._update_session(user)
        return self._response(token_collection)

    @staticmethod
    async def authenticate(email: str, password: str) -> User:
        user = await User.async_get(email=email, is_active__is=True)
        if not user:
            logger.info("Not found active user with email [%s]", email)
            raise AuthenticationFailedError("Not found active user with provided email.")

        hasher = PBKDF2PasswordHasher()
        verified, error_msg = hasher.verify(password, encoded=user.password)
        if not verified:
            logger.error("Password didn't verify: email: %s | err: %s", email, error_msg)
            raise AuthenticationFailedError("Email or password is invalid.")

        return user


class SignUpAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """ Allows to create new user and create his own session """

    schema_request = SignUpSchema
    auth_backend = None

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        user_invite: UserInvite = cleaned_data["user_invite"]
        user = await User.create(
            email=cleaned_data["email"],
            password=User.make_password(cleaned_data["password_1"]),
        )
        await UserInvite.async_update(
            filter_kwargs={"id": user_invite.id},
            update_data={"is_applied": True, "user_id": user.id},
        )
        await Podcast.create_first_podcast(user.id)
        token_collection = await self._update_session(user)
        return self._response(token_collection, status_code=status.HTTP_201_CREATED)

    async def _validate(self, request, partial_: bool = False, location: str = None) -> dict:
        cleaned_data = await super()._validate(request)
        email = cleaned_data["email"]

        if await User.async_get(email=email):
            raise InvalidParameterError(details=f"User with email '{email}' already exists")

        user_invite = await UserInvite.async_get(
            token=cleaned_data["invite_token"],
            is_applied__is=False,
            expired_at__gt=datetime.utcnow(),
        )
        if not user_invite:
            details = "Invitation link is expired or unavailable"
            logger.error(
                "Couldn't signup user token: %s | details: %s",
                cleaned_data["invite_token"],
                details,
            )
            raise InvalidParameterError(details=details)

        if email != user_invite.email:
            raise InvalidParameterError(details="Email does not match with your invitation.")

        cleaned_data["user_invite"] = user_invite
        return cleaned_data


class SignOutAPIView(BaseHTTPEndpoint):
    """
    Sign-out consists from 2 operations:
     - remove JWT token on front-end side
     - deactivate current session on BE (this allows to block use regular or refresh token)
    """

    async def delete(self, request):
        user = request.user
        logger.info("Log out for user %s", user)
        user_session = await UserSession.async_get(user_id=user.id, is_active=True)
        if user_session:
            logger.info("Session %s exists and active. It will be updated.", user_session)
            await user_session.update(is_active=False).apply()
        else:
            logger.info("Not found active sessions for user %s. Skip sign-out.", user)

        return self._response(status_code=status.HTTP_204_NO_CONTENT)


class RefreshTokenAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """ Allows to update tokens (should be called when main token is outdated) """

    schema_request = RefreshTokenSchema
    auth_backend = None

    @db_transaction
    async def post(self, request):
        user, refresh_token = await self._validate(request)

        user_session = await UserSession.async_get(user_id=user.id, is_active=True)
        if not user_session:
            raise AuthenticationFailedError("There is not active session for user.")

        if user_session.refresh_token != refresh_token:
            raise AuthenticationFailedError("Refresh token is not active for user session.")

        token_collection = await self._update_session(user)
        return self._response(token_collection)

    async def _validate(self, request, *args, **kwargs) -> Tuple[User, str]:
        cleaned_data = await super()._validate(request)
        refresh_token = cleaned_data["refresh_token"]
        user, jwt_payload = await LoginRequiredAuthBackend().authenticate_user(
            refresh_token, token_type="refresh"
        )
        return user, refresh_token


class InviteUserAPIView(BaseHTTPEndpoint):
    """ Invite user (by email) to podcast-service """

    schema_request = UserInviteRequestSchema
    schema_response = UserInviteResponseSchema

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        email = cleaned_data["email"]
        token = UserInvite.generate_token()
        expired_at = datetime.utcnow() + timedelta(seconds=settings.INVITE_LINK_EXPIRES_IN)

        if user_invite := await UserInvite.async_get(email=email):
            logger.info("INVITE: update for %s (expired %s) token [%s]", email, expired_at, token)
            await user_invite.update(token=token, expired_at=expired_at).apply()

        else:
            logger.info("INVITE: create for %s (expired %s) token [%s]", email, expired_at, token)
            user_invite = await UserInvite.create(
                email=email,
                token=token,
                expired_at=expired_at,
                created_by_id=request.user.id,
            )

        logger.info("Invite object %r created. Sending message...", user_invite)
        await self._send_email(user_invite)
        return self._response(user_invite, status_code=status.HTTP_201_CREATED)

    @staticmethod
    async def _send_email(user_invite: UserInvite):
        link = f"{settings.SITE_URL}/sign-up/?t={user_invite.token}"
        body = (
            f"<p>Hello! :) You have been invited to {settings.SITE_URL}</p>"
            f"<p>Please follow the link </p>"
            f"<p><a href={link}>{link}</a></p>"
        )
        await send_email(
            recipient_email=user_invite.email,
            subject=f"Welcome to {settings.SITE_URL}",
            html_content=body.strip(),
        )

    async def _validate(self, request, partial_: bool = False, location: str = None) -> dict:
        cleaned_data = await super()._validate(request)
        if exists_user := await User.async_get(email=cleaned_data["email"]):
            raise InvalidParameterError(f"User with email=[{exists_user.email}] already exists.")

        return cleaned_data


class ResetPasswordAPIView(BaseHTTPEndpoint):
    """ Send link to user's email for resetting his password """

    schema_request = ResetPasswordRequestSchema
    schema_response = ResetPasswordResponseSchema
    auth_backend = AdminRequiredAuthBackend

    @db_transaction
    async def post(self, request):
        user = await self._validate(request)
        token = self._generate_token(user)
        await self._send_email(user, token)
        return self._response(data={"user_id": user.id, "email": user.email, "token": token})

    async def _validate(self, request, partial_: bool = False, location: str = None) -> User:
        cleaned_data = await super()._validate(request)
        user = await User.async_get(email=cleaned_data["email"])
        if not user:
            raise InvalidParameterError(f"User with email=[{cleaned_data['email']}] not found.")

        return user

    @staticmethod
    async def _send_email(user: User, token: str):
        link = f"{settings.SITE_URL}/change-password/?t={token}"
        body = (
            f"<p>You can reset your password for {settings.SITE_URL}</p>"
            f"<p>Please follow the link </p>"
            f"<p><a href={link}>{link}</a></p>"
        )
        await send_email(
            recipient_email=user.email,
            subject=f"Welcome back to {settings.SITE_URL}",
            html_content=body.strip(),
        )

    @staticmethod
    def _generate_token(user: User) -> str:
        payload = {
            "user_id": user.id,
            "email": user.email,
            "jti": f"token-{uuid.uuid4()}",  # JWT ID
            "slt": get_salt(),
        }
        token, _ = encode_jwt(
            payload,
            token_type=TOKEN_TYPE_RESET_PASSWORD,
            expires_in=settings.RESET_PASSWORD_LINK_EXPIRES_IN,
        )
        return token


class ChangePasswordAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """ Simple API for changing user's password """

    schema_request = ChangePasswordSchema
    auth_backend = None

    @db_transaction
    async def post(self, request):
        """ Check is email unique and create new User """
        cleaned_data = await self._validate(request)
        user, _ = await LoginRequiredAuthBackend().authenticate_user(
            cleaned_data["token"],
            token_type=TOKEN_TYPE_RESET_PASSWORD,
        )
        new_password = User.make_password(cleaned_data["password_1"])
        await user.update(password=new_password).apply()

        token_collection = await self._update_session(user)
        return self._response(token_collection)


class ProfileApiView(BaseHTTPEndpoint):
    """ Simple retrieves profile information (for authenticated user) """

    schema_response = UserResponseSchema

    async def get(self, request):
        return self._response(request.user)

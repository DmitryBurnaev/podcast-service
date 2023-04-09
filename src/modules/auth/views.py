import json
import uuid
import base64
import logging
from typing import Generator, Iterable
from uuid import UUID
from datetime import datetime, timedelta

from sqlalchemy import select
from starlette import status
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from common.request import PRequest
from common.views import BaseHTTPEndpoint
from common.statuses import ResponseStatus
from common.utils import send_email
from common.exceptions import AuthenticationFailedError, InvalidRequestError
from modules.auth.models import User, UserSession, UserInvite, UserIP
from modules.auth.hasher import PBKDF2PasswordHasher, get_salt
from modules.auth.backend import AdminRequiredAuthBackend, LoginRequiredAuthBackend
from modules.auth.utils import (
    encode_jwt,
    register_ip,
    TokenCollection,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_RESET_PASSWORD,
)
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
    UserPatchRequestSchema,
    UserIPsResponseSchema,
    UserIPsDeleteRequestSchema,
)
from modules.media.models import File
from modules.podcast.models import Podcast
from modules.podcast.schemas import BaseLimitOffsetSchema

logger = logging.getLogger(__name__)


class JWTSessionMixin:
    """Allows to update session and prepare usual / refresh JWT tokens"""

    schema_response = JWTResponseSchema
    db_session: AsyncSession = NotImplemented

    @staticmethod
    def _get_tokens(user_id: int, session_id: str | UUID) -> TokenCollection:
        token_payload = {"user_id": user_id, "session_id": str(session_id)}
        access_token, access_token_expired_at = encode_jwt(token_payload)
        refresh_token, refresh_token_expired_at = encode_jwt(
            token_payload,
            token_type=TOKEN_TYPE_REFRESH,
        )
        return TokenCollection(
            refresh_token=refresh_token,
            refresh_token_expired_at=refresh_token_expired_at,
            access_token=access_token,
            access_token_expired_at=access_token_expired_at,
        )

    async def _create_session(self, request: PRequest, user: User) -> TokenCollection:
        request.scope["user"] = user
        session_id = uuid.uuid4()
        token_collection = self._get_tokens(user.id, session_id)
        await UserSession.async_create(
            self.db_session,
            user_id=user.id,
            public_id=str(session_id),
            refresh_token=token_collection.refresh_token,
            expired_at=token_collection.refresh_token_expired_at,
        )
        await register_ip(request)
        return token_collection

    async def _update_session(self, user: User, user_session: UserSession) -> TokenCollection:
        token_collection = self._get_tokens(user.id, session_id=user_session.public_id)
        await user_session.update(
            self.db_session,
            refresh_token=token_collection.refresh_token,
            expired_at=token_collection.refresh_token_expired_at,
            refreshed_at=datetime.utcnow(),
            is_active=True,
        )
        return token_collection


class SignInAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """Allows to Log-In user and update/create his session"""

    schema_request = SignInSchema
    auth_backend = None

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        user = await self.authenticate(cleaned_data["email"], cleaned_data["password"])
        token_collection = await self._create_session(request, user)
        return self._response(token_collection)

    async def authenticate(self, email: str, password: str) -> User:
        user = await User.async_get(db_session=self.db_session, email=email, is_active__is=True)
        if not user:
            logger.info("Not found active user with email [%s]", email)
            raise AuthenticationFailedError(
                "Not found active user with provided email.",
                response_status=ResponseStatus.INVALID_PARAMETERS,
            )

        hasher = PBKDF2PasswordHasher()
        verified, error_msg = hasher.verify(password, encoded=user.password)
        if not verified:
            logger.error("Password didn't verify: email: %s | err: %s", email, error_msg)
            raise AuthenticationFailedError(
                "Email or password is invalid.", response_status=ResponseStatus.INVALID_PARAMETERS
            )

        return user


class SignUpAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """Allows to create new user and create his own session"""

    schema_request = SignUpSchema
    auth_backend = None

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        user_invite: UserInvite = cleaned_data["user_invite"]
        user = await User.async_create(
            self.db_session,
            email=cleaned_data["email"],
            password=User.make_password(cleaned_data["password_1"]),
        )
        await user_invite.update(self.db_session, is_applied=True, user_id=user.id)
        await Podcast.create_first_podcast(self.db_session, user.id)
        token_collection = await self._create_session(request, user)
        return self._response(token_collection, status_code=status.HTTP_201_CREATED)

    async def _validate(self, request: PRequest, *_) -> dict:
        cleaned_data = await super()._validate(request)
        email = cleaned_data["email"]

        if await User.async_get(self.db_session, email=email):
            raise InvalidRequestError(details=f"User with email '{email}' already exists")

        user_invite = await UserInvite.async_get(
            self.db_session,
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
            raise InvalidRequestError(details=details)

        if email != user_invite.email:
            raise InvalidRequestError(message="Email does not match with your invitation.")

        cleaned_data["user_invite"] = user_invite
        return cleaned_data


class SignOutAPIView(BaseHTTPEndpoint):
    """
    Sign-out consists from 2 operations:
     - remove JWT token on front-end side
     - deactivate current session on BE (this allows to block use regular or refresh token)
    """

    async def delete(self, request: PRequest) -> Response:
        user = request.user
        logger.info("Log out for user %s", user)

        user_session = await UserSession.async_get(
            self.db_session, public_id=request.user_session_id, is_active=True
        )
        if user_session:
            logger.info("Session %s exists and active. It will be updated.", user_session)
            user_session.is_active = False
            await self.db_session.flush()

        else:
            logger.info("Not found active sessions for user %s. Skip sign-out.", user)

        return self._response(status_code=status.HTTP_200_OK)


class RefreshTokenAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """Allows to update tokens (should be called when main token is outdated)"""

    schema_request = RefreshTokenSchema
    auth_backend = None

    async def post(self, request: PRequest) -> Response:
        user, refresh_token, session_id = await self._validate(request)
        if session_id is None:
            raise AuthenticationFailedError("No session ID in token found")

        user_session = await UserSession.async_get(
            self.db_session, public_id=session_id, is_active=True
        )
        if not user_session:
            raise AuthenticationFailedError("There is not active session for user.")

        if user_session.refresh_token != refresh_token:
            raise AuthenticationFailedError("Refresh token does not match with user session.")

        token_collection = await self._update_session(user, user_session)
        return self._response(token_collection)

    async def _validate(self, request: PRequest, *_) -> tuple[User, str, str | None]:
        cleaned_data = await super()._validate(request)
        refresh_token = cleaned_data["refresh_token"]
        user, jwt_payload, _ = await LoginRequiredAuthBackend(request).authenticate_user(
            refresh_token, token_type=TOKEN_TYPE_REFRESH
        )
        return user, refresh_token, jwt_payload.get("session_id")


class InviteUserAPIView(BaseHTTPEndpoint):
    """Invite user (by email) to podcast-service"""

    schema_request = UserInviteRequestSchema
    schema_response = UserInviteResponseSchema

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        email = cleaned_data["email"]
        token = UserInvite.generate_token()
        expired_at = datetime.utcnow() + timedelta(seconds=settings.INVITE_LINK_EXPIRES_IN)

        if user_invite := await UserInvite.async_get(self.db_session, email=email):
            logger.info("INVITE: update for %s (expired %s) token [%s]", email, expired_at, token)
            await user_invite.update(self.db_session, token=token, expired_at=expired_at)

        else:
            logger.info("INVITE: create for %s (expired %s) token [%s]", email, expired_at, token)
            user_invite = await UserInvite.async_create(
                self.db_session,
                email=email,
                token=token,
                expired_at=expired_at,
                owner_id=request.user.id,
            )

        logger.info("Invite object %r created/updated. Sending message...", user_invite)
        await self._send_email(user_invite)
        return self._response(user_invite, status_code=status.HTTP_201_CREATED)

    @staticmethod
    async def _send_email(user_invite: UserInvite) -> None:
        invite_data = {"token": user_invite.token, "email": user_invite.email}
        invite_data = base64.urlsafe_b64encode(json.dumps(invite_data).encode()).decode()
        link = f"{settings.SITE_URL}/sign-up/?i={invite_data}"
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

    async def _validate(self, request: PRequest, *_) -> dict:
        cleaned_data = await super()._validate(request)
        if exists_user := await User.async_get(self.db_session, email=cleaned_data["email"]):
            raise InvalidRequestError(f"User with email=[{exists_user.email}] already exists.")

        return cleaned_data


class ResetPasswordAPIView(BaseHTTPEndpoint):
    """Send link to user's email for resetting his password"""

    schema_request = ResetPasswordRequestSchema
    schema_response = ResetPasswordResponseSchema
    auth_backend = AdminRequiredAuthBackend

    async def post(self, request: PRequest) -> Response:
        user = await self._validate(request)
        token = self._generate_token(user)
        await self._send_email(user, token)
        return self._response(data={"user_id": user.id, "email": user.email, "token": token})

    async def _validate(self, request: PRequest, *_) -> User:
        cleaned_data = await super()._validate(request)
        user = await User.async_get(self.db_session, email=cleaned_data["email"])
        if not user:
            raise InvalidRequestError(f"User with email=[{cleaned_data['email']}] not found.")

        return user

    @staticmethod
    async def _send_email(user: User, token: str) -> None:
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
    """Simple API for changing user's password"""

    schema_request = ChangePasswordSchema
    auth_backend = None

    async def post(self, request: PRequest) -> Response:
        """Check is email unique and create new User"""
        cleaned_data = await self._validate(request)
        user, *_ = await LoginRequiredAuthBackend(request).authenticate_user(
            jwt_token=cleaned_data["token"],
            token_type=TOKEN_TYPE_RESET_PASSWORD,
        )
        new_password = User.make_password(cleaned_data["password_1"])
        await user.update(self.db_session, password=new_password)
        # deactivate all user's sessions
        await UserSession.async_update(
            self.db_session, filter_kwargs={"user_id": user.id}, update_data={"is_active": False}
        )
        return self._response()


class ProfileApiView(BaseHTTPEndpoint):
    """Simple retrieves profile information (for authenticated user)"""

    schema_response = UserResponseSchema
    schema_request = UserPatchRequestSchema

    async def get(self, request: PRequest) -> Response:
        await register_ip(request)
        return self._response(request.user)

    async def patch(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        if cleaned_data:
            await request.user.update(self.db_session, db_commit=True, **cleaned_data)
            await self.db_session.refresh(request.user)
        return self._response(request.user)

    async def _validate(self, request, *_) -> dict:
        cleaned_data = await super()._validate(request)
        update_data = {}

        if cleaned_data["email"] and request.user.email != cleaned_data["email"]:
            update_data["email"] = cleaned_data["email"]

        if password := cleaned_data.get("password_1"):
            update_data["password"] = User.make_password(password)

        return update_data


class UserIPsRetrieveAPIView(BaseHTTPEndpoint):
    schema_request = BaseLimitOffsetSchema
    schema_response = UserIPsResponseSchema

    async def get(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request, location="query")
        limit, offset = cleaned_data["limit"], cleaned_data["offset"]
        ips_query = (
            select(UserIP, Podcast)
            .outerjoin(File, UserIP.registered_by == File.access_token)  # noqa
            .outerjoin(Podcast, File.id == Podcast.rss_id)
            .filter(UserIP.user_id == request.user.id)
            .order_by(UserIP.created_at.desc())
        )

        def process_items(items: Iterable[tuple]) -> Generator:
            """
            query consists of tuple (UserIP, Podcast).
            we need to combine it before response and after limit / offset operations
            """
            for user_ip, podcast in items:
                user_ip.podcast = podcast
                yield user_ip

        return await self._paginated_response(
            ips_query,
            limit=limit,
            offset=offset,
            process_items=process_items,
        )


class UserIPsDeleteAPIView(BaseHTTPEndpoint):
    schema_request = UserIPsDeleteRequestSchema

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        await UserIP.async_delete(
            self.db_session, user_id=request.user.id, ip_address__in=cleaned_data["ips"]
        )
        return self._response()

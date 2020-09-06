import logging
import uuid
from datetime import datetime, timedelta
from typing import NamedTuple, Tuple

from marshmallow import validate, Schema
from sqlalchemy import and_
from starlette import status
from starlette.responses import JSONResponse
from webargs import fields
from webargs_starlette import parser

from core import settings
from common.db_utils import db_transaction
from common.exceptions import AuthenticationFailedError, InvalidParameterError
from common.utils import send_email
from common.views import BaseHTTPEndpoint, JSONResponseNew
from modules.auth.backend import AdminRequiredAuthBackend
from modules.auth.hasher import PBKDF2PasswordHasher, get_salt
from modules.auth.models import User, UserSession, UserInvite
from modules.auth import serializers
from modules.auth.utils import encode_jwt, decode_jwt

logger = logging.getLogger(__name__)


class JWTSessionMixin:
    model_response = serializers.JWTResponseModel

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
        user_session = await UserSession.async_get(user_id=user.id)
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


# class
class TokenSchema(Schema):
    access_token = fields.Str(required=True)
    refresh_token = fields.Str(required=True)


class SignInAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    model = serializers.SignInModel
    auth_backend = None
    request_schema = {"email": fields.Email(required=True), "password": fields.Str(required=True)}
    response_schema = {
        "access_token": fields.Str(required=True),
        "refresh_token": fields.Str(required=True)
    }

    async def post(self, request):
        cleaned_data = await parser.parse(self.request_schema, request)
        # cleaned_data = await self._validate(request)
        user = await self.authenticate(cleaned_data["email"], cleaned_data["password"])
        token_collection = await self._update_session(user)
        schema = TokenSchema()
        return JSONResponse(schema.dump(token_collection))

        # return self._response(data=token_collection._asdict())

    # async def post(self, request):
    #     # cleaned_data = await parser.parse(self.request_schema, request)
    #     cleaned_data = await self._validate(request)
    #     user = await self.authenticate(cleaned_data.email, cleaned_data.password)
    #     token_collection = await self._update_session(user)
    #     return self._response(data=token_collection._asdict())

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
    model = serializers.SignUpModel
    auth_backend = None

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        user = await User.create(
            email=cleaned_data.email,
            password=User.make_password(cleaned_data.password_1),
        )
        token_collection = await self._update_session(user)
        return self._response(data=token_collection._asdict())

    async def _validate(self, request) -> serializers.SignUpModel:
        serializer = await super()._validate(request)
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

    async def get(self, request):
        user = request.user
        logger.info("Log out for user %s", user)
        user_session = await UserSession.async_get(user_id=user.id, is_active=True)
        if user_session:
            logger.info("Session %s exists and active. It will be updated.", user_session)
            await user_session.update(is_active=False).apply()
        else:
            logger.info("Not found active sessions for user %s. Skip.", user)

        return self._response(status_code=status.HTTP_204_NO_CONTENT)


class RefreshTokenAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    model = serializers.RefreshTokenModel
    auth_backend = None

    @db_transaction
    async def post(self, request):
        user_id, refresh_token = await self._validate(request)

        user = await User.get_active(user_id)
        if not user:
            raise AuthenticationFailedError("Active user not found")

        user_session = await UserSession.async_get(user_id=user_id, is_active=True)
        if not user_session:
            raise AuthenticationFailedError("There is not active session for user")

        if user_session.refresh_token != refresh_token:
            raise AuthenticationFailedError("Refresh token is not active for user session")

        token_collection = await self._update_session(user)
        return self._response(data=token_collection._asdict())

    async def _validate(self, request) -> Tuple[int, str]:
        cleaned_data = await super()._validate(request)
        token_payload = decode_jwt(cleaned_data.refresh_token)
        user_id = token_payload.get("user_id")
        if not user_id:
            raise InvalidParameterError("Refresh token doesn't contain 'user_id'")

        token_type = token_payload.get("token_type")
        if token_type != "refresh":
            raise InvalidParameterError("Refresh token has invalid token-type")

        return user_id, cleaned_data.refresh_token


class InviteUserAPIView(BaseHTTPEndpoint):
    """ Invite user (by email) to podcast-service """

    model = serializers.UserInviteModel
    model_response = serializers.UserInviteResponseModel

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        email = cleaned_data.email
        token = UserInvite.generate_token()
        expired_at = datetime.utcnow() + timedelta(seconds=settings.INVITE_LINK_EXPIRES_IN)

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

    async def _validate(self, request) -> model:
        cleaned_data = await super()._validate(request)
        email_exists = await UserInvite.async_get(email=cleaned_data.email)
        if email_exists:
            raise InvalidParameterError(f"User with email=[{cleaned_data.email}] already exists")

        return cleaned_data


class ResetPasswordAPIView(BaseHTTPEndpoint):
    """ Remove current user from session """

    model = serializers.ResetPasswordModel
    model_response = serializers.ResetPasswordResponseModel
    auth_backend = AdminRequiredAuthBackend

    @db_transaction
    async def post(self, request):
        user = await self._validate(request)
        token = self._generate_token(user)
        await self._send_email(user, token)
        return self._response(data={"user_id": user.id, "email": user.email, "token": token})

    async def _validate(self, request) -> User:
        cleaned_data = await super()._validate(request)
        user = await User.async_get(email=cleaned_data.email)
        if not user:
            raise InvalidParameterError(f"User with email=[{cleaned_data.email}] not found")

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
        token, _ = encode_jwt(payload, expires_in=settings.RESET_PASSWORD_LINK_EXPIRES_IN)
        return token


class ChangePasswordAPIView(JWTSessionMixin, BaseHTTPEndpoint):
    """ Create new user in db """

    model = serializers.ChangePasswordModel
    model_response = serializers.JWTResponseModel

    @db_transaction
    async def post(self, request):
        """ Check is email unique and create new User """
        cleaned_data = await self._validate(request)
        new_password = User.make_password(cleaned_data.password_1)
        await request.user.update(password=new_password).apply()

        token_collection = await self._update_session(request.user)
        return self._response(data=token_collection._asdict())

    async def _validate(self, request) -> serializers.ChangePasswordModel:
        model = await super()._validate(request)
        if model.password_1 != model.password_2:
            raise InvalidParameterError("Passwords should be equal")

        return model


class ProfileApiView(BaseHTTPEndpoint):
    """ Simple retrieves profile information (for authenticated user) """
    model_response = serializers.UserResponseModel

    async def get(self, request):
        return self._response(request.user)

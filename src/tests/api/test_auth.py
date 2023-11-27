import json
import uuid
import base64
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.request import PRequest
from common.statuses import ResponseStatus
from common.utils import hash_string
from core import settings
from modules.auth.models import User, UserSession, UserInvite, UserIP
from modules.auth.utils import (
    decode_jwt,
    encode_jwt,
    TOKEN_TYPE_RESET_PASSWORD,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_ACCESS,
    register_ip,
)
from modules.podcast.models import Podcast
from tests.api.test_base import BaseTestAPIView
from tests.helpers import prepare_request, PodcastTestClient

INVALID_SIGN_IN_DATA = [
    [{"email": "fake-email"}, {"email": "Not a valid email address."}],
    [{"password": ""}, {"password": "Length must be between 2 and 32."}],
    [
        {},
        {
            "email": "Missing data for required field.",
            "password": "Missing data for required field.",
        },
    ],
]

INVALID_SIGN_UP_DATA = [
    [
        {},
        {
            "email": "Missing data for required field.",
            "invite_token": "Missing data for required field.",
        },
    ],
    [
        {
            "email": "test@test.com",
            "invite_token": uuid.uuid4().hex,
        },
        {
            "password_1": "Password is required",
        },
    ],
    [
        {"email": ("user_" * 30 + "@t.com")},
        {"email": "Longer than maximum length 128."},
    ],
    [
        {"email": "fake-email"},
        {"email": "Not a valid email address."},
    ],
    [
        {
            "email": "test@test.com",
            "invite_token": uuid.uuid4().hex,
            "password_1": "Header",
            "password_2": "Footer",
        },
        {"password_1": "Passwords must be equal", "password_2": "Passwords must be equal"},
    ],
    [
        {"invite_token": "token"},
        {"invite_token": "Length must be between 10 and 32."},
    ],
]
INVALID_INVITE_DATA = [
    [{"email": "fake-email"}, {"email": "Not a valid email address."}],
    [{}, {"email": "Missing data for required field."}],
]
INVALID_CHANGE_PASSWORD_DATA = [
    [{"password_1": "123456", "token": "t"}, {"password_2": "Password is required"}],
    [{"password_1": "foo", "password_2": "foo"}, {"token": "Missing data for required field."}],
    [
        {"password_1": "header", "password_2": "footer", "token": "t"},
        {"password_1": "Passwords must be equal", "password_2": "Passwords must be equal"},
    ],
    [
        {"password_1": "header", "password_2": "footer", "token": ""},
        {"token": "Shorter than minimum length 1."},
    ],
]
pytestmark = pytest.mark.asyncio


def assert_tokens(response_data: dict, user: User, session_id: str = None):
    """Allows to check access- and refresh-tokens in the response body"""

    access_token = response_data.get("access_token")
    refresh_token = response_data.get("refresh_token")
    assert access_token, f"No access_token in response: {response_data}"
    assert refresh_token, f"No refresh_token in response: {response_data}"

    decoded_access_token = decode_jwt(access_token)
    access_exp_dt = datetime.fromisoformat(decoded_access_token.pop("exp_iso"))
    assert access_exp_dt > datetime.utcnow()
    assert decoded_access_token.get("user_id") == user.id, decoded_access_token
    assert decoded_access_token.get("token_type") == "access", decoded_access_token

    decoded_refresh_token = decode_jwt(refresh_token)
    refresh_exp_dt = datetime.fromisoformat(decoded_refresh_token.pop("exp_iso"))
    assert refresh_exp_dt > datetime.utcnow()
    assert decoded_refresh_token.get("user_id") == user.id, decoded_refresh_token
    assert decoded_refresh_token.get("token_type") == "refresh", decoded_refresh_token
    assert refresh_exp_dt > access_exp_dt

    if session_id:
        assert decoded_refresh_token.get("session_id") == session_id


class TestAuthSignInAPIView(BaseTestAPIView):
    url = "/api/auth/sign-in/"
    raw_password = "test-password"
    default_fail_status_code = 401
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    @classmethod
    def setup_class(cls):
        cls.encoded_password = User.make_password(cls.raw_password)

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"

    async def _create_user(self, dbs, is_active=True):
        self.user = await User.async_create(
            dbs,
            db_commit=True,
            email=self.email,
            password=self.encoded_password,
            is_active=is_active,
        )

    async def test_sign_in__ok(self, dbs: AsyncSession, client: PodcastTestClient):
        await self._create_user(dbs)
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        response_data = self.assert_ok_response(response)
        assert_tokens(response_data, self.user)

    async def test_sign_in__check_user_session__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
    ):
        await self._create_user(dbs)
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        response_data = self.assert_ok_response(response)

        refresh_token = response_data.get("refresh_token")
        decoded_refresh_token = decode_jwt(refresh_token)
        refresh_exp_dt = datetime.fromisoformat(decoded_refresh_token.pop("exp_iso"))

        user_session: UserSession = await UserSession.async_get(dbs, user_id=self.user.id)
        assert user_session.refresh_token == refresh_token
        assert user_session.is_active is True
        assert user_session.expired_at == refresh_exp_dt
        assert user_session.refreshed_at is not None
        assert decoded_refresh_token.get("session_id") == user_session.public_id

    async def test_sign_in__create_new_user_session__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
    ):
        await self._create_user(dbs)
        old_expired_at = datetime.now() + timedelta(seconds=1)
        old_user_session = await UserSession.async_create(
            dbs,
            is_active=True,
            user_id=self.user.id,
            public_id=str(uuid.uuid4()),
            refresh_token="refresh_token",
            expired_at=old_expired_at,
        )
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        response_data = self.assert_ok_response(response)
        refresh_token = response_data.get("refresh_token")

        user_sessions = (await UserSession.async_filter(dbs, user_id=self.user.id)).all()
        assert len(user_sessions) == 2
        old_session, new_session = user_sessions

        assert old_session.id == old_user_session.id
        assert old_session.is_active is True
        assert old_session.expired_at == old_expired_at
        assert old_session.refreshed_at == old_user_session.refreshed_at

        assert new_session.refresh_token == refresh_token
        assert new_session.is_active is True
        assert old_session.refreshed_at is not None

    async def test_sign_in__password_mismatch__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
    ):
        await self._create_user(dbs)
        response = client.post(self.url, json={"email": self.email, "password": "fake-password"})
        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Authentication credentials are invalid.",
            "details": "Email or password is invalid.",
        }

    async def test_sign_in__user_not_found__fail(self, client: PodcastTestClient):
        response = client.post(self.url, json={"email": "fake@t.ru", "password": self.raw_password})
        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Authentication credentials are invalid.",
            "details": "Not found active user with provided email.",
        }

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_SIGN_IN_DATA)
    async def test_sign_in__invalid_request__fail(
        self, client: PodcastTestClient, invalid_data: dict, error_details: dict
    ):
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    async def test_sign_in__user_inactive__fail(self, dbs: AsyncSession, client: PodcastTestClient):
        await self._create_user(dbs, is_active=False)
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Authentication credentials are invalid.",
            "details": "Not found active user with provided email.",
        }


class TestAuthSignUPAPIView(BaseTestAPIView):
    url = "/api/auth/sign-up/"
    default_fail_status_code = 400
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    @staticmethod
    def _sign_up_data(user_invite: UserInvite):
        return {
            "email": user_invite.email,
            "invite_token": user_invite.token,
            "password_1": "test-password",
            "password_2": "test-password",
        }

    async def test_sign_up__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user_invite: UserInvite,
    ):
        request_data = self._sign_up_data(user_invite)
        response = client.post(self.url, json=request_data)
        response_data = self.assert_ok_response(response, status_code=201)

        user = await User.async_get(dbs, email=request_data["email"])
        assert user is not None, f"User wasn't created with {request_data=}"
        assert_tokens(response_data, user)

        await dbs.refresh(user_invite)
        assert user_invite.user_id == user.id
        assert user_invite.is_applied
        assert await Podcast.async_get(dbs, owner_id=user.id) is not None

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_SIGN_UP_DATA)
    async def test_sign_up__invalid_request__fail(
        self, client, invalid_data: dict, error_details: dict
    ):
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    async def test_sign_up__user_already_exists__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user_invite: UserInvite,
    ):
        request_data = self._sign_up_data(user_invite)
        user_email = request_data["email"]

        await User.async_create(dbs, db_commit=True, email=user_email, password="pass")
        response = client.post(self.url, json=request_data)
        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": f"User with email '{user_email}' already exists",
        }

    @pytest.mark.parametrize(
        "token_update_data",
        [
            {"token": f"outdated-token-{uuid.uuid4().hex[:10]}"},
            {"expired_at": datetime.utcnow() - timedelta(hours=1)},
            {"is_applied": True},
        ],
    )
    async def test_sign_up__token_problems__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user_invite: UserInvite,
        token_update_data: dict,
    ):
        request_data = self._sign_up_data(user_invite)
        await user_invite.update(dbs, **token_update_data)
        await dbs.commit()
        response = client.post(self.url, json=request_data)
        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": "Invitation link is expired or unavailable",
        }

    async def test_sign_up__email_mismatch_with_token__fail(
        self,
        client: PodcastTestClient,
        user_invite: UserInvite,
    ):
        request_data = self._sign_up_data(user_invite)
        request_data["email"] = f"another.email{uuid.uuid4().hex[:10]}@test.com"
        response = client.post(self.url, json=request_data)
        response_data = self.assert_fail_response(response)
        assert response_data["error"] == "Email does not match with your invitation."


class TestSignOutAPIView(BaseTestAPIView):
    url = "/api/auth/sign-out/"

    async def test_sign_out__ok(self, dbs: AsyncSession, client: PodcastTestClient, user: User):
        user_session = await client.login(user)
        response = client.delete(self.url)
        assert response.status_code == 200
        user_session = await UserSession.async_get(dbs, id=user_session.id)
        assert user_session.is_active is False

    async def test_sign_out__user_session_not_found__ok(
        self,
        client: PodcastTestClient,
        user: User,
    ):
        await client.login(user)
        response = client.delete(self.url)
        assert response.status_code == 200

    async def test_sign_out__another_session_exists__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        user_session: UserSession,
    ):
        another_user_session = user_session
        current_user_session = await client.login(user)

        response = client.delete(self.url)
        assert response.status_code == 200

        # current login
        current_user_session = await UserSession.async_get(dbs, id=current_user_session.id)
        assert current_user_session.is_active is False

        # user's login from another browser / device
        another_user_session = await UserSession.async_get(dbs, id=another_user_session.id)
        assert another_user_session.is_active


class TestUserInviteApiView(BaseTestAPIView):
    url = "/api/auth/invite-user/"
    default_fail_status_code = 400
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"

    async def test_invite__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_auth_send: AsyncMock,
    ):
        await client.login(user)
        response = client.post(self.url, json={"email": self.email})
        response_data = self.assert_ok_response(response, status_code=201)

        user_invite: UserInvite = await UserInvite.async_get(dbs, email=self.email)
        assert user_invite is not None
        assert response_data == {
            "id": user_invite.id,
            "token": user_invite.token,
            "email": user_invite.email,
            "owner_id": user.id,
            "created_at": user_invite.created_at.isoformat(),
            "expired_at": user_invite.expired_at.isoformat(),
        }
        invite_data = {
            "token": user_invite.token,
            "email": user_invite.email,
        }
        invite_data = base64.urlsafe_b64encode(json.dumps(invite_data).encode()).decode()
        link = f"{settings.SITE_URL}/sign-up/?i={invite_data}"
        expected_body = (
            f"<p>Hello! :) You have been invited to {settings.SITE_URL}</p>"
            f"<p>Please follow the link </p>"
            f"<p><a href={link}>{link}</a></p>"
        )
        mocked_auth_send.assert_awaited_once_with(
            recipient_email=self.email,
            subject=f"Welcome to {settings.SITE_URL}",
            html_content=expected_body,
        )

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_INVITE_DATA)
    async def test_invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    async def test_invite__unauth__fail(self, client: PodcastTestClient):
        client.logout()
        self.assert_unauth(client.post(self.url, json={"email": self.email}))

    async def test_invite__user_already_exists__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        response = client.post(self.url, json={"email": user.email})

        response_data = self.assert_fail_response(response)
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": f"User with email=[{user.email}] already exists.",
        }

    async def test_invite__user_already_invited__update_invite__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_auth_send: AsyncMock,
    ):
        old_token = UserInvite.generate_token()
        old_expired_at = datetime.utcnow()
        user_invite = await UserInvite.async_create(
            dbs,
            email=self.email,
            token=old_token,
            expired_at=old_expired_at,
            owner_id=user.id,
            db_commit=True,
        )

        await client.login(user)
        client.post(self.url, json={"email": self.email})

        dbs.expunge(user_invite)  # for refreshing instance
        updated_user_invite: UserInvite = await UserInvite.async_get(dbs, email=self.email)

        assert updated_user_invite is not None
        assert updated_user_invite.id == user_invite.id
        assert updated_user_invite.owner_id == user.id
        assert updated_user_invite.token != old_token
        assert updated_user_invite.expired_at > old_expired_at

        mocked_auth_send.assert_awaited_once()
        _, call_kwargs = mocked_auth_send.call_args_list[0]
        assert call_kwargs["recipient_email"] == self.email


class TestResetPasswordAPIView(BaseTestAPIView):
    url = "/api/auth/reset-password/"

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"

    async def test_reset_password__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_auth_send: AsyncMock,
    ):
        request_user = user
        await request_user.update(dbs, is_superuser=True)
        target_user = await User.async_create(
            dbs, db_commit=True, email=self.email, password="pass"
        )

        await client.login(user)
        response = client.post(self.url, json={"email": target_user.email})
        response_data = self.assert_ok_response(response)
        token = response_data.get("token")

        assert response_data["user_id"] == target_user.id
        assert token is not None, response_data
        assert decode_jwt(response_data["token"])["user_id"] == target_user.id

        link = f"{settings.SITE_URL}/change-password/?t={token}"
        expected_body = (
            f"<p>You can reset your password for {settings.SITE_URL}</p>"
            f"<p>Please follow the link </p>"
            f"<p><a href={link}>{link}</a></p>"
        )
        mocked_auth_send.assert_awaited_once_with(
            recipient_email=target_user.email,
            subject=f"Welcome back to {settings.SITE_URL}",
            html_content=expected_body,
        )

    async def test_reset_password__unauth__fail(self, client: PodcastTestClient):
        client.logout()
        self.assert_unauth(client.post(self.url, json={"email": self.email}))

    async def test_reset_password__user_not_found__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_auth_send: AsyncMock,
    ):
        request_user = user
        await request_user.update(dbs, is_superuser=True, db_commit=True)

        await client.login(request_user)
        response = client.post(self.url, json={"email": "fake-email@test.com"})
        response_data = self.assert_fail_response(
            response, status_code=400, response_status=ResponseStatus.INVALID_PARAMETERS
        )
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": "User with email=[fake-email@test.com] not found.",
        }

    async def test_reset_password__user_is_not_superuser__fail(
        self,
        client: PodcastTestClient,
        user: User,
    ):
        await client.login(user)
        response = client.post(self.url, json={"email": user.email})
        response_data = self.assert_fail_response(
            response, status_code=403, response_status=ResponseStatus.FORBIDDEN
        )
        assert response_data == {
            "error": "You don't have permission to perform this action.",
            "details": "You don't have an admin privileges.",
        }


class TestRefreshTokenAPIView(BaseTestAPIView):
    url = "/api/auth/refresh-token/"

    INVALID_REFRESH_TOKEN_DATA = [
        [{}, {"refresh_token": "Missing data for required field."}],
        [{"refresh_token": ""}, {"refresh_token": "Length must be between 10 and 512."}],
    ]

    @staticmethod
    async def _prepare_token(
        dbs: AsyncSession,
        user: User,
        is_active: bool = True,
        refresh: bool = True,
    ) -> UserSession:
        token_type = TOKEN_TYPE_REFRESH if refresh else TOKEN_TYPE_ACCESS
        session_id = str(uuid.uuid4())
        refresh_token, _ = encode_jwt(
            {"user_id": user.id, "session_id": session_id}, token_type=token_type
        )
        user_session = await UserSession.async_create(
            dbs,
            db_commit=True,
            user_id=user.id,
            is_active=is_active,
            public_id=session_id,
            refresh_token=refresh_token,
            expired_at=datetime.utcnow(),
        )
        return user_session

    async def test_refresh_token__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        user_session = await self._prepare_token(dbs, user)
        client.logout()
        response = client.post(self.url, json={"refresh_token": user_session.refresh_token})
        response_data = self.assert_ok_response(response)
        assert_tokens(response_data, user)

    async def test_refresh_token__several_sessions_for_user__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        user_session_1 = await self._prepare_token(dbs, user)
        user_session_2 = await self._prepare_token(dbs, user)
        client.logout()
        response = client.post(self.url, json={"refresh_token": user_session_2.refresh_token})
        response_data = self.assert_ok_response(response)
        assert_tokens(response_data, user, session_id=user_session_2.public_id)

        upd_user_session_1: UserSession = await UserSession.async_get(dbs, id=user_session_1.id)
        upd_user_session_2: UserSession = await UserSession.async_get(dbs, id=user_session_2.id)

        assert user_session_1.refreshed_at == upd_user_session_1.refreshed_at
        assert user_session_1.refresh_token == upd_user_session_1.refresh_token
        assert user_session_1.refreshed_at < upd_user_session_2.refreshed_at

    async def test_refresh_token__user_inactive__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        user_session = await self._prepare_token(dbs, user)
        await user.update(dbs, is_active=False, db_commit=True)

        response = client.post(self.url, json={"refresh_token": user_session.refresh_token})
        self.assert_auth_invalid(response, f"Couldn't found active user with id={user.id}.")

    async def test_refresh_token__session_inactive__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        session = await self._prepare_token(dbs, user, is_active=False)
        response = client.post(self.url, json={"refresh_token": session.refresh_token})
        expected_msg = (
            f"Couldn't found active session: user_id={user.id} | session_id='{session.public_id}'."
        )
        self.assert_auth_invalid(response, expected_msg)

    @pytest.mark.parametrize("token_type", [TOKEN_TYPE_ACCESS, TOKEN_TYPE_RESET_PASSWORD])
    async def test_refresh_token__token_not_refresh__fail(
        self,
        client: PodcastTestClient,
        user: User,
        token_type: str,
    ):
        refresh_token, _ = encode_jwt({"user_id": user.id}, token_type=token_type)
        response = client.post(self.url, json={"refresh_token": refresh_token})
        response_data = self.assert_fail_response(
            response, status_code=401, response_status=ResponseStatus.AUTH_FAILED
        )
        assert response_data == {
            "error": "Authentication credentials are invalid.",
            "details": f"Token type 'refresh' expected, got '{token_type}' instead.",
        }

    async def test_refresh_token__token_mismatch__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        user_session = await self._prepare_token(dbs, user, is_active=True)
        refresh_token = user_session.refresh_token
        await user_session.update(dbs, refresh_token="fake-token", db_commit=True)

        response = client.post(self.url, json={"refresh_token": refresh_token})
        self.assert_auth_invalid(
            response, "Refresh token does not match with user session.", ResponseStatus.AUTH_FAILED
        )

    async def test_refresh_token__fake_jwt__fail(self, client: PodcastTestClient, user: User):
        response = client.post(self.url, json={"refresh_token": "fake-jwt-token"})
        self.assert_auth_invalid(response, "Token could not be decoded: Not enough segments")

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_REFRESH_TOKEN_DATA)
    async def test_invalid_request__fail(
        self,
        client: PodcastTestClient,
        invalid_data: dict,
        error_details: dict,
    ):
        client.logout()
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)


class TestUserIPRegistration(BaseTestAPIView):
    IP = "172.17.0.1"
    HASHED_IP = hash_string(IP)

    def _request(self, user: User, ip_address: str = IP) -> PRequest:
        dbs = self.client.db_session
        request = prepare_request(dbs, headers={"X-Real-IP": ip_address})
        request.scope["user"] = user
        return request

    async def test_register_success(self, client: PodcastTestClient, user: User):
        self.client = client
        request = self._request(user=user)
        await register_ip(request)
        user_ip = await UserIP.async_get(
            client.db_session, user_id=user.id, hashed_address=self.HASHED_IP
        )
        assert user_ip is not None

    async def test_register_ip_already_exists(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        self.client = client
        old_user_ip = await UserIP.async_create(
            dbs, user_id=user.id, hashed_address=self.HASHED_IP, db_commit=True
        )

        request = self._request(user=user, ip_address=self.IP)
        await register_ip(request)

        new_user_ip = await UserIP.async_get(dbs, user_id=user.id, hashed_address=self.HASHED_IP)
        assert new_user_ip is not None
        assert new_user_ip.id == old_user_ip.id

    async def test_register_ip_several_requests(
        self,
        client: PodcastTestClient,
        user: User,
        user_session: UserSession,
    ):
        self.client = client
        # TODO: fix tests
        request_1 = self._request(user=user, ip_address="172.17.0.1")
        request_2 = self._request(user=user, ip_address="172.17.0.2")
        await register_ip(request_1)
        await register_ip(request_2)

        user_ips = await UserIP.async_filter(client.db_session, user_id=user.id)
        actual_ips = [user_ip.ip_address for user_ip in user_ips]
        assert actual_ips == ["172.17.0.2", "172.17.0.1"]

    async def test_register_missed_ip_header(self, dbs: AsyncSession, user: User):
        request = prepare_request(dbs, headers={"WRONG-X-Real-IP": "172.17.0.1"})
        request.scope["user"] = user
        await register_ip(request)

        user_ip = await UserIP.async_get(dbs, user_id=user.id, ip_address="172.17.0.1")
        assert user_ip is None

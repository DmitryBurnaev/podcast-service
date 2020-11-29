import uuid
from datetime import datetime, timedelta

import pytest
from requests import Response

from core import settings
from modules.auth.models import User, UserSession, UserInvite
from modules.auth.utils import decode_jwt
from modules.podcast.models import Podcast
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.helpers import async_run

INVALID_SIGN_IN_DATA = [
    [{"email": "fake-email"}, {"email": "Not a valid email address."}],
    [{"password": ""}, {"password": "Length must be between 2 and 32."}],
    [{}, {
        'email': 'Missing data for required field.',
        'password': 'Missing data for required field.'
    }],
]

INVALID_SIGN_UP_DATA = [
    [
        {},
        {
            'email': 'Missing data for required field.',
            'password_1': 'Missing data for required field.',
            'password_2': 'Missing data for required field.',
            'invite_token': 'Missing data for required field.',
        }
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
            "password_1": "Head",
            "password_2": "Foo"
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
    [{}, {'email': 'Missing data for required field.'}]
]


def assert_tokens(response: Response, user: User):
    """ Allows to check access- and refresh-tokens in the response body """

    access_token = response.json().get("access_token")
    refresh_token = response.json().get("refresh_token")
    assert access_token, f"No access_token in response: {response.json()}"
    assert refresh_token, f"No refresh_token in response: {response.json()}"

    decoded_access_token = decode_jwt(access_token)
    access_exp_dt = datetime.fromisoformat(decoded_access_token.pop("exp_iso"))
    assert access_exp_dt > datetime.utcnow()
    assert decoded_access_token.get("user_id") == user.id, decoded_access_token
    assert decoded_access_token.get("token_type") == 'access', decoded_access_token

    decoded_refresh_token = decode_jwt(refresh_token)
    refresh_exp_dt = datetime.fromisoformat(decoded_refresh_token.pop("exp_iso"))
    assert refresh_exp_dt > datetime.utcnow()
    assert decoded_refresh_token.get("user_id") == user.id, decoded_refresh_token
    assert decoded_refresh_token.get("token_type") == 'refresh', decoded_refresh_token

    assert refresh_exp_dt > access_exp_dt


class TestAuthMeAPIView(BaseTestAPIView):
    url = "/api/auth/me/"

    def test_get__ok(self, client, user):
        client.login(user)
        response = client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'id': user.id,
            'email': user.email,
            'is_active': True,
            'is_superuser': user.is_superuser
        }


class TestAuthSignInAPIView(BaseTestAPIView):
    url = "/api/auth/sign-in/"
    raw_password = "test-password"

    @classmethod
    def setup_class(cls):
        cls.encoded_password = User.make_password(cls.raw_password)

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"
        self.user = self.async_run(User.create(email=self.email, password=self.encoded_password))

    def test_sign_in__ok(self, client):
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        assert response.status_code == 200
        assert_tokens(response, self.user)

    def test_sign_in__check_user_session__ok(self, client):
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        assert response.status_code == 200

        refresh_token = response.json().get("refresh_token")
        decoded_refresh_token = decode_jwt(refresh_token)
        refresh_exp_dt = datetime.fromisoformat(decoded_refresh_token.pop("exp_iso"))

        user_session: UserSession = self.async_run(UserSession.async_get(user_id=self.user.id))
        assert user_session.refresh_token == refresh_token
        assert user_session.is_active is True
        assert user_session.expired_at == refresh_exp_dt
        assert user_session.last_login is not None

    def test_sign_in__update_user_session__ok(self, client):
        old_expired_at = datetime.now() + timedelta(seconds=1)
        user_session = self.async_run(
            UserSession.create(
                user_id=self.user.id,
                is_active=False,
                refresh_token="refresh_token",
                expired_at=old_expired_at
            )
        )
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        assert response.status_code == 200
        refresh_token = response.json().get("refresh_token")

        user_session: UserSession = self.async_run(UserSession.async_get(id=user_session.id))
        assert user_session.refresh_token == refresh_token
        assert user_session.user_id == self.user.id
        assert user_session.expired_at > old_expired_at
        assert user_session.is_active is True

    def test_sign_in__user_not_found__fail(self, client):
        response = client.post(self.url, json={"email": "fake@t.ru", "password": self.raw_password})
        assert response.status_code == 401
        assert response.json() == {
            'error': 'Authentication credentials are invalid',
            'details': 'Not found active user with provided email.'
        }

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_SIGN_IN_DATA)
    def test_sign_in__invalid_request__fail(self, client, invalid_data: dict, error_details: dict):
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    def test_sign_in__user_inactive__fail(self, client):
        self.async_run(self.user.update(is_active=False).apply())
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        assert response.status_code == 401
        assert response.json() == {
            'error': 'Authentication credentials are invalid',
            'details': 'Not found active user with provided email.'
        }


class TestAuthSignUPAPIView(BaseTestAPIView):
    url = "/api/auth/sign-up/"

    @staticmethod
    def _sign_up_data(user_invite: UserInvite):
        return {
            "email": user_invite.email,
            "invite_token": user_invite.token,
            "password_1": "test-password",
            "password_2": "test-password",
        }

    def test_sign_up__ok(self, client, user_invite):
        request_data = self._sign_up_data(user_invite)
        response = client.post(self.url, json=request_data)
        assert response.status_code == 201

        user = self.async_run(User.async_get(email=request_data["email"]))
        assert user is not None, f"User wasn't created with {request_data=}"
        assert_tokens(response, user)

        user_invite = self.async_run(UserInvite.async_get(id=user_invite.id))
        assert user_invite.user_id == user.id
        assert user_invite.is_applied

        assert self.async_run(Podcast.async_get(created_by_id=user.id)) is not None

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_SIGN_UP_DATA)
    def test_sign_up__invalid_request__fail(self, client, invalid_data: dict, error_details: dict):
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    def test_sign_up__user_already_exists__fail(self, client, user_invite):
        request_data = self._sign_up_data(user_invite)
        user_email = request_data["email"]

        self.async_run(User.create(email=user_email, password="password"))
        response = client.post(self.url, json=request_data)

        assert response.status_code == 400
        assert response.json() == {
            "error": "Requested data is not valid.",
            "details": f"User with email '{user_email}' already exists"
        }

    @pytest.mark.parametrize("token_update_data", [
        {"token": f"outdated-token-{uuid.uuid4().hex[:10]}"},
        {"expired_at": datetime.utcnow() - timedelta(hours=1)},
        {"is_applied": True}
    ])
    def test_sign_up__token_problems__fail(self, client, user_invite, token_update_data):
        request_data = self._sign_up_data(user_invite)
        self.async_run(user_invite.update(**token_update_data).apply())
        response = client.post(self.url, json=request_data)

        assert response.status_code == 400
        assert response.json() == {
            "error": "Requested data is not valid.",
            "details": "Invitation link is expired or unavailable"
        }

    def test_sign_up__email_mismatch_with_token__fail(self, client, user_invite):
        request_data = self._sign_up_data(user_invite)
        request_data["email"] = f"another.email{uuid.uuid4().hex[:10]}@test.com"
        response = client.post(self.url, json=request_data)

        assert response.status_code == 400
        assert response.json() == {
            "error": "Requested data is not valid.",
            "details": "Email does not match with your invitation."
        }


class TestSignOutAPIView(BaseTestAPIView):
    url = "/api/auth/sign-out/"

    def test_sign_out__ok(self, client, user):
        user_session = self.async_run(
            UserSession.create(
                user_id=user.id,
                refresh_token="refresh_token",
                expired_at=datetime.now() + timedelta(hours=1)
            )
        )
        client.login(user)
        response = client.get(self.url)
        assert response.status_code == 204

        user_session = self.async_run(UserSession.async_get(id=user_session.id))
        assert user_session.is_active is False

    def test_sign_out__user_session_not_found__ok(self, client, user):
        client.login(user)
        response = client.get(self.url)
        assert response.status_code == 204


class TestUserInviteApiView(BaseTestAPIView):
    url = "/api/auth/invite-user/"

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"

    def test_invite__ok(self, client, user, mocked_auth_send):
        client.login(user)
        response = client.post(self.url, json={"email": self.email})
        assert response.status_code == 201

        user_invite: UserInvite = async_run(UserInvite.async_get(email=self.email))
        assert user_invite is not None
        assert response.json() == {
            "id": user_invite.id,
            "token": user_invite.token,
            "email": user_invite.email,
            "created_by_id": user.id,
            "created_at": user_invite.created_at.isoformat(),
            "expired_at": user_invite.expired_at.isoformat(),
        }

        link = f"{settings.SITE_URL}/sign-up/?t={user_invite.token}"
        expected_body = (
            f"<p>Hello! :) You have been invited to {settings.SITE_URL}</p>"
            f"<p>Please follow the link </p>"
            f"<p><a href={link}>{link}</a></p>"
        )
        mocked_auth_send.assert_called_once_with(
            recipient_email=self.email,
            subject=f"Welcome to {settings.SITE_URL}",
            html_content=expected_body,
        )

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_INVITE_DATA)
    def test_invite__invalid_request__fail(self, client, user, invalid_data: dict, error_details: dict):
        client.login(user)
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    def test_invite__unauth__fail(self, client):
        client.logout()
        self.assert_unauth(client.post(self.url, json={"email": self.email}))

    def test_invite__user_already_exists__fail(self, client, user):
        client.login(user)
        response = client.post(self.url, json={"email": user.email})
        assert response.status_code == 400
        assert response.json() == {
            "error": "Requested data is not valid.",
            "details": f"User with email=[{user.email}] already exists."
        }

    def test_invite__invite_already_exist__updated__ok(self, client, user, mocked_auth_send):
        old_token = UserInvite.generate_token()
        old_expired_at = datetime.utcnow()
        user_invite = async_run(
            UserInvite.create(
                email=self.email, token=old_token, expired_at=old_expired_at, created_by_id=user.id,
            )
        )

        client.login(user)
        client.post(self.url, json={"email": self.email})
        updated_user_invite: UserInvite = async_run(UserInvite.async_get(email=self.email))

        assert updated_user_invite is not None
        assert updated_user_invite.id == user_invite.id
        assert updated_user_invite.token != user_invite.token
        assert updated_user_invite.expired_at != user_invite.expired_at
        assert mocked_auth_send.called
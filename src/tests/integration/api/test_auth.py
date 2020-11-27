import uuid
from datetime import datetime, timedelta

import pytest
from requests import Response

from modules.auth.models import User, UserSession, UserInvite
from modules.auth.utils import decode_jwt
from tests.integration.api.test_base import BaseTestAPIView

INVALID_SIGN_IN_DATA = [
    [{"email": "fake-email"}, {"email": "Not a valid email address."}],
    [{"password": ""}, {"password": "Length must be between 2 and 32."}],
    [{}, {
        'email': 'Missing data for required field.',
        'password': 'Missing data for required field.'
    }],
]

INVALID_SIGN_UP_DATA = [
    [{}, {
        'email': 'Missing data for required field.',
        'password_1': 'Missing data for required field.',
        'password_2': 'Missing data for required field.',
        'invite_token': 'Missing data for required field.',
    }],
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


class TestAuthSignInAPIView(BaseTestAPIView):
    url = "/api/auth/sign-in/"
    raw_password = "test-password"

    @classmethod
    def setup_class(cls):
        cls.encoded_password = User.make_password(cls.raw_password)

    def setup_method(self):
        self.email = f"user_{uuid.uuid4().hex[:10]}@test.com"

    def test_sign_in__ok(self, client):
        user = self.async_run(User.create(email=self.email, password=self.encoded_password))
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})

        assert response.status_code == 200
        assert_tokens(response, user)

    def test_sign_in__check_user_session__ok(self, client):
        user = self.async_run(User.create(email=self.email, password=self.encoded_password))
        response = client.post(self.url, json={"email": self.email, "password": self.raw_password})
        assert response.status_code == 200

        refresh_token = response.json().get("refresh_token")
        decoded_refresh_token = decode_jwt(refresh_token)
        refresh_exp_dt = datetime.fromisoformat(decoded_refresh_token.pop("exp_iso"))

        user_session: UserSession = self.async_run(UserSession.async_get(user_id=user.id))
        assert user_session.refresh_token == refresh_token
        assert user_session.is_active is True
        assert user_session.expired_at == refresh_exp_dt
        assert user_session.last_login is not None

    def test_sign_in__user_not_found__fail(self, client):
        response = client.post(self.url, json={"email": "fake@t.ru", "password": self.raw_password})
        assert response.status_code == 401
        assert response.json() == {
            'error': 'Authentication credentials are invalid',
            'details': 'Not found user with provided email.'
        }

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_SIGN_IN_DATA)
    def test_sign_in__invalid_request__fail(self, client, invalid_data: dict, error_details: dict):
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)


class TestAuthSignUPAPIView(BaseTestAPIView):
    url = "/api/auth/sign-up/"

    def _sign_up_data(self, user_invite: UserInvite):
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
        self.async_run(
            UserInvite.async_update(
                filter_kwargs={"id": user_invite.id},
                update_data=token_update_data
            )
        )
        request_data = self._sign_up_data(user_invite)
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

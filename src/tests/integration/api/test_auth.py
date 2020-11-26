import uuid
from datetime import datetime

from modules.auth.models import User, UserSession
from modules.auth.utils import decode_jwt
from tests.integration.api.test_base import BaseTestAPIView

INVALID_SIGN_IN_DATA = [
    [{"email": "fake-email"}, {"name": "Length must be between 1 and 256."}],
    [{"password": ""}, {"name": "Length must be between 1 and 256."}],
    [{}, {"description": "Not a valid string."}],
]

INVALID_SIGN_UP_DATA = [
    [
        {
            "email": ("fake_user_" * 30 + "@t.com"),
            "password_1": "123456",
            "password_2": "123456",
            "token": "t",
        },
        {"email": ["max length is 128"]},
    ],
    [
        {"email": "", "password_1": "123456", "password_2": "123456", "token": "t"},
        {"email": ["empty values not allowed"]},
    ],
    [
        {"email": "f@t.com", "password_1": "123456", "token": "t"},
        {"password_2": ["required field"]},
    ],
    [
        {"email": "f@t.com", "password_1": "header", "password_2": "footer"},
        {"token": ["required field"]},
    ],
    [
        {"email": "f@t.com", "password_1": "header", "password_2": "footer", "token": "t"},
        {"password_1": "Passwords must be equal", "password_2": "Passwords must be equal"},
    ],
    [
        {"email": "f@t.com", "password_1": "header", "password_2": "footer", "token": ""},
        {"token": ["empty values not allowed"]},
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

    def test_sign_in_check_user_session__ok(self, client):
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

import pytest

from common.statuses import ResponseStatus
from modules.auth.utils import encode_jwt, TOKEN_TYPE_RESET_PASSWORD, TOKEN_TYPE_REFRESH
from tests.api.test_auth import INVALID_CHANGE_PASSWORD_DATA
from tests.api.test_base import BaseTestAPIView
from tests.helpers import await_


class TestProfileAPIView(BaseTestAPIView):
    url = "/api/auth/me/"

    def test_get__ok(self, client, user):
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": user.email,
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

    def test_patch__ok(self, dbs, client, user):
        client.login(user)
        response = client.patch(self.url, json={"email": "new-user@test.com"})
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": "new-user@test.com",
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

        await_(dbs.refresh(user))
        assert user.email == "new-user@test.com"


class TestChangePasswordAPIView(BaseTestAPIView):
    url = "/api/auth/change-password/"
    new_password = "new123456"

    def _assert_fail_response(self, client, token: str, response_status: str = None) -> dict:
        request_data = {
            "token": token,
            "password_1": self.new_password,
            "password_2": self.new_password,
        }
        client.logout()
        response = client.post(self.url, json=request_data)
        assert response.status_code == 401
        response_data = response.json()
        if response_status:
            assert response_data["status"] == response_status
        return response.json()["payload"]

    def test_change_password__ok(self, client, user, user_session, dbs):
        token, _ = encode_jwt({"user_id": user.id}, token_type=TOKEN_TYPE_RESET_PASSWORD)
        request_data = {
            "token": token,
            "password_1": self.new_password,
            "password_2": self.new_password,
        }
        client.logout()
        response = client.post(self.url, json=request_data)
        response_data = self.assert_ok_response(response)
        assert response_data == {}

        await_(dbs.refresh(user))
        await_(dbs.refresh(user_session))
        assert user.verify_password(self.new_password)
        assert not user_session.is_active

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CHANGE_PASSWORD_DATA)
    def test_invalid_request__fail(self, client, invalid_data: dict, error_details: dict):
        client.logout()
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    def test__token_expired__fail(self, client, user):
        token, _ = encode_jwt({"user_id": user.id}, expires_in=-10)
        response_data = self._assert_fail_response(client, token, ResponseStatus.AUTH_FAILED)
        self.assert_auth_invalid(response_data, "JWT signature has been expired for token")

    def test__token_invalid_type__fail(self, client, user):
        token, _ = encode_jwt({"user_id": user.id}, token_type=TOKEN_TYPE_REFRESH)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(
            response_data, "Token type 'reset_password' expected, got 'refresh' instead."
        )

    def test_token_invalid__fail(self, client, user):
        response_data = self._assert_fail_response(client, "fake-jwt")
        self.assert_auth_invalid(response_data, "Token could not be decoded: Not enough segments")

    def test_user_inactive__fail(self, client, user, dbs):
        await_(user.update(dbs, is_active=False))
        await_(dbs.commit())
        token, _ = encode_jwt({"user_id": user.id}, token_type=TOKEN_TYPE_RESET_PASSWORD)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(response_data, f"Couldn't found active user with id={user.id}.")

    def test_user_does_not_exist__fail(self, client, user):
        user_id = 0
        token, _ = encode_jwt({"user_id": user_id}, token_type=TOKEN_TYPE_RESET_PASSWORD)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(response_data, f"Couldn't found active user with id={user_id}.")

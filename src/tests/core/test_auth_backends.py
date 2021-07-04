import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from common.exceptions import (
    AuthenticationRequiredError,
    AuthenticationFailedError,
    PermissionDeniedError,
)
from modules.auth.backend import BaseAuthJWTBackend, AdminRequiredAuthBackend
from modules.auth.models import User
from modules.auth.utils import encode_jwt, TOKEN_TYPE_RESET_PASSWORD, TOKEN_TYPE_REFRESH
from tests.helpers import async_run


class TestBackendAuth:
    @staticmethod
    def _prepare_request(user: User, db_session: AsyncSession):
        jwt, _ = encode_jwt({"user_id": user.id})
        scope = {"type": "http", "headers": [(b"authorization", f"Bearer {jwt}".encode("latin-1"))]}
        request = Request(scope)
        request.db_session = db_session
        return request

    def test_check_auth__ok(self, client, user, user_session, db_session):
        request = self._prepare_request(user, db_session)
        authenticated_user, _ = async_run(BaseAuthJWTBackend(request).authenticate())
        assert authenticated_user.id == user.id

    @pytest.mark.parametrize(
        "auth_header, auth_exception, err_details",
        [
            (
                (b"auth", "JWT"),
                AuthenticationRequiredError,
                "Invalid token header. No credentials provided.",
            ),
            (
                (b"authorization", b"JWT"),
                AuthenticationFailedError,
                "Invalid token header. Token should be format as JWT.",
            ),
            (
                (b"authorization", b"FakeKeyword JWT"),
                AuthenticationFailedError,
                "Invalid token header. Keyword mismatch.",
            ),
            (
                (b"authorization", b"Bearer fake-jwt-token"),
                AuthenticationFailedError,
                "Token could not be decoded: Not enough segments",
            ),
        ],
    )
    def test_invalid_token__fail(self, client, user, auth_header, auth_exception, err_details):
        request = Request(scope={"type": "http", "headers": [auth_header]})
        with pytest.raises(auth_exception) as err:
            async_run(BaseAuthJWTBackend(request).authenticate())

        assert err.value.details == err_details

    def test_check_auth__user_not_active__fail(self, client, user, db_session):
        async_run(user.update(is_active=False).apply())
        request = self._prepare_request(user, db_session)
        with pytest.raises(AuthenticationFailedError) as err:
            async_run(BaseAuthJWTBackend(request).authenticate())

        assert err.value.details == f"Couldn't found active user with id={user.id}."

    def test_check_auth__session_not_active__fail(self, client, user, user_session, db_session):
        async_run(user_session.update(is_active=False).apply())
        request = self._prepare_request(user, db_session)
        with pytest.raises(AuthenticationFailedError) as err:
            async_run(BaseAuthJWTBackend(request).authenticate())

        assert err.value.details == f"Couldn't found active session for user #{user.id}."

    @pytest.mark.parametrize("token_type", [TOKEN_TYPE_REFRESH, TOKEN_TYPE_RESET_PASSWORD])
    def test_check_auth__token_type_mismatch__fail(
        self, client, user, user_session, token_type, db_session
    ):
        async_run(user_session.update(is_active=False).apply())
        token, _ = encode_jwt({"user_id": user.id}, token_type=token_type)
        request = self._prepare_request(user, db_session)
        with pytest.raises(AuthenticationFailedError) as err:
            async_run(BaseAuthJWTBackend(request).authenticate_user(token, token_type="access"))

        assert err.value.details == f"Token type 'access' expected, got '{token_type}' instead."

    def test_check_auth__admin_required__ok(self, client, user, user_session, db_session):
        async_run(user.update(is_superuser=True).apply())
        request = self._prepare_request(user, db_session)
        authenticated_user, _ = async_run(AdminRequiredAuthBackend(request).authenticate())
        assert authenticated_user.id == user.id

    def test_check_auth__admin_required__not_superuser__fail(
        self, client, user, user_session, db_session
    ):
        async_run(user.update(is_superuser=False).apply())
        request = self._prepare_request(user, db_session)
        with pytest.raises(PermissionDeniedError) as err:
            async_run(AdminRequiredAuthBackend(request).authenticate())

        assert err.value.details == "You don't have an admin privileges."

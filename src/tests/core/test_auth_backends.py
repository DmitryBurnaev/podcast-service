import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from common.exceptions import (
    AuthenticationRequiredError,
    AuthenticationFailedError,
    PermissionDeniedError,
)
from modules.auth.backend import BaseAuthJWTBackend, AdminRequiredAuthBackend
from modules.auth.models import User, UserSession
from modules.auth.utils import encode_jwt, TOKEN_TYPE_RESET_PASSWORD, TOKEN_TYPE_REFRESH
from tests.helpers import prepare_request

pytestmark = pytest.mark.asyncio


class TestBackendAuth:
    @staticmethod
    def _prepare_request(dbs: AsyncSession, user: User, user_session: UserSession) -> Request:
        jwt, _ = encode_jwt({"user_id": user.id, "session_id": user_session.public_id})
        return prepare_request(dbs, headers={"authorization": f"Bearer {jwt}"})

    async def test_check_auth__ok(self, user, user_session, dbs):
        request = self._prepare_request(dbs, user, user_session)
        authenticated_user, _ = await BaseAuthJWTBackend(request).authenticate()
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
    async def test_invalid_token__fail(self, auth_header, auth_exception, err_details, dbs):
        request = Request(scope={"type": "http", "headers": [auth_header]})
        request.db_session = dbs
        with pytest.raises(auth_exception) as exc:
            await BaseAuthJWTBackend(request).authenticate()

        assert exc.value.details == err_details

    async def test_check_auth__user_not_active__fail(self, user, user_session, dbs):
        await user.update(dbs, is_active=False, db_commit=True)
        request = self._prepare_request(dbs, user, user_session)
        with pytest.raises(AuthenticationFailedError) as exc:
            await BaseAuthJWTBackend(request).authenticate()

        assert exc.value.details == f"Couldn't found active user with id={user.id}."

    async def test_check_auth__session_not_active__fail(self, user, user_session, dbs):
        await user_session.update(dbs, is_active=False, db_commit=True)
        request = self._prepare_request(dbs, user, user_session)
        with pytest.raises(AuthenticationFailedError) as exc:
            await BaseAuthJWTBackend(request).authenticate()

        assert exc.value.details == (
            f"Couldn't found active session: user_id={user.id} | "
            f"session_id='{user_session.public_id}'."
        )

    @pytest.mark.parametrize("token_type", [TOKEN_TYPE_REFRESH, TOKEN_TYPE_RESET_PASSWORD])
    async def test_check_auth__token_t_mismatch__fail(self, user, user_session, token_type, dbs):
        await user_session.update(dbs, is_active=False, db_commit=True)
        token, _ = encode_jwt({"user_id": user.id}, token_type=token_type)
        request = self._prepare_request(dbs, user, user_session)
        with pytest.raises(AuthenticationFailedError) as exc:
            await BaseAuthJWTBackend(request).authenticate_user(token, token_type="access")

        assert exc.value.details == f"Token type 'access' expected, got '{token_type}' instead."

    async def test_check_auth__admin_required__ok(self, user, user_session, dbs):
        await user.update(dbs, is_superuser=True, db_commit=True)
        request = self._prepare_request(dbs, user, user_session)
        authenticated_user, _ = await AdminRequiredAuthBackend(request).authenticate()
        assert authenticated_user.id == user.id

    async def test_check_auth__admin_required__not_superuser__fail(self, user, user_session, dbs):
        await user.update(dbs, is_superuser=False, db_commit=True)
        request = self._prepare_request(dbs, user, user_session)
        with pytest.raises(PermissionDeniedError) as exc:
            await AdminRequiredAuthBackend(request).authenticate()

        assert exc.value.details == "You don't have an admin privileges."

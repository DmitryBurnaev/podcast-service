import pytest
from starlette.requests import Request

from common.exceptions import (
    AuthenticationRequiredError,
    AuthenticationFailedError,
    PermissionDeniedError,
)
from modules.auth.backend import BaseAuthJWTBackend, AdminRequiredAuthBackend
from modules.auth.models import User
from modules.auth.utils import encode_jwt
from tests.helpers import async_run


class TestBackendAuth:

    @staticmethod
    def _prepare_request(user: User):
        jwt, _ = encode_jwt({'user_id': user.id})
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {jwt}".encode("latin-1"))]
        }
        return Request(scope)

    def test_check_auth__ok(self, client, user):
        request = self._prepare_request(user)
        authenticated_user = async_run(BaseAuthJWTBackend().authenticate(request))
        assert authenticated_user.id == user.id

    @pytest.mark.parametrize(
        "auth_header, auth_exception, err_details",
        [
            (
                (b"auth", "JWT"),
                AuthenticationRequiredError,
                "Invalid token header. No credentials provided."
            ),
            (
                (b"authorization", b"JWT"),
                AuthenticationFailedError,
                "Invalid token header. Token should be format as JWT."
            ),
            (
                (b"authorization", b"FakeKeyword JWT"),
                AuthenticationFailedError,
                "Invalid token header. Keyword mismatch."
            ),
            (
                (b"authorization", b"Bearer fake-jwt-token"),
                AuthenticationFailedError,
                "Token could not be decoded: Not enough segments"
            ),
        ]
    )
    def test_invalid_token__fail(self, client, user, auth_header, auth_exception, err_details):
        request = Request(scope={"type": "http", "headers": [auth_header]})
        with pytest.raises(auth_exception) as err:
            async_run(BaseAuthJWTBackend().authenticate(request))

        assert err.value.details == err_details

    def test_check_auth__user_not_active__fail(self, client, user):
        async_run(user.update(is_active=False).apply())
        request = self._prepare_request(user)
        with pytest.raises(AuthenticationFailedError) as err:
            async_run(BaseAuthJWTBackend().authenticate(request))

        assert err.value.details == f"Couldn't found active user with id={user.id}."

    def test_check_auth__admin_required__ok(self, client, user):
        async_run(user.update(is_superuser=True).apply())
        request = self._prepare_request(user)
        authenticated_user = async_run(AdminRequiredAuthBackend().authenticate(request))
        assert authenticated_user.id == user.id

    def test_check_auth__admin_required__not_superuser__fail(self, client, user):
        async_run(user.update(is_superuser=False).apply())
        request = self._prepare_request(user)
        with pytest.raises(PermissionDeniedError) as err:
            async_run(AdminRequiredAuthBackend().authenticate(request))

        assert err.value.details == "You don't have an admin privileges."

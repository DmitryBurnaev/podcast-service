import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.statuses import ResponseStatus
from common.utils import hash_string
from modules.auth.models import UserIP, User, UserSession
from modules.auth.utils import encode_jwt
from modules.auth.constants import AuthTokenType
from modules.media.models import File
from modules.podcast.models import Podcast
from tests.api.test_auth import INVALID_CHANGE_PASSWORD_DATA
from tests.api.test_base import BaseTestAPIView
from tests.helpers import PodcastTestClient

pytestmark = pytest.mark.asyncio


class TestProfileAPIView(BaseTestAPIView):
    url = "/api/auth/me/"

    async def test_get__ok(self, client: PodcastTestClient, user: User):
        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": user.email,
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

    async def test_patch__ok(self, dbs, client: PodcastTestClient, user: User):
        await client.login(user)
        response = client.patch(self.url, json={"email": "new-user@test.com"})
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": "new-user@test.com",
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

        await dbs.refresh(user)
        assert user.email == "new-user@test.com"


class TestChangePasswordAPIView(BaseTestAPIView):
    url = "/api/auth/change-password/"
    new_password = "new123456"

    def _assert_fail_response(
        self,
        client: PodcastTestClient,
        token: str,
        response_status: str | None = None,
    ) -> dict:
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

    async def test_change_password__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        user_session: UserSession,
    ):
        token, _ = encode_jwt({"user_id": user.id}, token_type=AuthTokenType.RESET_PASSWORD)
        request_data = {
            "token": token,
            "password_1": self.new_password,
            "password_2": self.new_password,
        }
        client.logout()
        response = client.post(self.url, json=request_data)
        response_data = self.assert_ok_response(response)
        assert response_data == {}

        await dbs.refresh(user)
        await dbs.refresh(user_session)
        assert user.verify_password(self.new_password)
        assert not user_session.is_active

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CHANGE_PASSWORD_DATA)
    async def test_invalid_request__fail(
        self,
        client: PodcastTestClient,
        invalid_data: dict,
        error_details: dict,
    ):
        client.logout()
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)

    async def test__token_expired__fail(self, client: PodcastTestClient, user: User):
        token, _ = encode_jwt({"user_id": user.id}, expires_in=-10)
        response_data = self._assert_fail_response(client, token, ResponseStatus.AUTH_FAILED)
        self.assert_auth_invalid(response_data, "JWT signature has been expired for token")

    async def test__token_invalid_type__fail(self, client: PodcastTestClient, user: User):
        token, _ = encode_jwt({"user_id": user.id}, token_type=AuthTokenType.REFRESH)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(
            response_data, "Token type 'reset_password' expected, got 'refresh' instead."
        )

    async def test_token_invalid__fail(self, client):
        response_data = self._assert_fail_response(client, "fake-jwt")
        self.assert_auth_invalid(response_data, "Token could not be decoded: Not enough segments")

    async def test_user_inactive__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        await user.update(dbs, is_active=False, db_commit=True)
        token, _ = encode_jwt({"user_id": user.id}, token_type=AuthTokenType.RESET_PASSWORD)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(response_data, f"Couldn't found active user with id={user.id}.")

    async def test_user_does_not_exist__fail(self, client: PodcastTestClient):
        user_id = 0
        token, _ = encode_jwt({"user_id": user_id}, token_type=AuthTokenType.RESET_PASSWORD)
        response_data = self._assert_fail_response(client, token)
        self.assert_auth_invalid(response_data, f"Couldn't found active user with id={user_id}.")


class TestUserIPsAPIView(BaseTestAPIView):
    url = "/api/auth/ips/"
    url_delete = "/api/auth/ips/delete/"

    @staticmethod
    async def _user_ip(dbs, user: User, address: str, registered_by: str = "") -> UserIP:
        ip_data = {
            "hashed_address": hash_string(address),
            "user_id": user.id,
            "registered_by": registered_by,
        }
        return await UserIP.async_create(dbs, **ip_data)

    @staticmethod
    def _ip_in_list(ip: UserIP, podcast: Podcast | None = None):
        podcast_details = {"id": podcast.id, "name": podcast.name} if podcast else None
        return {
            "id": ip.id,
            "hashed_address": ip.hashed_address,
            "by_rss_podcast": podcast_details,
            "created_at": ip.created_at.isoformat(),
        }

    @staticmethod
    async def _create_user(dbs, email: str) -> User:
        return await User.async_create(
            dbs,
            db_commit=True,
            email=email,
            password="password",
            is_active=True,
        )

    async def test_get_list_ips(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
        rss_file: File,
    ):
        user_1 = await self._create_user(dbs, email=f"test-user-1-{uuid.uuid4().hex[:10]}@test.com")
        user_2 = await self._create_user(dbs, email=f"test-user-2-{uuid.uuid4().hex[:10]}@test.com")
        await podcast.update(dbs, rss_id=rss_file.id)
        await dbs.refresh(user_1)
        await dbs.refresh(user_2)

        # login user's IPs
        user_1_ip_1 = await self._user_ip(dbs, user_1, "127.0.0.1")
        user_1_ip_2 = await self._user_ip(dbs, user_1, "192.168.1.10")
        user_1_ip_3_with_podcast = await self._user_ip(
            dbs, user_1, "192.168.1.10", registered_by=rss_file.access_token
        )
        # another user's IPs
        await self._user_ip(dbs, user_2, "192.168.1.10")
        await dbs.commit()

        await client.login(user_1)

        # default limit is settings.DEFAULT_PAGINATION_LIMIT
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [
            self._ip_in_list(user_1_ip_3_with_podcast, podcast),
            self._ip_in_list(user_1_ip_2),
            self._ip_in_list(user_1_ip_1),
        ]

        # limit query
        response = client.get(self.url, params={"limit": 1})
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [
            self._ip_in_list(user_1_ip_3_with_podcast, podcast),
        ]

        # limit and offset query
        response = client.get(self.url, params={"limit": 1, "offset": 1})
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [
            self._ip_in_list(user_1_ip_2),
        ]

    async def test_delete_ips(self, dbs: AsyncSession, client: PodcastTestClient, user_data: dict):
        user_1 = await self._create_user(dbs, email=f"test-user-1-{uuid.uuid4().hex[:10]}@test.com")
        user_2 = await self._create_user(dbs, email=f"test-user-2-{uuid.uuid4().hex[:10]}@test.com")
        await dbs.refresh(user_1)
        await dbs.refresh(user_2)

        user_ip_1 = await self._user_ip(dbs, user_1, "127.0.0.1")
        user_ip_2 = await self._user_ip(dbs, user_1, "192.168.1.10")
        user_ip_3 = await self._user_ip(dbs, user_2, "192.168.1.10")
        await dbs.commit()

        await client.login(user_1)
        response = client.post(self.url_delete, json={"ids": [user_ip_1.id, user_ip_2.id]})
        self.assert_ok_response(response)

        assert await UserIP.async_get(dbs, id=user_ip_3.id) is not None

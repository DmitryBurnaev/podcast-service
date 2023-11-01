import io

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.statuses import ResponseStatus
from modules.auth.models import User
from modules.podcast.models import Cookie, Episode
from common.enums import SourceType
from tests.api.test_base import BaseTestAPIView
from tests.helpers import create_user, create_file, PodcastTestClient
from tests.mocks import MockSensitiveData

INVALID_UPDATE_DATA = [
    [
        {"source_type": "FAKE-TYPE"},
        {"source_type": "Must be one of: YOUTUBE, YANDEX, UPLOAD."},
    ],
    [{"source_type": "YOUTUBE"}, {"file": "Missing data for required field."}],
]

INVALID_CREATE_DATA = [
    [
        {},
        {
            "source_type": "Missing data for required field.",
            "file": "Missing data for required field.",
        },
    ],
]
pytestmark = pytest.mark.asyncio


def _cookie(cookie):
    return {
        "id": cookie.id,
        "sourceType": cookie.source_type,
        "createdAt": cookie.created_at.isoformat(),
    }


def _cookie_file(text="Cookie at netscape format\n") -> io.BytesIO:
    return create_file(text)


class TestCookieListCreateAPIView(BaseTestAPIView):
    url = "/api/cookies/"

    async def test_get_list__ok(self, client: PodcastTestClient, cookie: Cookie, user: User):
        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_cookie(cookie)]

    async def test_get_list__unique_results__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        cd = {
            "data": "Cookie at netscape format\n",
            "owner_id": user.id,
        }
        await Cookie.async_create(dbs, source_type=SourceType.YANDEX, **cd)
        await Cookie.async_create(dbs, source_type=SourceType.YANDEX, **cd)
        await Cookie.async_create(dbs, source_type=SourceType.YOUTUBE, **cd)
        last_cookie_youtube = await Cookie.async_create(dbs, source_type=SourceType.YOUTUBE, **cd)
        last_cookie_yandex = await Cookie.async_create(dbs, source_type=SourceType.YANDEX, **cd)
        await dbs.commit()

        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [
            _cookie(last_cookie_youtube),
            _cookie(last_cookie_yandex),
        ]

    async def test_create__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_sens_data: MockSensitiveData,
    ):
        cookie_data = {"source_type": SourceType.YANDEX}
        cookie_text = "Cookie at netscape format\n"
        await client.login(user)
        response = client.post(
            self.url,
            data=cookie_data,
            files={"file": _cookie_file(cookie_text)},
        )
        response_data = self.assert_ok_response(response, status_code=201)
        cookie = await Cookie.async_get(dbs, id=response_data["id"])
        assert cookie is not None
        assert cookie.data == "encrypted_data"
        assert response_data == _cookie(cookie)
        mocked_sens_data.encrypt.assert_called_with(cookie_text)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    async def test_create__invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        self.assert_bad_request(client.post(self.url, data=invalid_data), error_details)


class TestCookieRUDAPIView(BaseTestAPIView):
    url = "/api/cookies/{id}/"

    async def test_get_detailed__ok(self, client: PodcastTestClient, cookie: Cookie, user: User):
        await client.login(user)
        url = self.url.format(id=cookie.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _cookie(cookie)

    async def test_get__cookie_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        cookie: Cookie,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=cookie.id)
        self.assert_not_found(client.get(url), cookie)

    async def test_update__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        cookie: Cookie,
        mocked_sens_data: MockSensitiveData,
    ):
        mocked_sens_data.encrypt.return_value = "updated_encrypted_data"
        await client.login(user)
        url = self.url.format(id=cookie.id)
        data = {"source_type": SourceType.YANDEX}
        response = client.put(url, data=data, files={"file": _cookie_file("updated cookie data")})
        await dbs.refresh(cookie)
        response_data = self.assert_ok_response(response)
        assert response_data == _cookie(cookie)
        assert cookie.data == "updated_encrypted_data"
        assert cookie.updated_at > cookie.created_at
        mocked_sens_data.encrypt.assert_called_with("updated cookie data")

    async def test_update__cookie_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        cookie: Cookie,
        mocked_sens_data: MockSensitiveData,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=cookie.id)
        data = {"source_type": SourceType.YANDEX}
        self.assert_not_found(client.put(url, data=data, files={"file": _cookie_file()}), cookie)
        mocked_sens_data.encrypt.assert_not_called()

    async def test_update__invalid_request__fail(
        self,
        client: PodcastTestClient,
        cookie: Cookie,
        user: User,
    ):
        await client.login(user)
        url = self.url.format(id=cookie.id)
        data = {"source_type": SourceType.YANDEX}
        self.assert_bad_request(
            client.put(url, data=data, files={}),
            {"file": "Missing data for required field."},
        )

    async def test_delete__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        cookie: Cookie,
        user: User,
    ):
        await client.login(user)
        url = self.url.format(id=cookie.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await Cookie.async_get(dbs, id=cookie.id) is None

    async def test_delete__cookie_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        cookie: Cookie,
        user: User,
    ):
        user_2 = await create_user(dbs)
        await client.login(user_2)
        url = self.url.format(id=cookie.id)
        self.assert_not_found(client.delete(url), cookie)

    async def test_delete__linked_episodes___fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode: Episode,
        cookie: Cookie,
        user: User,
    ):
        await episode.update(dbs, db_commit=True, cookie_id=cookie.id)
        await client.login(user)
        url = self.url.format(id=cookie.id)
        self.assert_fail_response(
            client.delete(url),
            status_code=403,
            response_status=ResponseStatus.FORBIDDEN,
        )

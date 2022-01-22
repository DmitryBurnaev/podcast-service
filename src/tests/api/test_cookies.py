import io

import pytest

from common.statuses import ResponseStatus
from modules.podcast.models import SourceType, Cookie
from tests.api.test_base import BaseTestAPIView
from tests.helpers import create_user, await_

INVALID_UPDATE_DATA = [
    [{"source_type": "FAKE-TYPE"}, {"source_type": "Length must be between 1 and 256."}],
    [{"file": None}, {"file": "Not a valid string."}],
    [{"file": "text"}, {"file": "Not a valid boolean."}],
]

INVALID_CREATE_DATA = INVALID_UPDATE_DATA + [
    [{}, {"source_type": "Missing data for required field."}],
]


def _cookie(cookie):
    return {
        "id": cookie.id,
        "source_type": cookie.source_type.value,
        "created_at": cookie.created_at.isoformat(),
        "updated_at": cookie.updated_at.isoformat(),
    }


def _file(text="Cookie at netscape format\n") -> io.BytesIO:
    return io.BytesIO(bytes(text.encode()))


class TestCookieListCreateAPIView(BaseTestAPIView):
    url = "/api/cookies/"

    def test_get_list__ok(self, client, cookie, user):
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_cookie(cookie)]

    def test_create__ok(self, client, user, dbs):
        cookie_data = {"source_type": SourceType.YANDEX}
        client.login(user)
        response = client.post(self.url, data=cookie_data, files={"file": _file()})
        response_data = self.assert_ok_response(response, status_code=201)
        cookie = await_(Cookie.async_get(dbs, id=response_data["id"]))
        assert cookie is not None
        assert response_data == _cookie(cookie)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    def test_create__invalid_request__fail(
        self, client, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)


class TestCookieRUDAPIView(BaseTestAPIView):
    url = "/api/cookies/{id}/"

    def test_get_detailed__ok(self, client, cookie, user):
        client.login(user)
        url = self.url.format(id=cookie.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _cookie(cookie)

    def test_get__cookie_from_another_user__fail(self, client, cookie, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=cookie.id)
        self.assert_not_found(client.get(url), cookie)

    def test_update__ok(self, client, cookie, user, dbs):
        client.login(user)
        url = self.url.format(id=cookie.id)
        data = {"source_type": SourceType.YANDEX}
        response = client.put(url, data=data, files={"file": _file("updated cookie data")})
        await_(dbs.refresh(cookie))
        response_data = self.assert_ok_response(response)
        assert response_data == _cookie(cookie)
        assert cookie.data == "updated cookie data"
        assert cookie.updated_at > cookie.created_at

    def test_update__cookie_from_another_user__fail(self, client, cookie, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=cookie.id)
        self.assert_not_found(client.put(url, files={"file": _file()}), cookie)

    def test_update__invalid_request__fail(self, client, cookie, user):
        client.login(user)
        url = self.url.format(id=cookie.id)
        data = {"source_type": SourceType.YANDEX}
        self.assert_bad_request(
            client.put(url, data=data, files={}),
            {"file": 'Missing data for required field.'}
        )

    def test_delete__ok(self, client, cookie, user, dbs):
        client.login(user)
        url = self.url.format(id=cookie.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await_(Cookie.async_get(dbs, id=cookie.id)) is None

    def test_delete__cookie_from_another_user__fail(self, client, cookie, user, dbs):
        user_2 = create_user(dbs)
        client.login(user_2)
        url = self.url.format(id=cookie.id)
        self.assert_not_found(client.delete(url), cookie)

    def test_delete__linked_episodes___fail(self, client, episode, cookie, user, dbs):
        await_(episode.update(dbs, cookie_id=cookie.id))
        await_(dbs.commit())

        client.login(user)
        url = self.url.format(id=cookie.id)
        self.assert_fail_response(
            client.delete(url),
            status_code=403,
            response_status=ResponseStatus.FORBIDDEN
        )

import youtube_dl

from common.enums import SourceType
from common.statuses import ResponseStatus
from modules.podcast.models import Cookie
from tests.api.test_base import BaseTestAPIView
from tests.helpers import await_, create_user
from tests.mocks import MockYoutubeDL


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/playlist/"
    default_fail_status_code = 400
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS
    cdata = {"data": "cookie in netscape format", "source_type": SourceType.YANDEX}

    @staticmethod
    def _playlist_data(mocked_youtube: MockYoutubeDL, source_type: SourceType):
        mocked_youtube.extract_info.return_value = {
            "_type": "playlist",
            "id": "pl1234",
            "title": "Playlist pl1234",
            "entries": [mocked_youtube.episode_info(source_type)],
        }

    def test_retrieve__ok(self, client, user, mocked_source_info_youtube, mocked_youtube):
        self._playlist_data(mocked_youtube, source_type=SourceType.YOUTUBE)
        client.login(user)
        response = client.get(self.url, params={"url": "http://link.to.source/"})
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": "pl1234",
            "title": "Playlist pl1234",
            "entries": [
                {
                    "id": mocked_youtube.info["id"],
                    "title": mocked_youtube.info["title"],
                    "description": mocked_youtube.info["description"],
                    "thumbnail_url": mocked_youtube.info["thumbnails"][0]["url"],
                    "url": mocked_youtube.info["webpage_url"],
                }
            ],
        }

    def test_retrieve__yandex__ok(self, client, user, mocked_source_info_yandex, mocked_youtube):
        self._playlist_data(mocked_youtube, source_type=SourceType.YANDEX)
        client.login(user)
        response = client.get(self.url, params={"url": "http://link.to.source/"})
        response_data = self.assert_ok_response(response)
        assert response_data["title"] == "Playlist pl1234"
        assert response_data["entries"] == [
            {
                "id": "123456",
                "title": "Test providers audio",
                "description": 'Playlist "Playlist #1" | Track #1 of 2',
                "thumbnail_url": "http://path.to-image.com",
                "url": "http://path.to-track.com",
            }
        ]

    def test_retrieve__use_cookies(
        self, dbs, client, user, mocked_source_info_yandex, mocked_youtube
    ):
        self._playlist_data(mocked_youtube, source_type=SourceType.YANDEX)
        cdata = self.cdata | {"owner_id": user.id}
        cookie = await_(Cookie.async_create(dbs, db_commit=True, **cdata))

        client.login(user)
        response = client.get(self.url, params={"url": "http://link.to.source/"})
        self.assert_ok_response(response)
        mocked_youtube.assert_called_with(cookiefile=cookie.as_file())

    def test_retrieve__cookies_from_another_user(
        self, dbs, client, user, mocked_source_info_yandex, mocked_youtube
    ):
        self._playlist_data(mocked_youtube, source_type=SourceType.YANDEX)

        cdata = self.cdata | {"owner_id": create_user(dbs).id}
        await_(Cookie.async_create(dbs, db_commit=True, **cdata))

        cdata = self.cdata | {"owner_id": user.id}
        cookie = await_(Cookie.async_create(dbs, db_commit=True, **cdata))

        client.login(user)
        response = client.get(self.url, params={"url": "http://link.to.source/"})
        self.assert_ok_response(response)
        mocked_youtube.assert_called_with(cookiefile=cookie.as_file())

    def test_retrieve__last_cookie(
        self, dbs, client, user, mocked_source_info_yandex, mocked_youtube
    ):
        self._playlist_data(mocked_youtube, source_type=SourceType.YANDEX)
        cdata = self.cdata | {"owner_id": user.id}

        await_(Cookie.async_create(dbs, db_commit=True, **cdata))
        cookie = await_(Cookie.async_create(dbs, db_commit=True, **cdata))

        client.login(user)
        response = client.get(self.url, params={"url": "http://link.to.source/"})
        self.assert_ok_response(response)
        mocked_youtube.assert_called_with(cookiefile=cookie.as_file())

    def test_retrieve__invalid_playlist_link__fail(self, client, user, mocked_youtube):
        mocked_youtube.extract_info.return_value = {"_type": "video"}
        client.login(user)
        response = client.get(self.url, data={"url": mocked_youtube.watch_url})
        response_data = self.assert_fail_response(response, status_code=400)
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": "It seems like incorrect playlist. yt_content_type='video'",
        }

    def test_retrieve__unsupported_url__fail(self, client, user, mocked_youtube):
        err_msg = "Unsupported URL: https://ya.ru"
        mocked_youtube.extract_info.side_effect = youtube_dl.utils.DownloadError(err_msg)
        client.login(user)
        response = client.get(self.url, data={"url": "https://ya.ru"})
        response_data = self.assert_fail_response(response, status_code=400)
        assert response_data == {
            "error": "Requested data is not valid.",
            "details": f"Couldn't extract playlist: {err_msg}",
        }

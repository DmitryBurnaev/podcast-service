import youtube_dl

from common.statuses import ResponseStatus
from tests.api.test_base import BaseTestAPIView


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/playlist/"
    default_fail_status_code = 400
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    def test_retrieve__ok(self, client, user, mocked_youtube):
        mocked_youtube.extract_info.return_value = {
            "_type": "playlist",
            "id": "pl1234",
            "title": "Playlist pl1234",
            "entries": [mocked_youtube.info],
        }
        client.login(user)
        response = client.get(self.url, data={"url": mocked_youtube.watch_url})
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

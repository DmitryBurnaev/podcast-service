from tests.integration.api.test_base import BaseTestAPIView


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/playlist/"

    def test_retrieve__invalid_playlist_link__fail(self, client, user, mocked_youtube):
        mocked_youtube.extract_info.return_value = {"_type": "video"}
        client.login(user)
        response = client.get(self.url, data={"url": mocked_youtube.watch_url})
        assert response.status_code == 400
        assert response.json() == {
            "error": "Requested data is not valid.",
            "details": "It seems like incorrect playlist. yt_content_type='video'"
        }

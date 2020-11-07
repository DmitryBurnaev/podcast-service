from tests.integration.api.test_base import BaseTestAPIView


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/"

    def test_get_list__ok(self, client):
        self._login()
        response_data = self._request(client, "GET")
        assert response_data == []

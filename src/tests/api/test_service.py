from unittest.mock import patch, Mock

from tests.api.test_base import BaseTestAPIView
from tests.helpers import PodcastTestClient


class TestHealthCheckAPIView(BaseTestAPIView):
    url = "/health_check/"

    def test_health__ok(self, client: PodcastTestClient):
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == {"services": {"postgres": "ok"}, "errors": []}

    @patch("common.models.ModelMixin.async_filter")
    def test_health__fail(self, client: PodcastTestClient, mock_filter: Mock):
        mock_filter.side_effect = RuntimeError("Oops")
        response = client.get(self.url)
        response_data = self.assert_fail_response(response, status_code=503)
        assert response_data == {
            "services": {"postgres": "down"},
            "errors": ["Couldn't connect to DB: RuntimeError('Oops')"],
        }


class TestSentryCheckAPIView(BaseTestAPIView):
    url = "/sentry_check/"

    def test_sentry__ok(self, client: PodcastTestClient):
        response = client.get(self.url)
        response_data = self.assert_fail_response(response, status_code=500)
        assert response_data == {"error": "Something went wrong", "details": "Oops!"}

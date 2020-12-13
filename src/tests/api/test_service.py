from unittest.mock import patch

from tests.api.test_base import BaseTestAPIView


class TestHealthCheckAPIView(BaseTestAPIView):
    url = "/health_check/"

    def test_health__ok(self, client):
        response = client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {"services": {"postgres": "ok"}, "errors": []}

    @patch("common.models.BaseModel.async_filter")
    def test_health__fail(self, mock_filter, client):
        mock_filter.side_effect = RuntimeError("Oops")
        response = client.get(self.url)
        assert response.status_code == 503
        assert response.json() == {
            "services": {"postgres": "down"},
            "errors": ["Couldn't connect to DB: RuntimeError 'Oops'"],
        }


class TestSentryCheckAPIView(BaseTestAPIView):
    url = "/sentry_check/"

    def test_sentry__ok(self, client):
        response = client.get(self.url)
        assert response.status_code == 500
        assert response.json() == {"error": "Something went wrong", "details": "Oops!"}

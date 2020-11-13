from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import video_id, get_user_data, create_user


class TestProgressAPIView(BaseTestAPIView):
    url = "/api/progress/"

    def test_episodes__progress__from_another_user__ok(self, episode, client):
        client.login(create_user())
        response = client.get(self.url)
        # TODO: Put records (with episodes from another user) to RedisMock
        assert response.status_code == 200, f"Progress API is not available: {response.text}"
        assert response.json() == []

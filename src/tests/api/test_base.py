import asyncio

from modules.podcast.models import Podcast, Episode
from tests.helpers import get_video_id


class BaseTestCase:

    @staticmethod
    def async_run(call):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(call)

    def _create_episode(
        self,
        episode_data: dict,
        podcast: Podcast,
        status: Episode.Status = Episode.Status.NEW,
        file_size: int = 0,
        source_id: str = None

    ) -> Episode:
        src_id = source_id or get_video_id()
        episode_data.update({
            "podcast_id": podcast.id,
            "source_id": src_id,
            "file_name": f"file_name_{src_id}.mp3",
            "status": status,
            "file_size": file_size,
        })
        return self.async_run(Episode.create(**episode_data))


class BaseTestAPIView(BaseTestCase):
    url: str = NotImplemented

    @staticmethod
    def assert_bad_request(response, error_details):
        response_data = response.json()
        assert response.status_code == 400
        assert response_data["error"] == "Requested data is not valid."
        for error_field, error_value in error_details.items():
            assert error_field in response_data["details"]
            assert error_value in response_data["details"][error_field]

    @staticmethod
    def assert_not_found(response, instance):
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": (
                f"{instance.__class__.__name__} #{instance.id} "
                f"does not exist or belongs to another user"
            ),
        }

    @staticmethod
    def assert_unauth(response):
        assert response.status_code == 401
        assert response.json() == {
            'error': 'Authentication is required',
            'details': 'Invalid token header. No credentials provided.',
        }

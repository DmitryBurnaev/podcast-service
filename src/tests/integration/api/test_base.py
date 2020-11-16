import asyncio
import json
from typing import Union

from starlette.testclient import TestClient

from modules.podcast.models import Podcast, Episode
from tests.integration.conftest import video_id


class BaseTestAPIView:
    url: str = NotImplemented

    @staticmethod
    def async_run(call):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(call)

    def _request(
        self,
        client: TestClient,
        method: str,
        url: str = None,
        json_data: Union[list, dict] = None,
        expected_status_code: int = 200,
        expected_json: bool = True,
        **client_kwargs,
    ):
        url = url or self.url
        method_handler_map = {
            "get": client.get,
            "post": client.post,
            "patch": client.patch,
            "put": client.put,
            "delete": client.delete,
        }
        method_handler = method_handler_map[method.lower()]
        kwargs = client_kwargs or {}
        if json_data:
            kwargs["data"] = json.dumps(json_data)
            kwargs["content_type"] = "application/json"

        response = method_handler(url, **kwargs)
        assert (
            response.status_code == expected_status_code
        ), f"\n{response.status_code=} \n{response.content=} \n{url=} \n{kwargs=}"

        return response.json() if expected_json else response.content

    def _create_episode(
        self,
        episode_data: dict,
        podcast: Podcast,
        status: Episode.Status = Episode.Status.NEW,
        file_size: int = 0,
        source_id: str = None

    ) -> Episode:
        src_id = source_id or video_id()
        episode_data.update({
            "podcast_id": podcast.id,
            "source_id": src_id,
            "file_name": f"file_name_{src_id}.mp3",
            "status": status,
            "file_size": file_size,
        })
        return self.async_run(Episode.create(**episode_data))

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


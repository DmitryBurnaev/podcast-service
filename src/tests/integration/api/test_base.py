import datetime
import json
from typing import Union

from starlette.testclient import TestClient

from tests.integration.conftest import create_user


class BaseTestAPIView:
    url: str = NotImplemented

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

from starlette.responses import Response

from common.request import PRequest
from common.views import BaseHTTPEndpoint
from modules.podcast.schemas import HealthCheckResponseSchema


class HealthCheckAPIView(BaseHTTPEndpoint):
    """Allows to simple check app's accessibility"""

    schema_request = None
    schema_response = HealthCheckResponseSchema
    auth_backend = None

    async def get(self, _: PRequest) -> Response:
        return self._response({"status": "ok"})

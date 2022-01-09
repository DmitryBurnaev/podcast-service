from starlette import status

from common.utils import get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Cookie
from modules.podcast.schemas import (
    CookieCreateUpdateSchema,
    CookieListResponseSchema,
    CookieListRequestSchema,
)

logger = get_logger(__name__)


class CookieListCreateAPIView(BaseHTTPEndpoint):
    """List and Create API for cookie's objects"""

    schema_request = CookieCreateUpdateSchema
    schema_response = CookieListResponseSchema

    async def get(self, request):
        cleaned_data = await self._validate(
            request, schema=CookieListRequestSchema, location="query"
        )
        cookies = await Cookie.async_filter(
            self.db_session, created_by_id=request.user.id, domains__inarr=cleaned_data["domain"]
        )
        return self._response(cookies)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        cookie = await Cookie.async_create(
            db_session=request.db_session,
            data=cleaned_data["data"],
            domains=cleaned_data["domains"],
            created_by_id=request.user.id,
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)

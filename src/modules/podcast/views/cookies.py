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
        domain = cleaned_data.get("domain")
        cookies = await Cookie.async_filter(self.db_session, aliases__inarr=domain)
        return self._response(cookies)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        # TODO: create new cookie here
        # podcast = await Podcast.async_create(
        #     db_session=request.db_session,
        #     name=cleaned_data["name"],
        #     publish_id=Podcast.generate_publish_id(),
        #     description=cleaned_data["description"],
        #     created_by_id=request.user.id,
        # )
        return self._response(cleaned_data, status_code=status.HTTP_201_CREATED)

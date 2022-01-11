from starlette import status

from common.exceptions import InvalidParameterError
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
        filter_kwargs = {'created_by_id': request.user.id}
        if domain := cleaned_data.get('domain'):
            filter_kwargs['domains__inarr'] = domain

        cookies = await Cookie.async_filter(self.db_session, **filter_kwargs)
        return self._response(cookies)

    async def post(self, request):
        # TODO: upload file with cookies (netscape formatted) here
        cleaned_data = await self._validate(request)
        # TODO: save file's content and domains
        cookie = await Cookie.async_create(
            db_session=request.db_session,
            data=cleaned_data["data"],
            domains=cleaned_data["domains"],
            created_by_id=request.user.id,
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)

    async def _validate(self, request, **_) -> dict:
        form = await request.form()
        if not (file := form.get("file")):
            raise InvalidParameterError(details="Cookie file is required here")

        return {"file": file}

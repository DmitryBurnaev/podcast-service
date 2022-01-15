from starlette import status

from common.exceptions import InvalidParameterError
from common.utils import get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Source
from modules.podcast.schemas import (
    CookieResponseSchema,
    CookieListRequestSchema,
    CookieCreateUpdateSchema,
)

logger = get_logger(__name__)


class CookieListCreateAPIView(BaseHTTPEndpoint):
    """List and Create API for cookie's objects"""

    schema_request = CookieListRequestSchema
    schema_response = CookieResponseSchema

    async def get(self, request):
        cleaned_data = await self._validate(request, location="query")
        filter_kwargs = {"created_by_id": request.user.id}
        if domain := cleaned_data.get("domain"):
            filter_kwargs["domains__inarr"] = domain

        cookies = await Source.async_filter(self.db_session, **filter_kwargs)
        return self._response(cookies)

    async def post(self, request):
        cleaned_data = await self._validate_post(request)
        cookie_data = (await cleaned_data["file"].read()).decode()
        cookie = await Source.async_create(
            db_session=request.db_session,
            data=cookie_data,
            domains=cleaned_data["domains"],
            created_by_id=request.user.id,
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)

    @staticmethod
    async def _validate_post(request) -> dict:
        form = await request.form()
        if not (file := form.get("file")):
            raise InvalidParameterError(details="Cookie file is required here")

        if not (domains := form.get("domains")):
            raise InvalidParameterError(details="Domains is required as comma separated list")

        return {"file": file, "domains": [domain.strip() for domain in domains.split(",")]}


class CookieRUDAPIView(BaseHTTPEndpoint):
    """Retrieve, Update, Delete API for cookies"""

    db_model = Source
    schema_request = CookieCreateUpdateSchema
    schema_response = CookieResponseSchema

    async def get(self, request):
        cookie_id = request.path_params["cookie_id"]
        cookie = await self._get_object(cookie_id)
        return self._response(cookie)

    async def patch(self, request):
        cleaned_data = await self._validate(request, partial_=True)
        cookie_id = request.path_params["cookie_id"]
        cookie = await self._get_object(cookie_id)
        await cookie.update(self.db_session, **cleaned_data)
        return self._response(cookie)

    async def delete(self, request):
        cookie_id = int(request.path_params["cookie_id"])
        cookie = await self._get_object(cookie_id)

        await cookie.delete(self.db_session)
        return self._response()

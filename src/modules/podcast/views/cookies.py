from sqlalchemy import exists
from starlette import status

from common.exceptions import InvalidParameterError, PermissionDeniedError
from common.utils import get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Cookie, Episode
from modules.podcast.schemas import CookieResponseSchema

logger = get_logger(__name__)


class CookieListCreateAPIView(BaseHTTPEndpoint):
    """List and Create API for cookie's objects"""

    schema_response = CookieResponseSchema

    async def get(self, request):
        cookies = await Cookie.async_filter(self.db_session, created_by_id=request.user.id)
        return self._response(cookies)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        cookie_data = (await cleaned_data["file"].read()).decode()
        cookie = await Cookie.async_create(
            db_session=request.db_session,
            data=cookie_data,
            created_by_id=request.user.id,
            source_type=cleaned_data["source_type"],
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)

    @staticmethod
    async def _validate(request, **_) -> dict:
        form = await request.form()
        if not (file := form.get("file")):
            raise InvalidParameterError(details="Cookie file is required here")

        if not (source_type := form.get("source_type")):
            raise InvalidParameterError(details="source_type is required")

        return {"file": file, "domains": source_type}


class CookieRDAPIView(BaseHTTPEndpoint):
    """Retrieve, Update, Delete API for cookies"""

    db_model = Cookie
    schema_response = CookieResponseSchema

    async def get(self, request):
        cookie_id = request.path_params["cookie_id"]
        cookie = await self._get_object(cookie_id)
        return self._response(cookie)

    async def delete(self, request):
        cookie_id = int(request.path_params["cookie_id"])
        query = Episode.prepare_query(db_session=request.db_session, cookie_id=cookie_id)
        (has_episodes,) = next(await self.db_session.execute(exists(query).select()))
        if has_episodes:
            raise PermissionDeniedError('There are episodes related to this cookie')

        cookie = await self._get_object(cookie_id)
        await cookie.delete(self.db_session)
        return self._response()

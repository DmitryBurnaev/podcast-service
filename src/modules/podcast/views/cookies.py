from sqlalchemy import exists
from starlette import status

from common.exceptions import PermissionDeniedError
from common.utils import get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Cookie, Episode
from modules.podcast.schemas import CookieResponseSchema, CookieCreateUpdateSchema

logger = get_logger(__name__)


class BaseCookieAPIView(BaseHTTPEndpoint):
    """ Common actions for cookie's update API view """

    async def _validate(self, request, partial_=False, **_) -> dict:
        cleaned_data = await super()._validate(request, partial_=partial_, location='form')
        cleaned_data['data'] = (await cleaned_data.pop("file").read()).decode()
        return cleaned_data


class CookieListCreateAPIView(BaseCookieAPIView):
    """List and Create API for cookie's objects"""

    schema_response = CookieResponseSchema
    schema_request = CookieCreateUpdateSchema

    async def get(self, request):
        cookies = await Cookie.async_filter(self.db_session, created_by_id=request.user.id)
        return self._response(cookies)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        cookie = await Cookie.async_create(
            db_session=request.db_session,
            created_by_id=request.user.id,
            **cleaned_data
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)


class CookieRDAPIView(BaseCookieAPIView):
    """Retrieve, Update, Delete API for cookies"""

    db_model = Cookie
    schema_response = CookieResponseSchema
    schema_request = CookieCreateUpdateSchema

    async def get(self, request):
        cookie_id = request.path_params["cookie_id"]
        cookie = await self._get_object(cookie_id)
        return self._response(cookie)

    async def patch(self, request):
        cleaned_data = await self._validate(request, partial_=True)
        cookie_id = int(request.path_params["cookie_id"])
        cookie = await self._get_object(cookie_id)
        await cookie.update(self.db_session, **cleaned_data)
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

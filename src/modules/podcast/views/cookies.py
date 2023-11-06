import logging

from starlette import status
from starlette.responses import Response
from sqlalchemy import exists, select

from common.request import PRequest
from common.views import BaseHTTPEndpoint
from common.exceptions import PermissionDeniedError, InvalidRequestError
from modules.podcast.models import Cookie, Episode
from modules.podcast.schemas import CookieResponseSchema, CookieCreateUpdateSchema

logger = logging.getLogger(__name__)


class BaseCookieAPIView(BaseHTTPEndpoint):
    """Common actions for cookie's update API view"""

    async def _validate(self, request: PRequest, *_) -> dict:
        cleaned_data = await super()._validate(request, location="form")
        file_content = await cleaned_data.pop("file").read()
        try:
            encrypted_data = Cookie.get_encrypted_data(file_content.decode())
            cleaned_data["data"] = encrypted_data
        except UnicodeDecodeError as exc:
            raise InvalidRequestError({"file": f"Unexpected cookie's file content: {exc}"}) from exc

        return cleaned_data


class CookieListCreateAPIView(BaseCookieAPIView):
    """List and Create API for cookie's objects"""

    schema_response = CookieResponseSchema
    schema_request = CookieCreateUpdateSchema

    async def get(self, request: PRequest) -> Response:
        cookies_query = (
            select(Cookie)
            .with_only_columns(Cookie.id, Cookie.source_type, Cookie.created_at)
            .filter_by(owner_id=request.user.id)
            .order_by(Cookie.source_type, Cookie.created_at.desc())
            .distinct(Cookie.source_type)
        )
        cookies = (
            Cookie.from_dict(cookie_data._asdict())  # pragma: no cover
            for cookie_data in await self.db_session.execute(cookies_query)
        )
        return self._response(cookies)

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request)
        cookie = await Cookie.async_create(
            db_session=request.db_session,
            owner_id=request.user.id,
            **cleaned_data,
        )
        return self._response(cookie, status_code=status.HTTP_201_CREATED)


class CookieRUDAPIView(BaseCookieAPIView):
    """Retrieve, Update, Delete API for cookies"""

    db_model = Cookie
    schema_response = CookieResponseSchema
    schema_request = CookieCreateUpdateSchema

    async def get(self, request: PRequest) -> Response:
        cookie_id = request.path_params["cookie_id"]
        cookie = await self._get_object(cookie_id)
        return self._response(cookie)

    async def put(self, request: PRequest) -> Response:
        cookie_id = int(request.path_params["cookie_id"])
        cookie = await self._get_object(cookie_id)
        cleaned_data = await self._validate(request)
        await cookie.update(self.db_session, **cleaned_data)
        return self._response(cookie)

    async def delete(self, request: PRequest) -> Response:
        cookie_id = int(request.path_params["cookie_id"])
        cookie = await self._get_object(cookie_id)
        query = Episode.prepare_query(cookie_id=cookie_id)
        (has_episodes,) = next(await self.db_session.execute(exists(query).select()))
        if has_episodes:
            raise PermissionDeniedError("There are episodes related to this cookie")

        await cookie.delete(self.db_session)
        return self._response()

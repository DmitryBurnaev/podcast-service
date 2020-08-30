import asyncio
import json
import logging
from typing import Type, Union, Iterable, Any

from pydantic import ValidationError, BaseModel
from pydantic.json import pydantic_encoder
from starlette import status
from starlette.endpoints import HTTPEndpoint
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.exceptions import (
    InvalidParameterError,
    BaseApplicationError,
    UnexpectedError,
    HttpError, NotFoundError, InvalidResponseError
)
from common.typing import DBModel
from core.database import db
from modules.auth.backend import LoginRequiredAuthBackend

logger = logging.getLogger(__name__)


class PydanticJSONEncoder(json.JSONEncoder):
    """
    JSONEncoder subclass that knows how to encode date/time, decimal types, and
    UUIDs.
    """
    def default(self, o):
        return pydantic_encoder(o)


class JSONResponseNew(JSONResponse):

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            cls=PydanticJSONEncoder
        ).encode("utf-8")


# TODO: pydantic validation

class BaseHTTPEndpoint(HTTPEndpoint):
    request: Request = None
    db_model: DBModel = NotImplemented
    model: Type[BaseModel] = NotImplemented
    model_response: Type[BaseModel] = NotImplemented
    auth_backend = LoginRequiredAuthBackend

    async def dispatch(self) -> None:
        self.request = Request(self.scope, receive=self.receive)
        handler_name = "get" if self.request.method == "HEAD" else self.request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)
        if self.auth_backend:
            backend = self.auth_backend()
            self.scope["user"] = await backend.authenticate(self.request)

        try:
            response = await handler(self.request)
        except BaseApplicationError as err:
            raise err
        except HTTPException as err:
            raise HttpError(err.detail, status_code=err.status_code)
        except Exception as err:
            error_details = repr(err)
            logger.exception("Unexpected error handled: %s", error_details)
            raise UnexpectedError(error_details)

        await response(self.scope, self.receive, self.send)

    async def get_object(self, instance_id, db_model: DBModel = None, **filter_kwargs) -> db.Model:
        db_model = db_model or self.db_model
        instance = await db_model.async_get(
            id=instance_id, created_by_id=self.request.user.id, **filter_kwargs
        )
        if not instance:
            raise NotFoundError(
                f"{db_model.__name__} #{instance_id} does not exist or belongs to another user"
            )

        return instance

    async def _validate(self, request) -> model:
        # TODO: extend logic?!
        request_body = await request.json()
        try:
            res = self.model(**request_body)
        except ValidationError as e:
            raise InvalidParameterError(details=e.errors())

        return res

    def _response(
        self,
        instance: Union[DBModel, Iterable[DBModel]] = None,
        data: Any = None,
        status_code: int = status.HTTP_200_OK
    ) -> JSONResponse:
        """ Shortcut for returning JSON-response  """

        response_data = {}
        response_model = self.model_response or self.model
        try:
            if instance is not None:
                response_data = response_model.from_orm(instance)

            elif data is not None:
                response_data = response_model(**data)

        except ValidationError as e:
            raise InvalidResponseError(details=e.errors())

        return JSONResponseNew(response_data, status_code=status_code)

    async def _run_task(self, task, *args, **kwargs):
        loop = asyncio.get_running_loop()
        logger.info(f"RUN task {task}")
        # handler = partial(self.request.app.rq_queue.enqueue, task, *args, **kwargs)
        # await loop.run_in_executor(None, handler)

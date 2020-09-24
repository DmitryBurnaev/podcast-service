import asyncio
import json
import logging
from typing import Type, Union, Iterable, Any

from marshmallow import Schema, ValidationError
# import
from starlette import status
from starlette.endpoints import HTTPEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from webargs_starlette import parser, WebargsHTTPException

from common.exceptions import (
    InvalidParameterError,
    BaseApplicationError,
    UnexpectedError,
    NotFoundError,
)
from common.typing import DBModel
from core.database import db
from modules.auth.backend import LoginRequiredAuthBackend

logger = logging.getLogger(__name__)


class BaseHTTPEndpoint(HTTPEndpoint):
    request: Request = None
    db_model: DBModel = NotImplemented
    auth_backend = LoginRequiredAuthBackend
    schema_request: Type[Schema] = NotImplemented
    schema_response: Type[Schema] = NotImplemented

    async def dispatch(self) -> None:
        self.request = Request(self.scope, receive=self.receive)
        handler_name = "get" if self.request.method == "HEAD" else self.request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)
        if self.auth_backend:
            backend = self.auth_backend()
            self.scope["user"] = await backend.authenticate(self.request)

        try:
            response = await handler(self.request)
        except (BaseApplicationError, WebargsHTTPException) as err:
            raise err
        except Exception as err:
            error_details = repr(err)
            logger.exception("Unexpected error handled: %s", error_details)
            raise UnexpectedError(error_details)

        await response(self.scope, self.receive, self.send)

    async def _get_object(self, instance_id, db_model: DBModel = None, **filter_kwargs) -> db.Model:
        db_model = db_model or self.db_model
        instance = await db_model.async_get(
            id=instance_id, created_by_id=self.request.user.id, **filter_kwargs
        )
        if not instance:
            raise NotFoundError(
                f"{db_model.__name__} #{instance_id} does not exist or belongs to another user"
            )

        return instance

    async def _validate(self, request, partial: bool = False) -> dict:

        schema_kwargs = {}
        if partial:
            schema_kwargs["partial"] = [field for field in self.schema_request().fields]

        schema = self.schema_request(**schema_kwargs)
        try:
            cleaned_data = await parser.parse(schema, request)
        except ValidationError as e:
            raise InvalidParameterError(details=e.data)

        return cleaned_data

    def _response(
        self,
        instance: Union[DBModel, Iterable[DBModel]] = None,
        data: Any = None,
        status_code: int = status.HTTP_200_OK
    ) -> Response:
        """ Shortcut for returning JSON-response  """
        if data or instance:
            schema_kwargs = {}
            if isinstance(instance, Iterable):
                schema_kwargs["many"] = True

            response_data = self.schema_response(**schema_kwargs).dump(instance or data)
            return JSONResponse(response_data, status_code=status_code)

        return Response(status_code=status_code)

    # async def _run_task(self, task, *args, **kwargs):
    #     loop = asyncio.get_running_loop()
    #     logger.info(f"RUN task {task}")
        # handler = partial(self.request.app.rq_queue.enqueue, task, *args, **kwargs)
        # await loop.run_in_executor(None, handler)

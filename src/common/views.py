import json
import asyncio
import logging
from json import JSONDecodeError
from dataclasses import dataclass
from typing import Type, Iterable, Any, ClassVar

from starlette import status
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.endpoints import HTTPEndpoint, WebSocketEndpoint
from sqlalchemy.exc import SQLAlchemyError, DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession
from marshmallow import Schema, ValidationError, fields
from webargs_starlette import parser, WebargsHTTPException

from common.exceptions import (
    NotFoundError,
    UnexpectedError,
    BaseApplicationError,
    InvalidRequestError,
)
from common.request import PRequest
from common.schemas import WSRequestAuthSchema
from common.statuses import ResponseStatus
from common.models import DBModel
from common.utils import create_task
from modules.auth.models import User
from modules.podcast.models import Podcast
from modules.podcast.tasks.base import RQTask
from modules.auth.utils import TokenCollection
from modules.auth.backend import LoginRequiredAuthBackend, BaseAuthJWTBackend

logger = logging.getLogger(__name__)


class BaseHTTPEndpoint(HTTPEndpoint):
    """
    Base View witch used as a base class for every API's endpoints
    """

    app = None
    request: PRequest
    db_model: ClassVar[DBModel]
    db_session: AsyncSession
    schema_request: ClassVar[Type[Schema]]
    schema_response: ClassVar[Type[Schema]]
    auth_backend: ClassVar[Type[BaseAuthJWTBackend] | None] = LoginRequiredAuthBackend

    async def dispatch(self) -> None:
        """
        This method is calling in every request.
        So, we can use this one for customs authenticate and catch all exceptions
        """

        self.request = PRequest(self.scope, receive=self.receive)
        self.app = self.scope.get("app")

        handler_name = self.request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)

        try:
            async with self.app.session_maker() as session:
                self.request.db_session = session
                self.db_session = session
                if self.auth_backend is not None:
                    backend = self.auth_backend(self.request)
                    user, session_id = await backend.authenticate()
                    self.scope["user"] = user
                    self.request.user_session_id = session_id

                response = await handler(self.request)  # noqa
                await self.db_session.commit()

        except (BaseApplicationError, WebargsHTTPException, HTTPException) as exc:
            await self.db_session.rollback()
            raise exc

        except (DatabaseError, SQLAlchemyError) as exc:
            await self.db_session.rollback()
            msg_template = "Unexpected DB-related error handled: %r"
            logger.exception(msg_template, exc)
            raise UnexpectedError("Unexpected DB-related error handled") from exc

        except Exception as exc:
            await self.db_session.rollback()
            msg_template = "Unexpected error handled: %r"
            logger.exception(msg_template, exc)
            raise UnexpectedError(msg_template % (exc,)) from exc

        await response(self.scope, self.receive, self.send)

    async def _get_object(
        self, instance_id, db_model: Type[DBModel] = None, **filter_kwargs
    ) -> DBModel:
        """
        Returns current object (only for logged-in or admin user) for CRUD API
        """

        db_model = db_model or self.db_model
        if not self.request.user.is_superuser:
            filter_kwargs["owner_id"] = self.request.user.id

        instance = await db_model.async_get(self.db_session, id=instance_id, **filter_kwargs)
        if not instance:
            raise NotFoundError(
                f"{db_model.__name__} #{instance_id} does not exist or belongs to another user"
            )

        return instance

    async def _validate(
        self, request, schema: Type[Schema] = None, partial_: bool = False, location: str = None
    ) -> dict:
        """Simple validation, based on marshmallow's schemas"""

        schema_request = schema or self.schema_request
        schema_kwargs = {}
        if partial_:
            schema_kwargs["partial"] = list(schema_request().fields)

        schema, cleaned_data = schema_request(**schema_kwargs), {}
        try:
            cleaned_data = await parser.parse(schema, request, location=location)
            if hasattr(schema, "is_valid"):
                schema.is_valid(cleaned_data)

        except ValidationError as exc:
            raise InvalidRequestError(details=exc.data) from exc

        return cleaned_data

    def _response(
        self,
        instance: DBModel | Iterable[DBModel] | TokenCollection | dict | None = None,
        data: Any = None,
        status_code: int = status.HTTP_200_OK,
        response_status: ResponseStatus = ResponseStatus.OK,
    ) -> Response:
        """Returns JSON-Response (with single instance or list of them) or empty Response"""

        response_instance = instance if (instance is not None) else data
        payload = {}
        if response_instance is not None:
            schema_kwargs = {}
            if isinstance(response_instance, Iterable) and not isinstance(response_instance, dict):
                schema_kwargs["many"] = True

            payload = self.schema_response(**schema_kwargs).dump(response_instance)

        if status_code == status.HTTP_204_NO_CONTENT:
            if not payload:
                return Response(None, status_code=status_code)

            status_code = status.HTTP_200_OK
            logger.warning("Status code changed to 200 because result payload is not empty")

        return JSONResponse(
            {"status": response_status, "payload": payload}, status_code=status_code
        )

    async def _run_task(self, task_class: Type[RQTask], *args, **kwargs):
        """Enqueue RQ task"""

        logger.info("RUN task %s", task_class)
        task = task_class()
        await run_in_threadpool(self.app.rq_queue.enqueue, task, *args, **kwargs)


class ServicesCheckSchema(Schema):
    postgres = fields.Str()


class HealthCheckSchema(Schema):
    services = fields.Nested(ServicesCheckSchema)
    errors = fields.List(fields.Str)


class HealthCheckAPIView(BaseHTTPEndpoint):
    """Allows controlling status of web application (live ASGI and pg connection)"""

    auth_backend = None
    schema_response = HealthCheckSchema

    async def get(self, *_):
        response_data = {"services": {}, "errors": []}
        result_status = status.HTTP_200_OK
        response_status = ResponseStatus.OK

        try:
            await Podcast.async_filter(self.db_session)
        except Exception as exc:
            error_msg = f"Couldn't connect to DB: {exc!r}"
            logger.exception(error_msg)
            response_data["services"]["postgres"] = "down"
            response_data["errors"].append(error_msg)
        else:
            response_data["services"]["postgres"] = "ok"

        services = response_data.get("services").values()

        if "down" in services or response_data.get("errors"):
            response_data["status"] = "down"
            result_status = status.HTTP_503_SERVICE_UNAVAILABLE
            response_status = ResponseStatus.INTERNAL_ERROR

        return self._response(
            data=response_data, status_code=result_status, response_status=response_status
        )


class SentryCheckAPIView(BaseHTTPEndpoint):
    """Simple checker sentry config (raise err + logger)."""

    auth_backend = None

    @staticmethod
    async def get(*_):
        logger.error("Error check sentry")
        try:
            1 / 0
        except ZeroDivisionError as exc:
            logger.exception("Test exc for sentry: %r", exc)

        raise BaseApplicationError("Oops!")


@dataclass
class WSRequest:
    headers: dict[str, str]
    data: dict | None = None


class BaseWSEndpoint(WebSocketEndpoint):
    auth_backend: ClassVar[Type[BaseAuthJWTBackend]] = LoginRequiredAuthBackend
    request_schema: ClassVar[Type[Schema]] = WSRequestAuthSchema
    user: User
    request: WSRequest
    background_task: asyncio.Task

    async def dispatch(self) -> None:
        # pylint: disable=attribute-defined-outside-init
        self.app = self.scope.get("app")  # noqa
        await super().dispatch()

    async def on_connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        cleaned_data = self._validate(data)
        self.request = WSRequest(headers=cleaned_data["headers"], data=cleaned_data)
        self.user = await self._auth()
        self.background_task = create_task(
            self._background_handler(websocket),
            log_instance=logger,
            error_message="Couldn't finish _background_handler for class %s",
            error_message_message_args=(self.__class__.__name__,),
        )

    async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
        if self.background_task:
            self.background_task.cancel()
            logger.info("Background task '_background_handler' was canceled")

        logger.info("WS connection was closed")

    async def _background_handler(self, websocket: WebSocket):
        raise NotImplementedError

    def _validate(self, data: str) -> dict:
        try:
            request_data = json.loads(data)
        except JSONDecodeError as exc:
            raise InvalidRequestError(f"Couldn't parse WS request data: {exc}") from exc

        return self.request_schema().load(request_data)

    async def _auth(self) -> User:
        async with self.app.session_maker() as db_session:
            backend = self.auth_backend(self.request, db_session)
            user, _ = await backend.authenticate()
            self.scope["user"] = user

        return user

import asyncio
from functools import partial
from typing import Type, Union, Iterable, Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from starlette.requests import Request
from starlette.endpoints import HTTPEndpoint
from marshmallow import Schema, ValidationError, fields
from starlette.responses import JSONResponse, Response
from webargs_starlette import parser, WebargsHTTPException

from common.exceptions import (
    NotFoundError,
    UnexpectedError,
    BaseApplicationError,
    InvalidParameterError,
)
from common.statuses import ResponseStatus
from common.models import DBModel
from common.utils import get_logger
from modules.podcast.models import Podcast
from modules.podcast.tasks.base import RQTask
from modules.auth.utils import TokenCollection
from modules.auth.backend import LoginRequiredAuthBackend

logger = get_logger(__name__)


class PRequest(Request):
    db_session: AsyncSession = None


class BaseHTTPEndpoint(HTTPEndpoint):
    """
    Base View witch used as a base class for every API's endpoints
    """

    request: PRequest = None
    app = None
    db_model: DBModel = NotImplemented
    db_session: AsyncSession = NotImplemented
    auth_backend = LoginRequiredAuthBackend
    schema_request: Type[Schema] = NotImplemented
    schema_response: Type[Schema] = NotImplemented

    async def dispatch(self) -> None:
        """
        This method is calling in every request.
        So, we can use this one for customs authenticate and catch all exceptions
        """

        self.request = PRequest(self.scope, receive=self.receive)
        self.app = self.scope.get("app")

        handler_name = "get" if self.request.method == "HEAD" else self.request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)

        try:
            async with self.app.sessionmaker() as session:
                if self.auth_backend:
                    backend = self.auth_backend(self.request)
                    self.scope["user"] = await backend.authenticate()

                self.request.db_session = session
                self.db_session = session
                response = await handler(self.request)

        except (BaseApplicationError, WebargsHTTPException) as err:
            raise err
        except Exception as err:
            msg_template = "Unexpected error handled: %r"
            logger.exception(msg_template, err)
            raise UnexpectedError(msg_template % (err,))

        await response(self.scope, self.receive, self.send)

    async def _get_object(
        self, instance_id, db_model: Type[DBModel] = None, **filter_kwargs
    ) -> DBModel:
        """
        Returns current object (only for logged-in or admin user) for CRUD API
        """

        db_model = db_model or self.db_model
        if not self.request.user.is_superuser:
            filter_kwargs["created_by_id"] = self.request.user.id

        instance = await db_model.async_get(self.db_session, id=instance_id, **filter_kwargs)
        if not instance:
            raise NotFoundError(
                f"{db_model.__name__} #{instance_id} does not exist or belongs to another user"
            )

        return instance

    async def _validate(self, request, partial_: bool = False, location: str = None) -> dict:
        """ Simple validation, based on marshmallow's schemas """

        schema_kwargs = {}
        if partial_:
            schema_kwargs["partial"] = [field for field in self.schema_request().fields]

        schema = self.schema_request(**schema_kwargs)
        try:
            cleaned_data = await parser.parse(schema, request, location=location)
            if hasattr(schema, "is_valid"):
                schema.is_valid(cleaned_data)

        except ValidationError as e:
            raise InvalidParameterError(details=e.data)

        return cleaned_data

    def _response(
        self,
        instance: Union[DBModel, Iterable[DBModel], TokenCollection] = None,
        data: Any = None,
        status_code: int = status.HTTP_200_OK,
        response_status: ResponseStatus = ResponseStatus.OK,
    ) -> Response:
        """ Returns JSON-Response (with single instance or list of them) or empty Response """

        response_instance = instance if (instance is not None) else data
        payload = {}
        if response_instance is not None:
            schema_kwargs = {}
            if isinstance(response_instance, Iterable) and not isinstance(response_instance, dict):
                schema_kwargs["many"] = True

            payload = self.schema_response(**schema_kwargs).dump(response_instance)

        return JSONResponse(
            {"status": response_status, "payload": payload}, status_code=status_code
        )

    async def _run_task(self, task_class: Type[RQTask], *args, **kwargs):
        """ Enqueue RQ task """

        logger.info(f"RUN task {task_class}")
        loop = asyncio.get_running_loop()
        task = task_class()
        handler = partial(self.app.rq_queue.enqueue, task, *args, **kwargs)
        await loop.run_in_executor(None, handler)


class ServicesCheckSchema(Schema):
    postgres = fields.Str()


class HealthCheckSchema(Schema):
    services = fields.Nested(ServicesCheckSchema)
    errors = fields.List(fields.Str)


class HealthCheckAPIView(BaseHTTPEndpoint):
    """ Allows to control status of web application (live ASGI and pg connection)"""

    auth_backend = None
    schema_response = HealthCheckSchema

    async def get(self, *_):
        response_data = {"services": {}, "errors": []}
        result_status = status.HTTP_200_OK
        response_status = ResponseStatus.OK

        try:
            await Podcast.async_filter(self.db_session)
        except Exception as error:
            error_msg = f"Couldn't connect to DB: {error.__class__.__name__} '{error}'"
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
    """ Simple checker sentry config (raise err + logger). """

    auth_backend = None

    async def get(self, request):  # noqa
        logger.error("Error check sentry")
        try:
            1 / 0
        except ZeroDivisionError as err:
            logger.exception(f"Test exc for sentry: {err}")

        raise BaseApplicationError("Oops!")

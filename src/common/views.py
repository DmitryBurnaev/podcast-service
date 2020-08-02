import json
from typing import Type, Union, Iterable, Any

from pydantic import ValidationError, BaseModel
from pydantic.json import pydantic_encoder
from starlette import status
from starlette.endpoints import HTTPEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.exceptions import InvalidParameterError
from common.typing import DBModel
from modules.auth.backend import LoginRequiredAuthBackend


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
    db_model: DBModel = NotImplemented
    model: Type[BaseModel] = NotImplemented
    model_response: Type[BaseModel] = NotImplemented
    auth_backend = LoginRequiredAuthBackend

    async def dispatch(self) -> None:
        request = Request(self.scope, receive=self.receive)
        handler_name = "get" if request.method == "HEAD" else request.method.lower()
        handler = getattr(self, handler_name, self.method_not_allowed)
        if self.auth_backend:
            backend = self.auth_backend()
            self.scope["user"] = await backend.authenticate(request)

        response = await handler(request)
        await response(self.scope, self.receive, self.send)

    async def _validate(self, request) -> model:
        # TODO: extend logic?!
        request_body = await request.json()
        try:
            res = self.model(**request_body)
        except ValidationError as e:
            print(e.json())
            raise InvalidParameterError(details=e.json())

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
        if instance is not None:
            response_data = response_model.from_orm(instance)

        elif data is not None:
            response_data = response_model(**data)

        return JSONResponseNew(response_data, status_code=status_code)

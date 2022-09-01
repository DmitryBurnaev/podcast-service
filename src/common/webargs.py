import json
from typing import Mapping, Iterable, Sequence, MutableSequence, Type, Callable, Any, NoReturn

from marshmallow import Schema, fields, ValidationError
from starlette.requests import Request
from webargs import core as wa_core
from webargs.asyncparser import AsyncParser
from webargs.multidictproxy import MultiDictProxy

from common.exceptions import HTTPRequestProcessingError

DEFAULT_TYPE_MAPPING = Schema.TYPE_MAPPING.copy()
DEFAULT_TYPE_MAPPING.update(
    {
        str: fields.String,
        dict: fields.Dict,
        list: fields.List,
        Mapping: fields.Dict,
        Iterable: fields.List,
        Sequence: fields.List,
        MutableSequence: fields.List,
    }
)
TypeMapping = Mapping[Type, Type[fields.Field]]


def is_json_request(req: Request) -> bool:
    content_type = req.headers.get("content-type")
    return wa_core.is_json(content_type)


class StarletteParser(AsyncParser):
    """Starlette request argument parser (copied from out-dated webargs-starlette lib)."""

    TYPE_MAPPING: TypeMapping = DEFAULT_TYPE_MAPPING

    __location_map__: dict[str, [str | Callable]] = dict(
        path_params="load_path_params", **wa_core.Parser.__location_map__
    )

    def load_path_params(self, req: Request, schema: Schema) -> Any:
        """Return the request's ``path_params`` or ``missing`` if there are none."""
        return req.path_params or wa_core.missing

    def load_querystring(self, req: Request, schema: Schema) -> MultiDictProxy:
        """Return query params from the request as a MultiDictProxy."""
        return MultiDictProxy(req.query_params, schema)

    def load_headers(self, req: Request, schema: Schema) -> MultiDictProxy:
        """Return headers from the request as a MultiDictProxy."""
        return MultiDictProxy(req.headers, schema)

    def load_cookies(self, req: Request, schema: Schema):
        """Return cookies from the request."""
        return req.cookies

    async def load_json(self, req: Request, schema: Schema) -> dict:
        """Return a parsed json payload from the request."""
        if not wa_core.is_json(req.headers.get("content-type")):
            return wa_core.missing
        try:
            json_data = await req.json()
        except json.JSONDecodeError as exc:
            if exc.doc == "":
                return wa_core.missing
            else:
                return self._handle_invalid_json_error(exc, req)
        except UnicodeDecodeError as exc:
            return self._handle_invalid_json_error(exc, req)
        return json_data

    async def load_form(self, req: Request, schema: Schema) -> MultiDictProxy:
        """Return form values from the request as a MultiDictProxy."""
        post_data = await req.form()
        return MultiDictProxy(post_data, schema)

    async def load_json_or_form(self, req: Request, schema: Schema) -> dict | MultiDictProxy:
        data = await self.load_json(req, schema)
        if data is not wa_core.missing:
            return data
        return await self.load_form(req, schema)

    def _handle_invalid_json_error(
        self, error: Exception, req: Request, *args, **kwargs
    ) -> NoReturn:
        raise WebargsHTTPException(
            400, exception=error, messages={"json": ["Invalid JSON body."]}
        )

    def get_request_from_view_args(self, view: Callable, args: tuple, kwargs: dict) -> Request:
        """Get request object from a handler function or method. Used internally by
        ``use_args`` and ``use_kwargs``.
        """
        req = None
        for arg in args:
            if isinstance(arg, Request):
                req = arg
                break
        assert isinstance(req, Request), "Request argument not found for handler"
        return req

    def handle_error(
        self,
        error: ValidationError,
        req: Request,
        schema: Schema,
        error_status_code: int | None,
        error_headers: dict | None,
    ) -> NoReturn:
        """Handles errors during parsing. Aborts the current HTTP request and
        responds with a 422 error.
        """
        status_code = error_status_code or self.DEFAULT_VALIDATION_STATUS
        raise HTTPRequestProcessingError(
            message="Handles errors during parsing. Aborts the current HTTP request",
            details=". ".join(error.messages),
            exception=error,
            schema=schema,
            headers=error_headers,
            status_code=status_code
        )


parser = StarletteParser()

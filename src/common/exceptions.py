# pylint: disable=unused-argument
# noinspection PyUnresolvedReferences
from starlette_web.common.http.exceptions import (
    BaseApplicationError,
    UnexpectedError,
    NotSupportedError,
    HttpError,
    AuthenticationFailedError,
    AuthenticationRequiredError,
    SignatureExpiredError,
    PermissionDeniedError,
    NotFoundError,
    MethodNotAllowedError,
    InviteTokenInvalidationError,
    InvalidResponseError,
    MaxAttemptsReached,
)
from starlette_web.common.http.statuses import ResponseStatus


class S3UploadingError(BaseApplicationError):
    message = "Couldn't upload file to the storage"


class InvalidRequestError(BaseApplicationError):
    status_code = 400
    message = "Requested data is not valid."
    response_status = ResponseStatus.INVALID_PARAMETERS


class SendRequestError(BaseApplicationError):
    status_code = 503
    message = "Got unexpected error for sending request."
    request_url = ""
    response_status = ResponseStatus.SERVICE_COMMUNICATION_ERROR

    def __init__(self, message: str, details: str, request_url: str):
        super().__init__(details, message)
        self.request_url = request_url

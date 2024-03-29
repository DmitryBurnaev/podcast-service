from typing import TYPE_CHECKING

from common.statuses import ResponseStatus

if TYPE_CHECKING:
    from modules.podcast.tasks.base import TaskResultCode


class BaseApplicationError(Exception):
    message = "Something went wrong"
    details: str | dict = None
    status_code = 500
    response_status = ResponseStatus.INTERNAL_ERROR

    def __init__(
        self,
        details: str | dict = None,
        message: str = None,
        status_code: int = None,
        response_status: str = None,
    ):
        self.message = message or self.message
        self.details = details or self.details
        self.status_code = status_code or self.status_code
        self.response_status = response_status or self.response_status


class ImproperlyConfiguredError(BaseApplicationError):
    message = "Required settings are not provided for requested action"


class DBError(BaseApplicationError):
    message = "Some error with DB communication"


class UnexpectedError(BaseApplicationError):
    message = "Something unexpected happened."


class NotSupportedError(BaseApplicationError):
    message = "Requested action is not supported now"


class S3UploadingError(BaseApplicationError):
    message = "Couldn't upload file to the storage"


class HttpError(BaseApplicationError):
    message = "Some HTTP error happened."


class AuthenticationFailedError(BaseApplicationError):
    status_code = 401
    response_status = ResponseStatus.AUTH_FAILED
    message = "Authentication credentials are invalid."


class AuthenticationRequiredError(BaseApplicationError):
    status_code = 401
    response_status = ResponseStatus.MISSED_CREDENTIALS
    message = "Authentication is required."


class SignatureExpiredError(BaseApplicationError):
    status_code = 401
    response_status = ResponseStatus.SIGNATURE_EXPIRED
    message = "Authentication credentials are invalid."


class PermissionDeniedError(BaseApplicationError):
    status_code = 403
    message = "You don't have permission to perform this action."
    response_status = ResponseStatus.FORBIDDEN


class NotFoundError(BaseApplicationError):
    status_code = 404
    message = "Requested object not found."
    response_status = ResponseStatus.NOT_FOUND


class MethodNotAllowedError(BaseApplicationError):
    status_code = 405
    message = "Requested method is not allowed."
    response_status = ResponseStatus.NOT_ALLOWED


class InviteTokenInvalidationError(BaseApplicationError):
    status_code = 401
    message = "Requested token is expired or does not exist."
    response_status = ResponseStatus.INVITE_ERROR


class InvalidRequestError(BaseApplicationError):
    status_code = 400
    message = "Requested data is not valid."
    response_status = ResponseStatus.INVALID_PARAMETERS


class InvalidResponseError(BaseApplicationError):
    status_code = 500
    message = "Response data couldn't be serialized."


class SendRequestError(BaseApplicationError):
    status_code = 503
    message = "Got unexpected error for sending request."
    request_url = ""
    response_status = ResponseStatus.COMMUNICATION_ERROR

    def __init__(self, message: str, details: str, request_url: str):
        super().__init__(details, message)
        self.request_url = request_url


class MaxAttemptsReached(BaseApplicationError):
    status_code = 503
    message = "Reached max attempt to make action"


class EmailSendingError(BaseApplicationError):
    status_code = 503
    message = "Couldn't send email to recipient"
    response_status = ResponseStatus.COMMUNICATION_ERROR


class UserCancellationError(BaseApplicationError):
    message = "Current processing was interrupted"


class DownloadingInterrupted(Exception):
    def __init__(self, code: "TaskResultCode", message: str = ""):
        self.code = code
        self.message = message

    def __repr__(self):
        return f'DownloadingInterrupted({self.code.name}, "{self.message}")'

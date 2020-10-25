class BaseApplicationError(Exception):
    message = "Something went wrong"
    details = None
    status_code = 500

    def __init__(self, details=None,  message=None, status_code=None):
        self.message = message or self.message
        self.details = details or self.details
        self.status_code = status_code or self.status_code


class UnexpectedError(BaseApplicationError):
    message = "Something unexpected happened"


class HttpError(BaseApplicationError):
    message = "Some HTTP error"


class AuthenticationFailedError(BaseApplicationError):
    status_code = 401
    message = "Authentication credentials are invalid"


class AuthenticationRequiredError(BaseApplicationError):
    status_code = 401
    message = "Authentication is required"


class PermissionDeniedError(BaseApplicationError):
    status_code = 403
    message = "You don't have permission to perform this action."


class NotFoundError(BaseApplicationError):
    status_code = 404
    message = "Requested object not found."


class InviteTokenInvalidationError(BaseApplicationError):
    status_code = 401
    message = "Requested token is expired or does not exist."


class InvalidParameterError(BaseApplicationError):
    status_code = 400
    message = "Requested data is not valid."


class InvalidResponseError(BaseApplicationError):
    status_code = 500
    message = "Response data couldn't be serialized."


class Forbidden(BaseApplicationError):
    status_code = 403
    message = "You don't have permission to perform this action"


class YoutubeFetchError(BaseApplicationError):
    ...


class SendRequestError(BaseApplicationError):
    status_code = 503
    message = "Got unexpected error for sending request."
    request_url = ""
    response_status = None

    def __init__(self, message: str, details: str, request_url: str, response_status: int):
        super().__init__(details, message)
        self.response_status = response_status
        self.request_url = request_url

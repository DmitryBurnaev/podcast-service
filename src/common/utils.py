import uuid
import asyncio
import logging
import logging.config
from pathlib import Path
from typing import Optional, Coroutine, Any

import httpx
import aioredis
from starlette import status
from starlette.responses import JSONResponse
from webargs_starlette import WebargsHTTPException

from core import settings
from common.typing import T
from common.statuses import ResponseStatus
from common.exceptions import SendRequestError, BaseApplicationError, NotFoundError


def get_logger(name: str = None):
    """Getting configured logger"""
    return logging.getLogger(name or "app")


def status_is_success(code):
    return 200 <= code <= 299


def status_is_server_error(code):
    return 500 <= code <= 600


async def send_email(recipient_email: str, subject: str, html_content: str):
    """Allows to send email via Sendgrid API"""

    request_url = f"https://api.sendgrid.com/{settings.SENDGRID_API_VERSION}/mail/send"
    request_data = {
        "personalizations": [{"to": [{"email": recipient_email}], "subject": subject}],
        "from": {"email": settings.EMAIL_FROM},
        "content": [{"type": "text/html", "value": html_content}],
    }
    request_header = {"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"}
    request_logger = get_logger(__name__)
    request_logger.info("Send request to %s. Data: %s", request_url, request_data)

    async with httpx.AsyncClient() as client:
        response = await client.post(request_url, json=request_data, headers=request_header)
        status_code = response.status_code
        if not status_is_success(status_code):
            response_text = response.json()
            raise SendRequestError(
                message=f"Couldn't send email to {recipient_email}",
                details=f"Got status code: {status_code}; response text: {response_text}",
                request_url=request_url,
            )

        request_logger.info("Email sent to %s. Status code: %s", recipient_email, status_code)


def log_message(exc, error_data, level=logging.ERROR):
    """
    Helps to log caught errors by exception handler
    """
    logger = get_logger(__name__)

    error_details = {
        "error": error_data.get("error", "Unbound exception"),
        "details": error_data.get("details", str(exc)),
    }
    message = "{exc.__class__.__name__} '{error}': [{details}]".format(exc=exc, **error_details)
    logger.log(level, message, exc_info=(level == logging.ERROR))


def custom_exception_handler(_, exc):
    """
    Returns the response that should be used for any given exception.
    Response will be formatted by our format: {"error": "text", "detail": details}
    """
    error_message = "Something went wrong!"
    error_details = f"Raised Error: {exc.__class__.__name__}"
    status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    response_status = ResponseStatus.INTERNAL_ERROR
    if isinstance(exc, BaseApplicationError):
        error_message = exc.message
        error_details = exc.details
        response_status = exc.response_status

    elif isinstance(exc, WebargsHTTPException):
        error_message = "Requested data is not valid."
        error_details = exc.messages.get("json") or exc.messages.get("form") or exc.messages
        status_code = status.HTTP_400_BAD_REQUEST
        response_status = ResponseStatus.INVALID_PARAMETERS

    payload = {"error": error_message}
    if settings.APP_DEBUG or response_status == ResponseStatus.INVALID_PARAMETERS:
        payload["details"] = error_details

    response_data = {"status": response_status, "payload": payload}
    log_level = logging.ERROR if status_is_server_error(status_code) else logging.WARNING
    log_message(exc, response_data["payload"], log_level)
    return JSONResponse(response_data, status_code=status_code)


def cut_string(source_string: str, max_length: int, finish_seq: str = "...") -> str:
    """
    Allows to limit source_string and append required sequence

    >>> cut_string('Some long string', max_length=13)
    'Some long ...'
    >>> cut_string('Some long string', max_length=8, finish_seq="***")
    'Some ***'
    >>> cut_string('Some long string', max_length=1)
    ''
    """
    if len(source_string) > max_length:
        slice_length = max_length - len(finish_seq)
        return source_string[:slice_length] + finish_seq if (slice_length > 0) else ""

    return source_string


async def download_content(url: str, file_ext: str, retries: int = 5) -> Optional[Path]:
    """Allows fetching content from url"""

    logger = get_logger(__name__)
    logger.debug(f"Send request to %s", url)
    result_content = None
    while retries := (retries - 1):
        async with httpx.AsyncClient() as client:
            await asyncio.sleep(0.1)
            try:
                response = await client.get(url, timeout=600)
            except Exception as exc:
                logger.warning(f"Couldn't download %s! Error: %r", url, exc)
                continue

            if response.status_code == status.HTTP_404_NOT_FOUND:
                raise NotFoundError(f"Resource not found by URL {url}!")

            if not 200 <= response.status_code <= 299:
                logger.warning(
                    f"Couldn't download %s | status: %s | response: %s",
                    url, response.status_code, response.text
                )
                continue

            result_content = response.content

    if not result_content:
        raise NotFoundError(f"Couldn't download url {url} after {retries} retries.")

    path = settings.TMP_PATH / f"{uuid.uuid4().hex}.{file_ext}"
    with open(path, "wb") as file:
        file.write(result_content)

    return path


def create_task(
    coroutine: Coroutine[Any, Any, T],
    logger: logging.Logger,
    error_message: str = "",
    error_message_message_args: tuple[Any, ...] = (),
) -> asyncio.Task[T]:
    """Creates asyncio.Task from coro and provides logging for any exceptions"""

    def handle_task_result(cover_task: asyncio.Task) -> None:
        """Logging any exceptions after task finished"""
        try:
            cover_task.result()
        except asyncio.CancelledError:
            # Task cancellation should not be logged as an error.
            pass
        except Exception as exc:  # pylint: disable=broad-except
            if error_message:
                logger.exception(error_message, *error_message_message_args)
            else:
                logger.exception(f"Couldn't complete {coroutine.__name__}: %r", exc)

    task = asyncio.create_task(coroutine)
    task.add_done_callback(handle_task_result)
    return task


async def publish_message_to_redis_pubsub(
    message: str,
    channel: str = settings.REDIS_PROGRESS_PUBSUB_CH,
):
    pub = aioredis.Redis(**settings.REDIS)
    await pub.publish(channel, message)

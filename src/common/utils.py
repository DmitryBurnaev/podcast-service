import uuid
import asyncio
import logging
import logging.config
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Coroutine, Any
from email.mime.text import MIMEText

import httpx
import aiosmtplib
from starlette import status
from starlette.responses import JSONResponse
from aiosmtplib import SMTPException
from webargs_starlette import WebargsHTTPException

from core import settings
from common.typing import T
from common.statuses import ResponseStatus
from common.exceptions import (
    BaseApplicationError,
    NotFoundError,
    EmailSendingError,
    ImproperlyConfiguredError,
)

logger = logging.getLogger(__name__)


def status_is_success(code):
    return 200 <= code <= 299


def status_is_server_error(code):
    return 500 <= code <= 600


async def send_email(recipient_email: str, subject: str, html_content: str):
    """Allows to send email via Sendgrid API"""

    logger.debug("Sending email to: %s | subject: '%s'", recipient_email, subject)
    required_settings = (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
    )
    if not all(getattr(settings, settings_name) for settings_name in required_settings):
        raise ImproperlyConfiguredError(
            f"SMTP settings: {required_settings} must be set for sending email"
        )

    smtp_client = aiosmtplib.SMTP(
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        use_tls=settings.SMTP_USE_TLS,
        start_tls=settings.SMTP_STARTTLS,
        username=settings.SMTP_USERNAME,
        password=str(settings.SMTP_PASSWORD),
    )

    message = MIMEMultipart("alternative")
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(html_content, "html"))

    async with smtp_client:
        try:
            smtp_details, smtp_status = await smtp_client.send_message(message)
        except SMTPException as exc:
            details = f"Couldn't send email: recipient: {recipient_email} | exc: {exc!r}"
            raise EmailSendingError(details=details) from exc

    if "OK" not in str(smtp_status):
        details = f"Couldn't send email: {recipient_email=} | {smtp_status=} | {smtp_details=}"
        raise EmailSendingError(details=details)

    logger.info("Email sent to %s | subject: %s", recipient_email, subject)


def log_message(exc, error_data, level=logging.ERROR):
    """
    Helps to log caught errors by exception handler
    """
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


async def download_content(
    url: str, file_ext: str, retries: int = 5, sleep_retry: float = 0.1
) -> Path | None:
    """Allows fetching content from url"""

    logger.debug("Send request to %s", url)
    result_content = None
    retries += 1
    while retries := (retries - 1):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=600)
            except Exception as exc:
                logger.warning("Couldn't download %s! Error: %r", url, exc)
                await asyncio.sleep(sleep_retry)
                continue

            if response.status_code == status.HTTP_404_NOT_FOUND:
                raise NotFoundError(f"Resource not found by URL {url}!")

            if not 200 <= response.status_code <= 299:
                logger.warning(
                    "Couldn't download %s | status: %s | response: %s",
                    url,
                    response.status_code,
                    response.text,
                )
                await asyncio.sleep(sleep_retry)
                continue

            result_content = response.content
            break

    if not result_content:
        raise NotFoundError(f"Couldn't download url {url} after {retries} retries.")

    path = settings.TMP_PATH / f"{uuid.uuid4().hex}.{file_ext}"
    with open(path, "wb") as file:
        file.write(result_content)

    return path


def create_task(
    coroutine: Coroutine[Any, Any, T],
    log_instance: logging.Logger,
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
                log_instance.exception(error_message, *error_message_message_args)
            else:
                log_instance.exception(f"Couldn't complete {coroutine.__name__}: %r", exc)

    task = asyncio.create_task(coroutine)
    task.add_done_callback(handle_task_result)
    return task

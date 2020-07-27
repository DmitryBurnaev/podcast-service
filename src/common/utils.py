import logging
import logging.config

import httpx
from starlette.responses import JSONResponse

from core import settings
from common.excpetions import SendRequestError


def get_logger(name: str = None):
    """ Getting configured logger """
    logging.config.dictConfig(settings.LOGGING)
    return logging.getLogger(name or "app")


def status_is_success(code):
    return 200 <= code <= 299


async def send_email(recipient_email: str, subject: str, html_content: str):
    """ Allows to send email via Sendgrid API """

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
            response_text = await response.json()
            raise SendRequestError(
                f"Couldn't send email to {recipient_email}",
                f"Got status code: {status_code}; response text: {response_text}",
                response_status=status_code,
                request_url=request_url,
            )
        else:
            request_logger.info("Email sent to %s. Status code: %s", recipient_email, status_code)


async def http_exception(request, exc):
    return JSONResponse({"error": exc.message, "details": exc.details}, status_code=exc.status_code)
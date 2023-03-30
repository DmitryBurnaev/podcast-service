import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

import aiosmtplib
import pytest

from common.exceptions import EmailSendingError, ImproperlyConfiguredError
from common.utils import send_email
from core import settings

pytestmark = pytest.mark.asyncio

SENDGRID_URL = f"https://api.sendgrid.com/{settings.SENDGRID_API_VERSION}/mail/send"
RECIPIENT_EMAIL = "test@test.com"
SUBJECT = "Test Email"
CONTENT = "<head>Test Content</head>"


async def test_send_email__success(mocked_smtp_sender):
    mocked_smtp_sender.send_message.return_value = ({}, "OK")
    with patch.object(logging.Logger, "info") as mock_logger:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    test_message = MIMEMultipart("alternative")
    test_message["From"] = settings.SMTP_FROM_EMAIL
    test_message["To"] = RECIPIENT_EMAIL
    test_message["Subject"] = SUBJECT
    test_message.attach(MIMEText(CONTENT))

    mocked_smtp_sender.send_message.assert_awaited_with(test_message)
    mocked_smtp_sender.target_class.__init__.assert_called_with(
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        use_tls=settings.SMTP_USE_TLS,
        start_tls=settings.SMTP_STARTTLS,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
    )
    mock_logger.assert_called_with("Email sent to %s | subject: %s", RECIPIENT_EMAIL, SUBJECT)


async def test_send_email__sending_problem(mocked_smtp_sender):
    mocked_smtp_sender.send_message.return_value = (
        {RECIPIENT_EMAIL: (550, "User unknown")}, "Some problem detected"
    )
    with pytest.raises(EmailSendingError) as exc:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    smtp_details = {RECIPIENT_EMAIL: (550, "User unknown")}
    assert f"{smtp_details=}" in exc.value.args


async def test_send_email__smtp_failed(mocked_smtp_sender):
    mocked_smtp_sender.send_message.side_effect = aiosmtplib.SMTPException("Some problem detected")
    with pytest.raises(EmailSendingError) as exc:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    assert exc.value.details == f"Couldn't send email: recipient: {RECIPIENT_EMAIL} | exc: {exc!r}"
    mocked_smtp_sender.send_message.assert_awaited()


@patch("core.settings.SMTP_HOST", "")
@patch("core.settings.SMTP_PORT", None)
async def test_send_email__required_params_not_specified():
    with pytest.raises(ImproperlyConfiguredError) as exc:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    assert exc.value.args == (
        "SMTP settings: "
        "('SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM_EMAIL') "
        "must be set for sending email",
    )


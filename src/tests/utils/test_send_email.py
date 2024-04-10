import logging
from unittest.mock import patch
from email.mime.multipart import MIMEMultipart

import aiosmtplib
import pytest

from core import settings
from common.utils import send_email
from common.exceptions import EmailSendingError, ImproperlyConfiguredError
from tests.mocks import MockSMTPSender

pytestmark = pytest.mark.asyncio

RECIPIENT_EMAIL = "test@test.com"
SUBJECT = "Test Email"
CONTENT = "<head>Test Content</head>"


@pytest.fixture
def smtp_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "test-smtp-host.com")
    monkeypatch.setattr(settings, "SMTP_PORT", "462")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "test-smtp-user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "test-smtp-pwd")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "test-from-email@test.com")


async def test_send_email__success(mocked_smtp_sender: MockSMTPSender, smtp_settings: None):
    mocked_smtp_sender.send_message.return_value = ({}, "OK")
    with patch.object(logging.Logger, "info") as mock_logger:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    mocked_smtp_sender.send_message.assert_awaited()
    (actual_sent_message,) = mocked_smtp_sender.send_message.call_args_list[0].args
    assert isinstance(actual_sent_message, MIMEMultipart)
    assert actual_sent_message["From"] == settings.SMTP_FROM_EMAIL
    assert actual_sent_message["To"] == RECIPIENT_EMAIL
    assert actual_sent_message["Subject"] == SUBJECT
    actual_payload = actual_sent_message.get_payload()[0].get_payload()
    assert actual_payload == CONTENT
    mocked_smtp_sender.target_class.__init__.assert_called_with(
        mocked_smtp_sender.target_obj,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        use_tls=settings.SMTP_USE_TLS,
        start_tls=settings.SMTP_STARTTLS,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
    )
    mock_logger.assert_called_with("Email sent to %s | subject: %s", RECIPIENT_EMAIL, SUBJECT)


async def test_send_email__sending_problem(mocked_smtp_sender: MockSMTPSender, smtp_settings: None):
    mocked_smtp_sender.send_message.return_value = (
        {RECIPIENT_EMAIL: (550, "User unknown")},
        "Some problem detected",
    )
    with pytest.raises(EmailSendingError) as exc:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    smtp_details = {RECIPIENT_EMAIL: (550, "User unknown")}
    assert f"{smtp_details=}" in exc.value.details


async def test_send_email__smtp_failed(mocked_smtp_sender: MockSMTPSender, smtp_settings: None):
    mocked_smtp_sender.send_message.side_effect = aiosmtplib.SMTPException("Some problem detected")
    with pytest.raises(EmailSendingError) as exc:
        await send_email(recipient_email=RECIPIENT_EMAIL, subject=SUBJECT, html_content=CONTENT)

    error = "SMTPException('Some problem detected')"
    assert exc.value.details == f"Couldn't send email: recipient: {RECIPIENT_EMAIL} | exc: {error}"
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

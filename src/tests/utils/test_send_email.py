import logging
from unittest.mock import patch

import pytest

from common.exceptions import SendRequestError
from common.utils import send_email
from core import settings
from tests.helpers import await_

SENDGRID_URL = f"https://api.sendgrid.com/{settings.SENDGRID_API_VERSION}/mail/send"
RECIPIENT_EMAIL = "test@test.com"


def test_send_email__success(mocked_httpx_client):
    mocked_httpx_client.post.return_value = mocked_httpx_client.Response(status_code=200, data={})
    subject = "Test Email"
    html_content = "<head>Test Content</head>"
    with patch.object(logging.Logger, "info") as mock_logger:
        await_(send_email(
            recipient_email=RECIPIENT_EMAIL, subject=subject, html_content=html_content
        ))

    mocked_httpx_client.post.assert_awaited_with(
        SENDGRID_URL,
        json={
            "personalizations": [{"to": [{"email": RECIPIENT_EMAIL}], "subject": subject}],
            "from": {"email": settings.EMAIL_FROM},
            "content": [{"type": "text/html", "value": html_content}],
        },
        headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"}
    )
    mock_logger.assert_called_with("Email sent to %s. Status code: %s", RECIPIENT_EMAIL, 200)


def test_send_email__failed(mocked_httpx_client):
    mocked_httpx_client.post.return_value = mocked_httpx_client.Response(
        status_code=400, data={"error": "Oops"}
    )

    with pytest.raises(SendRequestError) as err:
        await_(send_email(recipient_email=RECIPIENT_EMAIL, subject="Test Email", html_content=""))

    assert err.value.request_url == SENDGRID_URL
    assert err.value.message == f"Couldn't send email to {RECIPIENT_EMAIL}"
    assert err.value.details == "Got status code: 400; response text: {'error': 'Oops'}"

    mocked_httpx_client.post.assert_awaited_once()

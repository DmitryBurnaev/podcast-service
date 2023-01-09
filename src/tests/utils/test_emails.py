from common.utils import send_email
from tests.helpers import await_


def test_send_email__success(mocked_httpx_client):
    recipient = "test@test.com"
    subject = "Test Email"
    html_content = "<head>Test Content</head>"
    # TODO: mock httpx client
    await_(send_email(recipient_email=recipient, subject=subject, html_content=html_content))
    assert False

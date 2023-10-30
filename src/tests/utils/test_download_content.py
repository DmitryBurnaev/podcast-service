import os.path
import logging
from unittest.mock import patch

import pytest

from common.exceptions import NotFoundError
from common.utils import download_content
from tests.mocks import MockHTTPXClient

pytestmark = pytest.mark.asyncio

TEST_FILE_URL = "http://test.path-to-file.com/image.jpg"


async def test_download_content__ok(mocked_httpx_client: MockHTTPXClient):
    mocked_httpx_client.get.return_value = mocked_httpx_client.Response(
        status_code=200, data={"test": 123}
    )
    result_path = await download_content(url=TEST_FILE_URL, file_ext="jpg")

    assert os.path.exists(result_path)
    with open(result_path, "rb") as file:
        assert file.read() == b"{'test': 123}"

    mocked_httpx_client.get.assert_awaited_with(TEST_FILE_URL, timeout=600)
    os.remove(result_path)


async def test_download_content__unexpected_error(mocked_httpx_client: MockHTTPXClient):
    exc = RuntimeError("Oops")
    mocked_httpx_client.get.side_effect = exc
    with patch.object(logging.Logger, "warning") as mock_logger:
        with pytest.raises(NotFoundError) as mocked_exception:
            await download_content(url=TEST_FILE_URL, file_ext="jpg", retries=1, sleep_retry=0)

    mocked_exception.value.args = (f"Couldn't download url {TEST_FILE_URL} after 2 retries.",)
    mock_logger.assert_called_with("Couldn't download %s! Error: %r", TEST_FILE_URL, exc)


async def test_download_content__object_not_found(mocked_httpx_client: MockHTTPXClient):
    mocked_httpx_client.get.return_value = mocked_httpx_client.Response(
        status_code=404, data={"error": "NotFound"}
    )
    with pytest.raises(NotFoundError) as mocked_exception:
        await download_content(url=TEST_FILE_URL, file_ext="jpg", retries=1)

    mocked_exception.value.args = (f"Resource not found by URL {TEST_FILE_URL}!",)


async def test_download_content__not_success_response(mocked_httpx_client: MockHTTPXClient):
    mocked_httpx_client.get.return_value = mocked_httpx_client.Response(
        status_code=400, data={"error": "Oops"}
    )
    with patch.object(logging.Logger, "warning") as mocked_logger:
        with pytest.raises(NotFoundError):
            await download_content(url=TEST_FILE_URL, file_ext="jpg", retries=2, sleep_retry=0)

    mocked_logger.assert_called_with(
        "Couldn't download %s | status: %s | response: %s", TEST_FILE_URL, 400, "{'error': 'Oops'}"
    )
    assert mocked_logger.call_count == 2


async def test_download_content__missed_content(mocked_httpx_client: MockHTTPXClient):
    mocked_httpx_client.get.return_value = mocked_httpx_client.Response(status_code=200, data=None)
    with pytest.raises(NotFoundError) as mocked_exception:
        await download_content(url=TEST_FILE_URL, file_ext="jpg", retries=1)

    assert mocked_exception.value.args == (
        f"Couldn't download url {TEST_FILE_URL} after 1 retries.",
    )

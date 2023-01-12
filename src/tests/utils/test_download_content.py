import os.path

from common.utils import download_content
from tests.helpers import await_

TEST_FILE_URL = "http://test.path-to-file.com/image.jpg"


def test_download_content__ok(mocked_httpx_client):
    mocked_httpx_client.get.return_value = mocked_httpx_client.Response(
        status_code=200, data={"test": 123}
    )
    result_path = await_(download_content(url=TEST_FILE_URL, file_ext="jpg"))

    assert os.path.exists(result_path)
    with open(result_path, "rb") as file:
        assert file.read() == b"{'test': 123}"

    mocked_httpx_client.get.assert_awaited_with(TEST_FILE_URL, timeout=600)
    os.remove(result_path)

# TODO: add test with non-success paths

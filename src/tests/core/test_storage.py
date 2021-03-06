import logging
import os
from unittest.mock import Mock, patch
from urllib.parse import urljoin

import botocore
import botocore.exceptions

from common.storage import StorageS3
from core import settings

from tests.helpers import async_run


class MockedClient:
    class MyMock(Mock):
        __name__ = "my_mock"

    def __init__(self):
        self.upload_file = self.MyMock()
        self.head_object = self.MyMock()
        self.delete_object = self.MyMock()


def mock_upload_callback(*_, **__):
    ...


class TestS3Storage:
    @patch("boto3.session.Session.client")
    def test_upload_file__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()
        local_path = "/tmp/episode-sound.mp3"
        remote_dir = "/files-on-cloud/"
        remote_path = os.path.join(remote_dir, "episode-sound.mp3")

        with open(local_path, "wb") as file:
            file.write(b"Test data\n")

        mock_boto3_session_client.return_value = mock_client

        result_utl = StorageS3().upload_file(local_path, remote_dir, callback=mock_upload_callback)
        expected_url = urljoin(
            settings.S3_STORAGE_URL, os.path.join(settings.S3_BUCKET_NAME, remote_path)
        )
        assert result_utl == expected_url

        mock_boto3_session_client.assert_called_with(
            service_name="s3", endpoint_url=settings.S3_STORAGE_URL
        )
        mock_client.upload_file.assert_called_with(
            Filename=local_path,
            Bucket=settings.S3_BUCKET_NAME,
            Key=remote_path,
            Callback=mock_upload_callback,
            ExtraArgs={"ACL": "public-read", "ContentType": "audio/mpeg"},
        )

    @patch("boto3.session.Session.client")
    def test_upload_file__s3_client_error__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()

        mock_boto3_session_client.return_value = mock_client
        mock_client.upload_file.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Message": "Oops", "Code": "SideEffect"}}, operation_name="test error"
        )
        with patch.object(logging.Logger, "log") as mocked_logger:
            result_utl = StorageS3().upload_file("/tmp/episode-sound.mp3", "/dir-on-cloud/")
            assert result_utl is None

        error_msg = "An error occurred (SideEffect) when calling the test error operation: Oops"
        mocked_logger.assert_called_with(
            logging.ERROR,
            "Couldn't execute request (%s) to S3: ClientError %s",
            "my_mock",
            error_msg,
        )

    @patch("boto3.session.Session.client")
    def test_get_file_info__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()
        file_info = {"size": 123, "name": "test.mp3"}

        mock_boto3_session_client.return_value = mock_client
        mock_client.head_object.return_value = file_info
        actual_info = StorageS3().get_file_info("test.mp3", "remote-path")
        assert actual_info == file_info

        mock_boto3_session_client.assert_called_with(
            service_name="s3", endpoint_url=settings.S3_STORAGE_URL
        )
        mock_client.head_object.assert_called_with(
            Key="remote-path/test.mp3",
            Bucket=settings.S3_BUCKET_NAME,
        )

    @patch("boto3.session.Session.client")
    def test_get_file_size__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()
        test_size = 1234
        file_info = {"ResponseMetadata": {"HTTPHeaders": {"content-length": test_size}}}

        mock_boto3_session_client.return_value = mock_client
        mock_client.head_object.return_value = file_info
        actual_size = StorageS3().get_file_size("test.mp3", "remote-path")
        assert actual_size == test_size

        mock_client.head_object.assert_called_with(
            Key="remote-path/test.mp3",
            Bucket=settings.S3_BUCKET_NAME,
        )

    @patch("boto3.session.Session.client")
    def test_delete_file__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()

        mock_boto3_session_client.return_value = mock_client
        mock_client.delete_object.return_value = {"result": "OK"}
        result = StorageS3().delete_file("test.mp3", "remote-path")
        assert result == {"result": "OK"}

        mock_client.delete_object.assert_called_with(
            Key="remote-path/test.mp3",
            Bucket=settings.S3_BUCKET_NAME,
        )

    @patch("boto3.session.Session.client")
    def test_delete_files_async__ok(self, mock_boto3_session_client):
        mock_client = MockedClient()
        mock_boto3_session_client.return_value = mock_client
        async_run(StorageS3().delete_files_async(["test.mp3", "test2.mp3"], "remote-path"))

        expected_calls = [
            {"Key": "remote-path/test.mp3", "Bucket": "test-podcast-media"},
            {"Key": "remote-path/test2.mp3", "Bucket": "test-podcast-media"},
        ]
        actual_calls = [call.kwargs for call in mock_client.delete_object.call_args_list]
        assert actual_calls == expected_calls

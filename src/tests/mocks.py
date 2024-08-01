import dataclasses
import multiprocessing
import os
import shutil
import tempfile
from abc import ABC
from argparse import ArgumentParser
from pathlib import Path
from unittest.mock import Mock, AsyncMock

import rq
import httpx
import aiosmtplib
from yt_dlp import YoutubeDL

from common.encryption import SensitiveData
from common.enums import SourceType
from common.redis import RedisClient
from common.storage import StorageS3
from modules.auth.backend import LoginRequiredAuthBackend
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.tasks import GenerateRSSTask


class BaseMock:
    """Base class for class mocking

    # users class
    >>> class Vehicle:
    >>>    def run(self): ...

    # mock class
    >>> class MockVehicle(BaseMock):
    >>>     target_class = Vehicle
    >>>     def __init__(self):
    >>>         self.run = Mock(return_value=None)  # noqa

    """

    CODE_OK = 0
    target_obj = None

    @property
    def target_class(self):
        raise NotImplementedError

    def get_mocks(self):
        return [attr for attr, val in self.__dict__.items() if callable(val)]

    def mock_init(self, *args, **kwargs): ...


class BaseMockWithContextManager(BaseMock, ABC):
    def __init__(self):
        self.__aenter__ = AsyncMock(return_value=self)
        self.__aexit__ = AsyncMock(side_effect=self._process_exit)

    @staticmethod
    async def _process_exit(exc_type, exc_val, exc_tb):  # noqa
        if exc_val:
            raise exc_val


class MockYoutubeDL(BaseMock):
    target_class = YoutubeDL

    def __init__(self, *_, **__):
        from tests.helpers import get_source_id

        self.source_id = get_source_id()
        self.watch_url = f"https://www.youtube.com/watch?v={self.source_id}"
        self.thumbnail_url = f"https://test.thumbnails.com/image-{self.source_id}.com"
        self.download = Mock()
        self.extract_info = Mock(return_value=self.info)

    def mock_init(self, *args, **kwargs):
        class RequestDirector:
            close = Mock()

        self.target_obj.params = {}
        self.target_obj._request_director = RequestDirector()

    def assert_called_with(self, **kwargs):
        mock: Mock = self.target_class.__init__  # noqa
        assert mock.called
        try:
            mock_call_kwargs = mock.call_args_list[-1].args[1]
        except IndexError:
            raise AssertionError(f"Could not fetch call kwargs: {mock.call_args_list}")

        for key, value in kwargs.items():
            assert key in mock_call_kwargs, mock_call_kwargs
            assert mock_call_kwargs[key] == value

    @property
    def info(self) -> dict:
        return self.episode_info(source_type=SourceType.YOUTUBE)

    def episode_info(self, source_type: SourceType) -> dict:
        match source_type:
            case SourceType.YOUTUBE:
                return {
                    "id": self.source_id,
                    "title": "Test providers video",
                    "description": "Test providers video description",
                    "webpage_url": self.watch_url,
                    "thumbnail": self.thumbnail_url,
                    "thumbnails": [{"url": self.thumbnail_url}],
                    "uploader": "Test author",
                    "duration": 110,
                    "chapters": []
                }
            case SourceType.YANDEX:
                return {
                    "id": "123456",
                    "title": "Test providers audio",
                    "webpage_url": "http://path.to-track.com",
                    "thumbnail": self.thumbnail_url,
                    "thumbnails": [{"url": self.thumbnail_url}],
                    "duration": 110,
                    "playlist": "Playlist #1",
                    "playlist_index": 1,
                    "n_entries": 2,
                }


class MockRedisClient(BaseMock):
    target_class = RedisClient

    class PubSubChannel:
        def __init__(self):
            self.get_message = AsyncMock()
            self.subscribe = AsyncMock()
            self.unsubscribe = AsyncMock()
            self.close = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_, **__):
            pass

    def __init__(self, content=None):
        self._content = content or {}
        self.set = Mock()
        self.get = Mock(return_value=None)
        self.publish = Mock()
        self.async_set = AsyncMock()
        self.async_get = AsyncMock(return_value=None)
        self.async_get_many = AsyncMock(side_effect=lambda *_, **__: self._content)
        self.async_publish = AsyncMock()
        self.pubsub_channel = self.PubSubChannel()
        self.async_pubsub = Mock(return_value=self.pubsub_channel)


class MockS3Client(BaseMock):
    target_class = StorageS3
    tmp_upload_dir = Path(tempfile.mkdtemp(prefix="uploaded__"))

    def __init__(self):
        self.delete_file = Mock(return_value=self.CODE_OK)
        self.get_file_size = Mock(return_value=0)
        self.get_file_info = Mock(return_value={})
        self.get_file_size_async = AsyncMock(return_value=0)
        self.delete_files_async = AsyncMock(return_value=self.CODE_OK)
        self.upload_file = Mock(side_effect=self.upload_file_mock)
        self.copy_file = Mock(return_value="")
        self.upload_file_async = AsyncMock(return_value="")
        self.get_presigned_url = AsyncMock(return_value="https://s3.storage/link")

    def upload_file_mock(self, src_path: str | Path, *_, **__) -> str:
        target_path = self.get_mocked_remote_path(src_path)
        shutil.copy(src_path, target_path)
        return str(target_path)

    def get_mocked_remote_path(self, src_path: str | Path) -> str:
        return str(self.tmp_upload_dir / os.path.basename(src_path))


class MockEpisodeCreator(BaseMock):
    target_class = EpisodeCreator

    def __init__(self):
        self.create = AsyncMock(return_value=None)


class MockRQQueue(BaseMock):
    target_class = rq.Queue

    def __init__(self):
        self.enqueue = Mock(return_value=None)


class MockGenerateRSS(BaseMock):
    target_class = GenerateRSSTask

    def __init__(self):
        self.run = AsyncMock(return_value=self.CODE_OK)


class MockArgumentParser(BaseMock):
    target_class = ArgumentParser

    def __init__(self):
        self.parse_args = Mock()
        self.add_argument = Mock()


class MockProcess(BaseMock):
    target_class = multiprocessing.context.Process

    def __init__(self):
        self.start = Mock(return_value=None)
        self.terminate = Mock(return_value=None)
        self.__repr__ = Mock(return_value="TestProcess")


class MockAuthBackend(BaseMock):
    target_class = LoginRequiredAuthBackend

    def __init__(self):
        self.authenticate = AsyncMock(return_value=None)


class MockSensitiveData(BaseMock):
    target_class = SensitiveData

    def __init__(self):
        self.encrypt = Mock(return_value="encrypted_data")
        self.decrypt = Mock(return_value="decrypted_data")


class MockHTTPXClient(BaseMockWithContextManager):
    target_class = httpx.AsyncClient

    @dataclasses.dataclass
    class Response:
        status_code: int
        data: dict | None

        def json(self):
            return self.data

        @property
        def content(self) -> bytes:
            return str(self.data).encode("utf-8") if self.data else None

        @property
        def text(self) -> str:
            return str(self.json())

    def __init__(self):
        super().__init__()
        self.post = AsyncMock()
        self.get = AsyncMock()


class MockSMTPSender(BaseMockWithContextManager):
    target_class = aiosmtplib.SMTP

    def __init__(self):
        super().__init__()
        self.send_message = AsyncMock(return_value=None)

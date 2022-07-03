import asyncio
import multiprocessing
import os
import shutil
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from unittest.mock import Mock, AsyncMock

import rq
from youtube_dl import YoutubeDL

from common.enums import SourceType
from common.redis import RedisClient
from common.storage import StorageS3
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

    def mock_init(self, *args, **kwargs):
        ...

    @staticmethod
    def async_return(result):
        f = asyncio.Future()
        f.set_result(result)
        return f


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
        self.target_obj.params = {}

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

    def __init__(self, content=None):
        self._content = content or {}
        # TODO: refactor and use AsyncMock instead
        self.async_get_many = Mock(return_value=self.async_return(self._content))
        self.get = Mock()
        self.set = Mock()
        self.async_set = AsyncMock()
        self.async_get = AsyncMock(return_value=None)


class MockS3Client(BaseMock):
    target_class = StorageS3
    tmp_upload_dir = Path(tempfile.mkdtemp(prefix="uploaded__"))

    def __init__(self):
        self.delete_file = Mock(return_value=self.CODE_OK)
        self.get_file_size = Mock(return_value=0)
        self.get_file_info = Mock(return_value={})
        self.delete_files_async = AsyncMock(return_value=self.async_return(self.CODE_OK))
        self.upload_file = Mock(side_effect=self.upload_file_mock)
        self.upload_file_async = AsyncMock(return_value="")
        self.get_presigned_url = Mock(return_value=self.async_return("https://s3.storage/link"))

    def upload_file_mock(self, src_path, *_, **__):
        target_path = self.tmp_upload_dir / os.path.basename(src_path)
        shutil.copy(src_path, target_path)
        return str(target_path)


class MockEpisodeCreator(BaseMock):
    target_class = EpisodeCreator

    def __init__(self):
        self.create = Mock(return_value=self.async_return(None))


class MockRQQueue(BaseMock):
    target_class = rq.Queue

    def __init__(self):
        self.enqueue = Mock(return_value=None)


class MockGenerateRSS(BaseMock):
    target_class = GenerateRSSTask

    def __init__(self):
        self.run = Mock(return_value=self.async_return(self.CODE_OK))


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

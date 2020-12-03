import asyncio
import os
import shutil
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from unittest.mock import Mock

import rq
from youtube_dl import YoutubeDL

from common.redis import RedisClient
from common.storage import StorageS3
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.tasks import GenerateRSSTask


class BaseMock:
    """ Base class for class mocking

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
        from tests.integration.helpers import get_video_id
        self.video_id = get_video_id()
        self.watch_url = f"https://www.youtube.com/watch?v={self.video_id}"
        self.download = Mock()
        self.extract_info = Mock(return_value=self.info)

    def mock_init(self, *args, **kwargs):
        self.target_obj.params = {}

    @property
    def info(self, *_, **__):
        return {
            "id": self.video_id,
            "title": "Test youtube video",
            "description": "Test youtube video description",
            "webpage_url": self.watch_url,
            "thumbnail": "http://path.to-image.com",
            "thumbnails": [{"url": "http://path.to-image.com"}],
            "uploader": "Test author",
            "duration": 110,
        }


class MockRedisClient(BaseMock):
    target_class = RedisClient

    def __init__(self, content=None):
        self._content = content or {}
        self.async_get_many = Mock(return_value=self.async_return(self._content))


class MockS3Client(BaseMock):
    target_class = StorageS3
    tmp_upload_dir = Path(tempfile.mkdtemp(prefix="uploaded__"))

    def __init__(self):
        self.delete_file = Mock(return_value=self.CODE_OK)
        self.get_file_size = Mock(return_value=0)
        self.get_file_info = Mock(return_value={})
        self.delete_files_async = Mock(return_value=self.async_return(self.CODE_OK))
        self.upload_file = Mock(side_effect=self.upload_file_mock)

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

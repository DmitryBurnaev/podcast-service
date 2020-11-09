import asyncio
import json
import random
import time
import uuid
from typing import Tuple, Union
from unittest.mock import Mock
from hashlib import blake2b

import pytest
from alembic.config import main
from starlette.testclient import TestClient
from youtube_dl import YoutubeDL

from common.redis import RedisClient
from common.storage import StorageS3
from modules.auth.models import User
from modules.auth.utils import encode_jwt
from modules.podcast.models import Podcast
from modules.youtube import utils as youtube_utils
from .mocks import MockYoutube, MockRedisClient, MockS3Client


def get_user_data() -> Tuple[str, str]:
    return f"u_{uuid.uuid4().hex[:10]}@test.com", "password"


def video_id() -> str:
    """ Generate YouTube-like videoID """
    return blake2b(key=bytes(str(time.time()), encoding="utf-8"), digest_size=6).hexdigest()[:11]


@pytest.fixture()
def user_data() -> Tuple[str, str]:
    return get_user_data()


@pytest.fixture
def episode_data(podcast: Podcast, user: User) -> dict:
    source_id = video_id()
    episode_data = {
        "source_id": source_id,
        "podcast_id": podcast.id,
        "title": f"episode_{source_id}",
        "watch_url": f"fixture_url_{source_id}",
        "length": random.randint(1, 100),
        "description": f"description_{source_id}",
        "image_url": f"image_url_{source_id}",
        "file_name": f"file_name_{source_id}",
        "file_size": random.randint(1, 100),
        "author_id": None,
        "status": "new",
        "created_by_id": user.id,
    }
    return episode_data


@pytest.fixture
def mocked_youtube(monkeypatch) -> MockYoutube:
    mock_youtube = MockYoutube()
    monkeypatch.setattr(YoutubeDL, "__new__", lambda *_, **__: mock_youtube)  # noqa
    yield mock_youtube
    del mock_youtube


@pytest.fixture
def mocked_redis(monkeypatch) -> MockRedisClient:
    mock_redis_client = MockRedisClient()
    monkeypatch.setattr(RedisClient, "__new__", lambda *_, **__: mock_redis_client)  # noqa
    yield mock_redis_client
    del mock_redis_client


@pytest.fixture
def mocked_s3(monkeypatch) -> MockS3Client:
    mock_s3_client = MockS3Client()
    monkeypatch.setattr(StorageS3, "__new__", lambda *_, **__: mock_s3_client)  # noqa
    yield mock_s3_client
    del mock_s3_client


@pytest.fixture
def mocked_ffmpeg(monkeypatch) -> Mock:
    mocked_ffmpeg_function = Mock()
    monkeypatch.setattr(youtube_utils, "ffmpeg_preparation", mocked_ffmpeg_function)
    yield mocked_ffmpeg_function
    del mocked_ffmpeg_function


class PodcastTestClient(TestClient):

    def login(self, user: User):
        jwt, _ = encode_jwt({'user_id': user.id})
        self.headers["Authorization"] = f"Bearer {jwt}"


def create_user():
    email, password = get_user_data()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(User.create(email=email, password=password))


def get_podcast_data():
    uid = uuid.uuid4().hex
    return {
        'publish_id': uid[:32],
        'name': f"Podcast {uid}",
        'description': f"Description: {uid}",
        'rss_link': f"http://link-to-rss/{uid}",
        'image_url': f"http://link-to-image/{uid}"
    }


@pytest.fixture
def loop():
    return asyncio.get_event_loop()


@pytest.fixture
def user():
    return create_user()


@pytest.fixture
def podcast_data():
    return get_podcast_data()


@pytest.fixture
def podcast(podcast_data, user, loop):
    podcast_data["created_by_id"] = user.id
    return loop.run_until_complete(Podcast.create(**podcast_data))


@pytest.fixture(scope="session")
def client() -> PodcastTestClient:
    from core.app import get_app

    main(["--raiseerr", "upgrade", "head"])

    with PodcastTestClient(get_app()) as client:
        yield client

    main(["--raiseerr", "downgrade", "base"])

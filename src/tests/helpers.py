import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta
from hashlib import blake2b
from typing import Tuple, Type
from unittest import mock

from starlette.testclient import TestClient

from modules.auth.utils import encode_jwt
from modules.auth.models import User, UserSession
from modules.podcast.models import Podcast
from tests.mocks import BaseMock


class PodcastTestClient(TestClient):
    def login(self, user: User):
        user_session = create_user_session(user)
        jwt, _ = encode_jwt({"user_id": user.id})
        self.headers["Authorization"] = f"Bearer {jwt}"
        return user_session

    def logout(self):
        self.headers.pop("Authorization", None)


def mock_target_class(mock_class: Type[BaseMock], monkeypatch):
    """Allows to mock any classes (is used as fixture)

    # in conftest.py:
    >>> import pytest
    >>> @pytest.fixture
    >>> def mocked_vechicle(monkeypatch) -> MockVehicle: # noqa
    >>>     yield from mock_target_class(MockVehicle, monkeypatch) # noqa

    # in test.py:
    >>> def test_something(mocked_sender):
    >>>     mocked_vechicle.run.assert_called
    >>>     mocked_vechicle.target_class.__init__.assert_called
    """

    mock_obj = mock_class()

    def init_method(target_obj=None, *args, **kwargs):
        nonlocal mock_obj
        mock_obj.target_obj = target_obj
        mock_obj.mock_init(*args, **kwargs)

    with mock.patch.object(mock_class.target_class, "__init__", autospec=True) as init:
        init.side_effect = init_method
        for mock_method in mock_obj.get_mocks():
            monkeypatch.setattr(
                mock_class.target_class, mock_method, getattr(mock_obj, mock_method)
            )

        yield mock_obj

    del mock_obj


def get_user_data() -> Tuple[str, str]:
    return f"u_{uuid.uuid4().hex[:10]}@test.com", "password"


def get_video_id() -> str:
    """ Generate YouTube-like videoID """
    return blake2b(key=bytes(str(time.time()), encoding="utf-8"), digest_size=6).hexdigest()[:11]


def get_episode_data(podcast: Podcast = None, status: str = None, creator: User = None) -> dict:
    source_id = get_video_id()
    episode_data = {
        "source_id": source_id,
        "title": f"episode_{source_id}",
        "watch_url": f"https://www.youtube.com/watch?v={source_id}",
        "length": random.randint(1, 100),
        "description": f"description_{source_id}",
        "image_url": f"image_url_{source_id}",
        "file_name": f"file_name_{source_id}",
        "file_size": random.randint(1, 100),
        "author": None,
        "status": status or "new",
    }

    if podcast:
        episode_data["podcast_id"] = podcast.id

    if creator:
        episode_data["created_by_id"] = creator.id

    return episode_data


def create_user():
    email, password = get_user_data()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(User.create(email=email, password=password))


def create_user_session(user):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        UserSession.create(
            user_id=user.id,
            refresh_token="refresh-token",
            is_active=True,
            expired_at=datetime.utcnow() + timedelta(seconds=120),
            created_at=datetime.utcnow(),
            last_login=datetime.utcnow(),
        )
    )


def get_podcast_data(**kwargs):
    uid = uuid.uuid4().hex
    return {
        **{
            "publish_id": uid[:32],
            "name": f"Podcast {uid}",
            "description": f"Description: {uid}",
            "image_url": f"http://link-to-image/{uid}",
        },
        **kwargs,
    }


def async_run(coroutine):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coroutine)

import asyncio
import io
import random
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import blake2b
from typing import Tuple, Type, Optional
from unittest import mock

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from common.db_utils import make_session_maker
from common.enums import SourceType, FileType, EpisodeStatus
from common.request import PRequest
from modules.auth.utils import encode_jwt
from modules.auth.models import User, UserSession
from modules.media.models import File
from modules.podcast.models import Podcast, Episode
from tests.mocks import BaseMock


class PodcastTestClient(TestClient):
    db_session: AsyncSession = None

    def login(self, user: User):
        user_session = create_user_session(self.db_session, user)
        jwt, _ = encode_jwt({"user_id": user.id, "session_id": user_session.public_id})
        self.headers["Authorization"] = f"Bearer {jwt}"
        return user_session

    def logout(self):
        self.headers.pop("Authorization", None)


def await_(coroutine):
    """Run coroutine in the current event loop"""

    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coroutine)


def mock_target_class(mock_class: Type[BaseMock], monkeypatch):
    """Allows to mock any classes (is used as fixture)

    # in conftest.py:
    >>> import pytest
    >>> @pytest.fixture
    >>> def mocked_bicycle(monkeypatch) -> MockBicycle: # noqa
    >>>     yield from mock_target_class(MockBicycle, monkeypatch) # noqa

    # in test.py:
    >>> def test_something(mocked_sender):
    >>>     mocked_bicycle.run.assert_called
    >>>     mocked_bicycle.target_class.__init__.assert_called
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


def get_source_id(prefix: str = "") -> str:
    """Generate SourceID (ex.: youtube's video-id)"""
    sid = blake2b(key=bytes(str(time.time()), encoding="utf-8"), digest_size=6).hexdigest()[:11]
    if prefix:
        sid = f"{prefix}_{sid}"

    return sid


def get_episode_data(
    podcast: Podcast = None,
    status: EpisodeStatus = EpisodeStatus.NEW,
    creator: User = None,
    source_id: Optional[str] = None,
) -> dict:
    source_id = source_id or get_source_id()
    episode_data = {
        "source_id": source_id,
        "source_type": SourceType.YOUTUBE,
        "title": f"episode_{source_id}",
        "watch_url": f"https://www.youtube.com/watch?v={source_id}",
        "length": random.randint(1, 100),
        "description": f"description_{source_id}",
        "author": None,
        "status": status or EpisodeStatus.NEW,
    }

    if podcast:
        episode_data["podcast_id"] = podcast.id

    if creator:
        episode_data["owner_id"] = creator.id
    elif podcast:
        episode_data["owner_id"] = podcast.owner_id

    return episode_data


def get_podcast_data(**kwargs):
    uid = uuid.uuid4().hex
    podcast_data = {
        "publish_id": uid[:32],
        "name": f"Podcast {uid}",
        "description": f"Description: {uid}",
    }
    return podcast_data | kwargs


@contextmanager
def make_db_session(loop):
    session_maker = make_session_maker()
    async_session = session_maker()
    await_(async_session.__aenter__())
    yield async_session
    await_(async_session.__aexit__(None, None, None))


def create_user(db_session):
    email, password = get_user_data()
    return await_(User.async_create(db_session, db_commit=True, email=email, password=password))


def create_file(content: str | bytes) -> io.BytesIO:
    if not isinstance(content, bytes):
        content = content.encode()

    return io.BytesIO(content)


def create_user_session(db_session, user):
    return await_(
        UserSession.async_create(
            db_session,
            db_commit=True,
            user_id=user.id,
            public_id=str(uuid.uuid4()),
            refresh_token="refresh-token",
            is_active=True,
            expired_at=datetime.utcnow() + timedelta(seconds=120),
            created_at=datetime.utcnow(),
            refreshed_at=datetime.utcnow(),
        )
    )


def create_episode(
    db_session: AsyncSession,
    episode_data: dict,
    podcast: Podcast = None,
    status: Episode.Status = None,
    file_size: int = 0,
    source_id: str = None,
) -> Episode:
    source_id = source_id or episode_data.get("source_id") or get_source_id()
    status = status or episode_data.get("status") or Episode.Status.NEW
    audio_path = episode_data.pop("audio_path", "") or (
        f"/remote/path/to/audio/{source_id}.mp3" if status == Episode.Status.PUBLISHED else ""
    )
    podcast_id = podcast.id if podcast else episode_data["podcast_id"]
    _episode_data = episode_data | {
        "podcast_id": podcast_id,
        "source_id": source_id,
        "status": status,
    }

    owner_id = episode_data.get("owner_id") or (podcast.owner_id if podcast else None)
    audio = await_(
        File.create(
            db_session,
            FileType.AUDIO,
            owner_id=owner_id,
            path=audio_path,
            size=file_size,
            available=(status == Episode.Status.PUBLISHED),
        )
    )
    image = await_(
        File.create(
            db_session,
            FileType.IMAGE,
            owner_id=owner_id,
            path=f"images/ep_{source_id}_{uuid.uuid4().hex}.png",
            available=(status == Episode.Status.PUBLISHED),
        )
    )
    _episode_data["audio_id"] = audio.id
    _episode_data["image_id"] = image.id
    episode = await_(Episode.async_create(db_session, db_commit=True, **_episode_data))
    episode.audio = audio
    episode.image = image
    return episode


def prepare_request(db_session: AsyncSession, headers: dict = None, path: str = "/") -> PRequest:
    scope = {
        "path": path,
        "type": "http",
        "headers": [(h.lower().encode(), v.encode("latin-1")) for h, v in (headers or {}).items()],
    }
    request = PRequest(scope)
    request.db_session = db_session
    return request

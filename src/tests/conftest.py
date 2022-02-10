import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Tuple
from unittest.mock import Mock, patch, AsyncMock

import pytest
from alembic.config import main
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from modules.auth.models import UserInvite
from modules.podcast.models import Podcast, Episode, Cookie
from common.enums import SourceType
from modules.providers import utils as youtube_utils
from modules.providers.utils import SourceInfo
from tests.helpers import (
    PodcastTestClient,
    get_user_data,
    get_episode_data,
    create_user,
    get_podcast_data,
    mock_target_class,
    create_user_session,
    make_db_session,
)
from tests.mocks import (
    MockYoutubeDL,
    MockRedisClient,
    MockS3Client,
    MockEpisodeCreator,
    MockRQQueue,
    MockGenerateRSS,
    MockArgumentParser,
    MockProcess,
)


@pytest.fixture(autouse=True, scope="session")
def test_settings():
    settings.APP_DEBUG = True
    settings.MAX_UPLOAD_ATTEMPT = 1
    settings.RETRY_UPLOAD_TIMEOUT = 0


@pytest.fixture(autouse=True, scope="session")
def client() -> PodcastTestClient:
    from core.app import get_app

    with PodcastTestClient(get_app()) as client:
        with make_db_session(asyncio.get_event_loop()) as db_session:
            client.db_session = db_session
            yield client


@pytest.fixture
def dbs(loop) -> AsyncSession:
    with make_db_session(loop) as db_session:
        yield db_session


@pytest.fixture(autouse=True, scope="session")
def db_migration():
    ini_path = settings.PROJECT_ROOT_DIR / "alembic.ini"
    main(["--raiseerr", f"-c{ini_path}", "upgrade", "head"])


@pytest.fixture
def mocked_youtube(monkeypatch) -> MockYoutubeDL:
    yield from mock_target_class(MockYoutubeDL, monkeypatch)


@pytest.fixture(autouse=True)
def mocked_redis(monkeypatch) -> MockRedisClient:
    yield from mock_target_class(MockRedisClient, monkeypatch)


@pytest.fixture
def mocked_s3(monkeypatch) -> MockS3Client:
    yield from mock_target_class(MockS3Client, monkeypatch)


@pytest.fixture
def mocked_episode_creator(monkeypatch) -> MockEpisodeCreator:
    yield from mock_target_class(MockEpisodeCreator, monkeypatch)


@pytest.fixture(autouse=True)
def mocked_rq_queue(monkeypatch) -> MockRQQueue:
    yield from mock_target_class(MockRQQueue, monkeypatch)


@pytest.fixture
def mocked_generate_rss_task(monkeypatch) -> MockGenerateRSS:
    yield from mock_target_class(MockGenerateRSS, monkeypatch)


@pytest.fixture
def mocked_arg_parser(monkeypatch) -> MockArgumentParser:
    yield from mock_target_class(MockArgumentParser, monkeypatch)


@pytest.fixture
def mocked_process(monkeypatch) -> MockProcess:
    yield from mock_target_class(MockProcess, monkeypatch)


@pytest.fixture
def mocked_ffmpeg(monkeypatch) -> Mock:
    mocked_ffmpeg_function = Mock()
    monkeypatch.setattr(youtube_utils, "ffmpeg_preparation", mocked_ffmpeg_function)
    yield mocked_ffmpeg_function
    del mocked_ffmpeg_function


@pytest.fixture
def mocked_auth_send() -> AsyncMock:
    mocked_send_email = AsyncMock()
    patcher = patch("modules.auth.views.send_email", new=mocked_send_email)
    patcher.start()
    yield mocked_send_email
    del mocked_send_email
    patcher.stop()


@pytest.fixture()
def user_data() -> Tuple[str, str]:
    return get_user_data()


@pytest.fixture
def loop():
    return asyncio.get_event_loop()


@pytest.fixture
def user(dbs):
    return create_user(dbs)


@pytest.fixture
def user_session(user, loop, dbs):
    return create_user_session(dbs, user)


@pytest.fixture
def podcast_data():
    return get_podcast_data()


@pytest.fixture
def episode_data(podcast):
    return get_episode_data(podcast)


@pytest.fixture
def podcast(podcast_data, user, loop, dbs):
    podcast_data["created_by_id"] = user.id
    podcast = loop.run_until_complete(Podcast.async_create(dbs, **podcast_data))
    loop.run_until_complete(dbs.commit())
    return podcast


@pytest.fixture
def cookie(user, loop, dbs):
    cookie_data = {
        "source_type": SourceType.YANDEX,
        "data": "Cookie at netscape format\n",
        "created_by_id": user.id,
    }
    podcast = loop.run_until_complete(Cookie.async_create(dbs, **cookie_data))
    loop.run_until_complete(dbs.commit())
    return podcast


@pytest.fixture
def episode(podcast, user, loop, dbs) -> Episode:
    episode_data = get_episode_data(podcast, creator=user)
    episode = loop.run_until_complete(Episode.async_create(dbs, **episode_data))
    loop.run_until_complete(dbs.commit())
    return episode


@pytest.fixture
def user_invite(user, loop, dbs) -> UserInvite:
    return loop.run_until_complete(
        UserInvite.async_create(
            dbs,
            db_commit=True,
            email=f"user_{uuid.uuid4().hex[:10]}@test.com",
            token=f"{uuid.uuid4().hex}",
            expired_at=datetime.utcnow() + timedelta(days=1),
            created_by_id=user.id,
        )
    )


@pytest.fixture()
def mocked_source_info() -> Mock:
    mock = Mock()
    mock.return_value = SourceInfo(
        id="source-id",
        url="http://link.to.source/",
        type=SourceType.YANDEX,
    )
    patcher = patch("modules.providers.utils.extract_source_info", new=mock)
    patcher.start()
    yield mock
    del mock
    patcher.stop()

import uuid
import logging
import tempfile
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch, AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy
from sqlalchemy.engine import URL
from sqlalchemy.util import concurrency
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import ProgrammingError, OperationalError

from core import settings, database
from modules.auth.models import UserInvite, User, UserSession
from modules.media.models import File
from modules.podcast.models import Podcast, Episode, Cookie
from common.enums import SourceType, FileType
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
    await_,
    get_source_id,
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
    MockAuthBackend,
    MockHTTPXClient,
)


@pytest.fixture(autouse=True, scope="session")
def test_settings():
    settings.APP_DEBUG = True
    settings.MAX_UPLOAD_ATTEMPT = 1
    settings.MAX_UPLOAD_AUDIO_FILESIZE = 32
    settings.RETRY_UPLOAD_TIMEOUT = 0


@pytest.fixture(autouse=True)
def cap_log(caplog):
    # trying to print out logs for failed tests
    caplog.set_level(logging.INFO)
    logging.getLogger("modules").setLevel(logging.INFO)

#
# # TODO: use async fixt instead
# @pytest.fixture(autouse=True, scope="session")
# def client() -> PodcastTestClient:
#     from core.app import get_app
#
#     with PodcastTestClient(get_app()) as client:
#         with make_db_session() as db_session:
#             client.db_session = db_session
#             yield client


# TODO: turn-on autouse=True, scope="session" (for pytest-asyncio global mode may be?)
@pytest_asyncio.fixture
# @pytest_asyncio.fixture(autouse=True, scope="session")
async def client() -> PodcastTestClient:
    from core.app import get_app

    # TODO: support async with for PodcastTestClient
    with PodcastTestClient(get_app()) as client:
        async with make_db_session() as db_session:
            client.db_session = db_session
            yield client


@pytest.fixture
def dbs() -> AsyncSession:
    with make_db_session() as db_session:
        yield db_session


def db_prep():
    print("Dropping the old test db…")
    postgres_db_dsn = URL.create(
        drivername="postgresql",
        username=settings.DATABASE["username"],
        password=settings.DATABASE["password"],
        host=settings.DATABASE["host"],
        port=settings.DATABASE["port"],
        database="postgres",
    )
    engine = sqlalchemy.create_engine(postgres_db_dsn)
    conn = engine.connect()
    try:
        conn = conn.execution_options(autocommit=False)
        conn.execute("ROLLBACK")  # FIXME: it will be deprecated in SA 2.0
        conn.execute(f"DROP DATABASE {settings.DB_NAME}")
    except ProgrammingError:
        print("Could not drop the database, probably does not exist.")
        conn.execute("ROLLBACK")
    except OperationalError:
        print("Could not drop database because it’s being accessed by other users")
        conn.execute("ROLLBACK")

    print(f"Test db dropped! about to create {settings.DB_NAME}")
    conn.execute(f"CREATE DATABASE {settings.DB_NAME}")
    username, password = settings.DATABASE["username"], settings.DATABASE["password"]

    try:
        conn.execute(f"CREATE USER {username} WITH ENCRYPTED PASSWORD '{password}'")
    except Exception as e:
        print(f"User already exists. ({e})")
        conn.execute(f"GRANT ALL PRIVILEGES ON DATABASE {settings.DB_NAME} TO {username}")

    conn.close()


@pytest.fixture(autouse=True, scope="session")
def db_migration():
    def create_tables():
        db_prep()
        print("Creating tables...")
        engine = sqlalchemy.create_engine(settings.DATABASE_DSN)
        database.ModelBase.metadata.create_all(engine)

    await_(concurrency.greenlet_spawn(create_tables))
    print("DB and tables were successful created.")


@pytest.fixture
def mocked_youtube(monkeypatch) -> MockYoutubeDL:
    yield from mock_target_class(MockYoutubeDL, monkeypatch)


@pytest.fixture
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
def mocked_auth_backend(monkeypatch) -> MockAuthBackend:
    yield from mock_target_class(MockAuthBackend, monkeypatch)


@pytest.fixture
def mocked_httpx_client(monkeypatch) -> MockHTTPXClient:
    yield from mock_target_class(MockHTTPXClient, monkeypatch)


@pytest.fixture
def mocked_ffmpeg(monkeypatch) -> Mock:
    mocked_ffmpeg_function = Mock()
    monkeypatch.setattr(youtube_utils, "ffmpeg_preparation", mocked_ffmpeg_function)
    yield mocked_ffmpeg_function
    del mocked_ffmpeg_function


@pytest.fixture
def mocked_audio_metadata(monkeypatch) -> Mock:
    mocked_function = Mock()
    monkeypatch.setattr(youtube_utils, "audio_metadata", mocked_function)
    yield mocked_function
    del mocked_function


@pytest.fixture
def mocked_auth_send() -> AsyncMock:
    mocked_send_email = AsyncMock()
    patcher = patch("modules.auth.views.send_email", new=mocked_send_email)
    patcher.start()
    yield mocked_send_email
    del mocked_send_email
    patcher.stop()


@pytest.fixture
def user_data() -> tuple[str, str]:
    return get_user_data()


@pytest_asyncio.fixture
async def user(dbs) -> User:
    return await create_user(dbs)


# @pytest.fixture
# async def auser(dbs) -> User:
#     email, password = get_user_data()
#     return await User.async_create(dbs, db_commit=True, email=email, password=password)
#     # return await acreate_user(dbs)


@pytest_asyncio.fixture
async def user_session(user, dbs) -> UserSession:
    return await create_user_session(dbs, user)


# TODO: replace
# @pytest_asyncio.fixture
# async def async_user_session(user, dbs) -> UserSession:
#     return await create_user_session(dbs, user)
#

@pytest.fixture
def podcast_data() -> dict[str, Any]:
    return get_podcast_data()


@pytest.fixture
def episode_data(podcast) -> dict[str, Any]:
    return get_episode_data(podcast=podcast)


@pytest.fixture
def podcast(podcast_data, user, dbs) -> Podcast:
    podcast_data["owner_id"] = user.id
    publish_id = podcast_data["publish_id"]
    image = await_(
        File.create(
            dbs,
            FileType.IMAGE,
            owner_id=user.id,
            path=f"/remote/path/to/audio/podcast_{publish_id}_image.png",
            available=True,
            public=True,
        )
    )
    rss = await_(
        File.create(
            dbs,
            FileType.RSS,
            owner_id=user.id,
            path=f"/remote/path/to/rss/podcast_{publish_id}_rss.xml",
            available=True,
        )
    )
    podcast_data["image_id"] = image.id
    podcast_data["rss_id"] = rss.id
    podcast = await_(Podcast.async_create(dbs, **podcast_data))
    await_(dbs.commit())
    podcast.image = image
    podcast.rss = rss
    return podcast


@pytest.fixture
def cookie(user, dbs) -> Cookie:
    cookie_data = {
        "source_type": SourceType.YANDEX,
        "data": "Cookie at netscape format\n",
        "owner_id": user.id,
    }
    cookie = await_(Cookie.async_create(dbs, **cookie_data))
    await_(dbs.commit())
    return cookie


@pytest.fixture
def image_file(user, dbs) -> File:
    image = await_(
        File.create(
            dbs,
            FileType.IMAGE,
            owner_id=user.id,
            path="/remote/path/to/image_file.png",
            size=1,
        )
    )
    await_(dbs.commit())
    return image


@pytest.fixture
def rss_file(user, dbs) -> File:
    image = await_(
        File.create(
            dbs,
            FileType.RSS,
            owner_id=user.id,
            path="/remote/path/to/rss_file.xml",
        )
    )
    await_(dbs.commit())
    return image


@pytest.fixture
def episode(podcast, user, dbs) -> Episode:
    episode_data = get_episode_data(podcast=podcast, creator=user)
    source_id = get_source_id()
    audio = await_(
        File.create(
            dbs,
            FileType.AUDIO,
            owner_id=user.id,
            path=f"/remote/path/to/audio/episode_{source_id}_audio.mp3",
            available=True,
            size=1024,
        )
    )
    image = await_(
        File.create(
            dbs,
            FileType.IMAGE,
            owner_id=user.id,
            source_url=f"http://link.to.source-image/{source_id}.png",
            path=f"/remote/path/to/images/episode_{source_id}_image.png",
            available=True,
        )
    )
    episode_data["audio_id"] = audio.id
    episode_data["image_id"] = image.id
    episode = await_(Episode.async_create(dbs, **episode_data))
    await_(dbs.commit())
    episode.image = image
    episode.audio = audio
    return episode


@pytest.fixture
def user_invite(user, dbs) -> UserInvite:
    return await_(
        UserInvite.async_create(
            dbs,
            db_commit=True,
            email=f"user_{uuid.uuid4().hex[:10]}@test.com",
            token=f"{uuid.uuid4().hex}",
            expired_at=datetime.utcnow() + timedelta(days=1),
            owner_id=user.id,
        )
    )


@pytest.fixture
def tmp_file():
    content = b"test-file-content"
    with tempfile.NamedTemporaryFile() as f:
        f.write(content)
        f.content = content
        f.size = len(content)
        f.seek(0)
        yield f


def _mocked_source_info(monkeypatch, source_type) -> Mock:
    mock = Mock()
    mock.return_value = SourceInfo(
        id="source-id",
        url="http://link.to.source/",
        type=source_type,
    )
    monkeypatch.setattr(youtube_utils, "extract_source_info", mock)
    yield mock
    del mock


@pytest.fixture
def mocked_source_info_youtube(monkeypatch) -> Mock:
    yield from _mocked_source_info(monkeypatch, source_type=SourceType.YOUTUBE)


@pytest.fixture
def mocked_source_info_yandex(monkeypatch) -> Mock:
    yield from _mocked_source_info(monkeypatch, source_type=SourceType.YANDEX)


@pytest.fixture
def mocked_source_info_upload(monkeypatch) -> Mock:
    yield from _mocked_source_info(monkeypatch, source_type=SourceType.UPLOAD)

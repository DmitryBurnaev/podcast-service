from unittest.mock import Mock
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yt_dlp.utils import ExtractorError

from common.enums import SourceType, FileType
from modules.auth.models import User
from modules.media.models import File
from modules.providers.exceptions import SourceFetchError
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Podcast, Episode, Cookie, EpisodeChapter
from modules.providers.utils import SOURCE_CFG_MAP
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_podcast_data, create_user
from tests.mocks import MockYoutubeDL, MockSensitiveData

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

pytestmark = pytest.mark.asyncio


class TestEpisodeCreator(BaseTestAPIView):
    @staticmethod
    async def assert_files(dbs: AsyncSession, episode: Episode, new_episode: Episode):
        audio: File = await File.async_get(dbs, id=episode.audio_id)
        new_audio: File = await File.async_get(dbs, id=new_episode.audio_id)
        assert audio.type == new_audio.type
        assert audio.path == new_audio.path
        assert audio.size == new_audio.size
        assert audio.source_url == new_audio.source_url
        assert new_audio.available is False

        image: File = await File.async_get(dbs, id=episode.image_id)
        new_image: File = await File.async_get(dbs, id=new_episode.image_id)
        assert image.type == new_image.type
        assert image.path == new_image.path
        assert image.size == new_image.size
        assert image.source_url == new_image.source_url
        assert image.available == new_image.available

    async def test_episodes_created__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
    ):
        source_id = mocked_youtube.source_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=watch_url,
            user_id=user.id,
        )
        episode = await episode_creator.create()
        assert episode is not None
        assert episode.watch_url == watch_url
        assert episode.source_id == source_id
        assert episode.audio_id is not None
        assert episode.image_id is not None

        audio = await File.async_get(dbs, id=episode.audio_id)
        assert audio.type == FileType.AUDIO
        assert audio.source_url == watch_url
        assert audio.path == ""
        assert audio.available is False

        image = await File.async_get(dbs, id=episode.image_id)
        assert image.type == FileType.IMAGE
        assert image.source_url == mocked_youtube.thumbnail_url
        assert image.path == ""
        assert image.available is False
        assert image.public is True

    async def test_episodes_created__chapters_extracted__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
    ):

        mocked_episode_data = mocked_youtube.episode_info(source_type=SourceType.YOUTUBE) | {
            "chapters": [
                {"end_time": 19.0, "start_time": 0.0, "title": "Intro"},
                {"end_time": 110.0, "start_time": 20.0, "title": "Main Chapter"},
            ]
        }
        mocked_youtube.extract_info.return_value = mocked_episode_data

        source_id = mocked_youtube.source_id
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=f"https://www.youtube.com/watch?v={source_id}",
            user_id=user.id,
        )
        episode = await episode_creator.create()
        assert episode is not None
        assert episode.chapters == [
            {"title": "Intro", "start": 0, "end": 19},
            {"title": "Main Chapter", "start": 20, "end": 110},
        ]
        assert episode.list_chapters == [
            EpisodeChapter(title="Intro", start=0, end=19),
            EpisodeChapter(title="Main Chapter", start=20, end=110),
        ]

    async def test_episodes_created__skip_chapters_extracted__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
    ):

        mocked_episode_data = mocked_youtube.episode_info(source_type=SourceType.YOUTUBE) | {
            "chapters": None
        }
        mocked_youtube.extract_info.return_value = mocked_episode_data

        source_id = mocked_youtube.source_id
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=f"https://www.youtube.com/watch?v={source_id}",
            user_id=user.id,
        )
        episode = await episode_creator.create()
        assert episode is not None
        assert episode.chapters is None
        assert episode.list_chapters == []

    async def test_same_episode_in_podcast__ok(
        self,
        dbs: AsyncSession,
        user: User,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
    ):
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=episode.podcast_id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode = await episode_creator.create()
        assert new_episode is not None
        assert new_episode.id == episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == episode.watch_url

    async def test_same_episode_in_other_podcast__ok(
        self,
        dbs: AsyncSession,
        episode: Episode,
        user: User,
        mocked_youtube: MockYoutubeDL,
    ):
        mocked_youtube.extract_info.return_value = {
            "id": episode.source_id,
            "title": "Updated title",
            "description": "Updated description",
            "webpage_url": "https://new.watch.site/updated/",
            "thumbnail": "https://link.to.image/updated/",
            "uploader": "Updated author",
            "duration": 123,
        }
        new_podcast = await Podcast.async_create(dbs, db_commit=True, **get_podcast_data())
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=new_podcast.id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode: Episode = await episode_creator.create()
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == "https://new.watch.site/updated/"
        assert new_episode.title == "Updated title"
        assert new_episode.description == "Updated description"
        assert new_episode.author == "Updated author"
        assert new_episode.length == 123
        assert new_episode.audio_id is not None
        assert new_episode.image_id is not None

        await self.assert_files(dbs, episode, new_episode)

    async def test_same_episode__extract_failed__ok(
        self,
        dbs: AsyncSession,
        user: User,
        episode: Episode,
        mocked_youtube: MockYoutubeDL,
    ):
        mocked_youtube.extract_info.side_effect = ExtractorError("Something went wrong here")
        new_podcast = await Podcast.async_create(dbs, **get_podcast_data())
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=new_podcast.id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode: Episode = await episode_creator.create()
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == episode.watch_url

        await self.assert_files(dbs, episode, new_episode)

    async def test_extract_failed__fail(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        episode_data: dict,
        mocked_youtube: MockYoutubeDL,
    ):
        ydl_error = ExtractorError("Something went wrong here", video_id=episode_data["source_id"])
        mocked_youtube.extract_info.side_effect = ydl_error
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=episode_data["watch_url"],
            user_id=user.id,
        )
        with pytest.raises(SourceFetchError) as exc:
            await episode_creator.create()

        assert exc.value.details == f"Extracting data for new Episode failed: {ydl_error}"

    async def test_episodes_created__using_proxy__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
        monkeypatch: "MonkeyPatch",
    ):
        proxy_url = "socks5://socks5user:pass@socks5host:2080"
        monkeypatch.setattr(SOURCE_CFG_MAP[SourceType.YOUTUBE], "proxy_url", proxy_url)

        source_id = mocked_youtube.source_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=watch_url,
            user_id=user.id,
        )
        episode = await episode_creator.create()
        assert episode is not None
        mocked_youtube.assert_called_with(proxy=proxy_url)


class TestCreateEpisodesWithCookies(BaseTestAPIView):
    url = "/api/podcasts/{id}/episodes/"
    source_url = "http://link.to.source/"
    cdata = {"data": "cookie in netscape format", "source_type": SourceType.YANDEX}

    def _request(self, client, user, podcast) -> dict:
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": self.source_url})
        return self.assert_ok_response(response, status_code=201)

    @staticmethod
    async def _assert_source(episode_creator: EpisodeCreator, cookie_id: int | None = None):
        episode = await episode_creator.create()
        assert episode.source_id == "source-id"
        assert episode.source_type == SourceType.YANDEX
        assert episode.cookie_id == cookie_id

    async def test_specific_cookie(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
        mocked_source_info_yandex: Mock,
        mocked_sens_data: MockSensitiveData,
    ):
        cdata = self.cdata | {"owner_id": user.id}
        await Cookie.async_create(dbs, **(cdata | {"source_type": SourceType.YANDEX}))
        cookie_yandex = await Cookie.async_create(dbs, **cdata)

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )

        await self._assert_source(episode_creator, cookie_yandex.id)
        mocked_youtube.assert_called_with(cookiefile=await cookie_yandex.as_file())
        mocked_sens_data.decrypt.assert_called_with(self.cdata["data"])

    async def test_cookie_from_another_user(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
        mocked_source_info_yandex: Mock,
        mocked_sens_data: MockSensitiveData,
    ):
        cdata = self.cdata | {"owner_id": user.id}
        cookie_yandex = await Cookie.async_create(dbs, **cdata)
        cdata = self.cdata | {"owner_id": (await create_user(dbs)).id}
        await Cookie.async_create(dbs, **cdata)

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        await self._assert_source(episode_creator, cookie_yandex.id)
        mocked_youtube.assert_called_with(cookiefile=await cookie_yandex.as_file())
        mocked_sens_data.decrypt.assert_called_with(self.cdata["data"])

    async def test_use_last_cookie(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        mocked_youtube: MockYoutubeDL,
        mocked_source_info_yandex: Mock,
        mocked_sens_data: MockSensitiveData,
    ):
        cdata = self.cdata | {"owner_id": user.id}
        await Cookie.async_create(dbs, **cdata)
        c2 = await Cookie.async_create(dbs, **cdata)

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        await self._assert_source(episode_creator, c2.id)
        mocked_youtube.assert_called_with(cookiefile=await c2.as_file())
        mocked_sens_data.decrypt.assert_called_with(self.cdata["data"])

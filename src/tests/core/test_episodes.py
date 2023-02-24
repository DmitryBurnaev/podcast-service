import pytest
from yt_dlp.utils import ExtractorError

from common.enums import SourceType, FileType
from modules.media.models import File
from modules.providers.exceptions import SourceFetchError
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Podcast, Episode, Cookie
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_podcast_data, create_user

pytestmark = pytest.mark.asyncio


class TestEpisodeCreator(BaseTestAPIView):
    @staticmethod
    async def assert_files(dbs, episode: Episode, new_episode: Episode):
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

    async def test_ok(self, podcast, user, mocked_youtube, dbs):
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

    async def test_same_episode_in_podcast__ok(self, episode, user, mocked_youtube, dbs):
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

    async def test_same_episode_in_other_podcast__ok(self, episode, user, mocked_youtube, dbs):
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

    async def test_same_episode__extract_failed__ok(self, episode, user, mocked_youtube, dbs):
        mocked_youtube.extract_info.side_effect = ExtractorError("Something went wrong here")
        new_podcast = await Podcast.async_create(dbs, **get_podcast_data())
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=new_podcast.id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode: Episode = await (episode_creator.create())
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == episode.watch_url

        await self.assert_files(dbs, episode, new_episode)

    async def test_extract_failed__fail(self, podcast, episode_data, user, mocked_youtube, dbs):
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
        self, mocked_source_info_yandex, mocked_youtube, dbs, user, podcast
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
        mocked_youtube.assert_called_with(cookiefile=await (cookie_yandex.as_file()))

    async def test_cookie_from_another_user(
        self, mocked_source_info_yandex, mocked_youtube, dbs, user, podcast
    ):
        cdata = self.cdata | {"owner_id": user.id}
        cookie_yandex = await Cookie.async_create(dbs, **cdata)
        cdata = self.cdata | {"owner_id": (await create_user(dbs)).id}
        await (Cookie.async_create(dbs, **cdata))

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        await self._assert_source(episode_creator, cookie_yandex.id)
        mocked_youtube.assert_called_with(cookiefile=await (cookie_yandex.as_file()))

    async def test_use_last_cookie(
        self, mocked_source_info_yandex, mocked_youtube, dbs, user, podcast
    ):
        cdata = self.cdata | {"owner_id": user.id}
        await (Cookie.async_create(dbs, **cdata))
        c2 = await (Cookie.async_create(dbs, **cdata))

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        await self._assert_source(episode_creator, c2.id)
        mocked_youtube.assert_called_with(cookiefile=await (c2.as_file()))

from typing import Optional

import pytest
from youtube_dl.utils import ExtractorError

from common.enums import SourceType
from modules.providers.exceptions import SourceFetchError
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Podcast, Episode, Cookie
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_podcast_data, await_, create_user


class TestEpisodeCreator(BaseTestAPIView):
    def test_ok(self, podcast, user, mocked_youtube, dbs):
        source_id = mocked_youtube.video_id
        watch_url = f"https://www.youtube.com/watch?v={source_id}"
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=watch_url,
            user_id=user.id,
        )
        episode = await_(episode_creator.create())
        assert episode is not None
        assert episode.watch_url == watch_url
        assert episode.source_id == source_id

    def test_same_episode_in_podcast__ok(self, podcast, episode, user, mocked_youtube, dbs):
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=episode.podcast_id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode = await_(episode_creator.create())
        assert new_episode is not None
        assert new_episode.id == episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == episode.watch_url

    def test_same_episode_in_other_podcast__ok(
        self, podcast, episode, user, mocked_youtube, dbs
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
        new_podcast = await_(Podcast.async_create(dbs, db_commit=True, **get_podcast_data()))
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=new_podcast.id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode: Episode = await_(episode_creator.create())
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == "https://new.watch.site/updated/"
        assert new_episode.title == "Updated title"
        assert new_episode.description == "Updated description"
        assert new_episode.image_url == "https://link.to.image/updated/"
        assert new_episode.author == "Updated author"
        assert new_episode.length == 123

    def test_same_episode__extract_failed__ok(
        self, podcast, episode, user, mocked_youtube, dbs
    ):
        mocked_youtube.extract_info.side_effect = ExtractorError("Something went wrong here")
        new_podcast = await_(Podcast.async_create(dbs, **get_podcast_data()))
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=new_podcast.id,
            source_url=episode.watch_url,
            user_id=user.id,
        )
        new_episode: Episode = await_(episode_creator.create())
        assert episode is not None
        assert new_episode.id != episode.id
        assert new_episode.source_id == episode.source_id
        assert new_episode.watch_url == episode.watch_url

    def test_extract_failed__fail(self, podcast, episode_data, user, mocked_youtube, dbs):
        ydl_error = ExtractorError("Something went wrong here", video_id=episode_data["source_id"])
        mocked_youtube.extract_info.side_effect = ydl_error
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=episode_data["watch_url"],
            user_id=user.id,
        )
        with pytest.raises(SourceFetchError) as error:
            await_(episode_creator.create())

        assert error.value.details == f"Extracting data for new Episode failed: {ydl_error}"


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
    def assert_source(episode_creator: EpisodeCreator, cookie_id: Optional[int] = None):
        episode = await_(episode_creator.create())
        assert episode.source_id == "source-id"
        assert episode.source_type == SourceType.YANDEX
        assert episode.cookie_id == cookie_id

    def test_specific_cookie(self, mocked_source_info, mocked_youtube, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        await_(Cookie.async_create(dbs, **(cdata | {"source_type": SourceType.YANDEX})))
        cookie_yandex = await_(Cookie.async_create(dbs, **cdata))

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )

        self.assert_source(episode_creator, cookie_yandex.id)
        # TODO: use assert method for this
        assert mocked_youtube.target_class.__init__.call_args.args[1]['cookiefile'] == cookie_yandex.as_file()
        # self.assert_called_with(mocked_youtube.target_class.__init__, cookiefile=cookie_yandex.as_file())

    def test_cookie_from_another_user(self, mocked_source_info, mocked_youtube, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        cookie_yandex = await_(Cookie.async_create(dbs, **cdata))
        cdata = self.cdata | {"created_by_id": create_user(dbs).id}
        await_(Cookie.async_create(dbs, **cdata))

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        self.assert_source(episode_creator, cookie_yandex.id)
        mocked_youtube.extract_info.assert_called_with(self.source_url, download=False, cookiefile=cookie_yandex.as_file())

    def test_use_last_cookie(self, mocked_source_info, mocked_youtube, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        await_(Cookie.async_create(dbs, **cdata))
        c2 = await_(Cookie.async_create(dbs, **cdata))

        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=self.source_url,
            user_id=user.id,
        )
        self.assert_source(episode_creator, c2.id)
        mocked_youtube.extract_info.assert_called_with(self.source_url, download=False, cookiefile=cookie_yandex.as_file())

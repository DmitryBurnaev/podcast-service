import pytest
from youtube_dl.utils import ExtractorError

from modules.youtube.exceptions import YoutubeFetchError
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Podcast, Episode
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_podcast_data, await_


class TestEpisodeCreator(BaseTestAPIView):
    def test_create__ok(self, podcast, user, mocked_youtube, dbs):
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

    def test_create__same_episode_in_podcast__ok(
        self, podcast, episode, user, mocked_youtube, dbs
    ):
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

    def test_create__same_episode_in_other_podcast__ok(
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

    def test_create__same_episode__extract_failed__ok(
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

    def test_create__extract_failed__fail(self, podcast, episode_data, user, mocked_youtube,
                                          dbs):
        ydl_error = ExtractorError("Something went wrong here", video_id=episode_data["source_id"])
        mocked_youtube.extract_info.side_effect = ydl_error
        episode_creator = EpisodeCreator(
            dbs,
            podcast_id=podcast.id,
            source_url=episode_data["watch_url"],
            user_id=user.id,
        )
        with pytest.raises(YoutubeFetchError) as error:
            await_(episode_creator.create())

        assert error.value.details == f"Extracting data for new Episode failed: {ydl_error}"

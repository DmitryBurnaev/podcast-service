import asyncio
from unittest.mock import patch

import pytest

from core import settings
from modules.podcast.models import Podcast, Episode
from common.enums import EpisodeStatus
from tests.api.test_base import BaseTestWSAPI
from tests.helpers import (
    create_user,
    create_episode,
    get_episode_data,
    get_podcast_data,
    create_user_session,
)

MB_1 = 1 * 1024 * 1024
MB_2 = 2 * 1024 * 1024
MB_4 = 4 * 1024 * 1024
STATUS = Episode.Status

pytestmark = pytest.mark.asyncio


def _episode_in_progress(
    podcast: Podcast,
    episode: Episode,
    current_size: int,
    completed: float,
    total_file_size: int | None = None,
    status: EpisodeStatus = EpisodeStatus.DL_EPISODE_DOWNLOADING,
):
    return {
        "status": str(status),
        "episode": {
            "id": episode.id,
            "title": episode.title,
            "image_url": episode.image_url,
            "status": str(episode.status),
        },
        "podcast": {
            "id": podcast.id,
            "name": podcast.name,
            "image_url": podcast.image_url,
        },
        "current_file_size": current_size,
        "total_file_size": episode.audio.size if total_file_size is None else total_file_size,
        "completed": completed,
    }


def _redis_key(filename: str) -> str:
    return filename.partition(".")[0]


class TestProgressAPIView(BaseTestWSAPI):
    url = "/ws/progress/"

    async def test_no_items(self, client, user_session, mocked_redis):
        response = self._ws_request(client, user_session)
        assert response == {"progressItems": []}

    async def test_filter_by_status__ok(self, client, user_session, episode_data, mocked_redis, dbs):
        user_id = user_session.user_id
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_id))
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_id))

        episode_data["owner_id"] = user_id
        episode_data["source_id"] = None  # should be regenerated for each new episode

        p1_ep_new = await create_episode(dbs, episode_data, podcast_1, STATUS.NEW, MB_1)
        p1_ep_down = await create_episode(dbs, episode_data, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_ep_down = await create_episode(dbs, episode_data, podcast_2, STATUS.DOWNLOADING, MB_4)
        await create_episode(dbs, episode_data, podcast_2, STATUS.NEW, MB_1)

        mocked_redis.async_get_many.side_effect = lambda *_, **__: (
            {
                _redis_key(p1_ep_new.audio_filename): {
                    "status": EpisodeStatus.DL_PENDING,
                    "processed_bytes": 0,
                    "total_bytes": MB_1,
                },
                _redis_key(p1_ep_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                _redis_key(p2_ep_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )
        response_data = self._ws_request(client, user_session)
        progress_items = response_data["progressItems"]
        assert len(progress_items) == 2, progress_items
        assert progress_items[0] == (
            _episode_in_progress(podcast_2, p2_ep_down, current_size=MB_1, completed=25.0)
        )
        assert progress_items[1] == (
            _episode_in_progress(podcast_1, p1_ep_down, current_size=MB_1, completed=50.0)
        )

    async def test_filter_by_user__ok(self, client, episode_data, mocked_redis, dbs):
        user_1 = await create_user(dbs)
        user_2 = await create_user(dbs)

        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_1.id))
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_2.id))

        ep_data_1 = get_episode_data(creator=user_1)
        ep_data_2 = get_episode_data(creator=user_2)
        p1_ep_down = await create_episode(dbs, ep_data_1, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_ep_down = await create_episode(dbs, ep_data_2, podcast_2, STATUS.DOWNLOADING, MB_4)

        await (dbs.commit())

        mocked_redis.async_get_many.side_effect = lambda *_, **__: (
            {
                _redis_key(p1_ep_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                _redis_key(p2_ep_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )

        user_session = await create_user_session(dbs, user_1)
        response_data = self._ws_request(client, user_session)
        progress_items = response_data["progressItems"]
        assert progress_items == [
            _episode_in_progress(podcast_1, p1_ep_down, current_size=MB_1, completed=50.0),
        ]


class TestEpisodeInProgressWSAPI(BaseTestWSAPI):
    url = "/ws/progress/"

    async def test_single_episode__ok(self, client, user, user_session, podcast, mocked_redis, dbs):
        ep_data_1 = get_episode_data(creator=user)
        ep_data_2 = get_episode_data(creator=user)
        episode_1 = await create_episode(dbs, ep_data_1, podcast, STATUS.DOWNLOADING, MB_2)
        episode_2 = await create_episode(dbs, ep_data_2, podcast, STATUS.DOWNLOADING, MB_4)
        await dbs.commit()

        mocked_redis.async_get_many.side_effect = lambda *_, **__: (
            {
                _redis_key(episode_1.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                _redis_key(episode_2.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )
        response_data = self._ws_request(client, user_session, data={"episodeID": episode_1.id})
        progress_items = response_data["progressItems"]
        assert progress_items == [
            _episode_in_progress(podcast, episode_1, current_size=MB_1, completed=50.0),
        ]

    async def test_single_episode__pubsub_ok(
        self, client, user, user_session, podcast, mocked_redis, dbs
    ):
        mocked_redis.pubsub_channel.get_message.side_effect = {
            "data": settings.REDIS_PROGRESS_PUBSUB_SIGNAL
        }

        ep_data_1 = get_episode_data(creator=user)
        episode_1 = await create_episode(dbs, ep_data_1, podcast, STATUS.DOWNLOADING, MB_2)
        await dbs.commit()

        mocked_redis.async_get_many.side_effect = lambda *_, **__: {
            _redis_key(episode_1.audio_filename): {
                "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                "processed_bytes": MB_1,
                "total_bytes": MB_2,
            },
        }
        response_data = self._ws_request(client, user_session, data={"episodeID": episode_1.id})
        progress_items = response_data["progressItems"]
        assert progress_items == [
            _episode_in_progress(podcast, episode_1, current_size=MB_1, completed=50.0),
        ]
        mocked_redis.pubsub_channel.subscribe.assert_awaited_with(settings.REDIS_PROGRESS_PUBSUB_CH)

    @patch("modules.podcast.views.progress.ProgressWS._send_progress_for_episodes")
    async def test_single_episode__pubsub_timeout(
        self, _, client, user_session, mocked_redis, dbs
    ):
        mocked_redis.pubsub_channel.get_message.side_effect = asyncio.TimeoutError()

        response_data = self._ws_request(client, user_session, data={"episodeID": 1})

        assert response_data == {"errorDetails": "Couldn't retrieve progress message"}
        mocked_redis.pubsub_channel.subscribe.assert_awaited_with(settings.REDIS_PROGRESS_PUBSUB_CH)
        mocked_redis.pubsub_channel.unsubscribe.assert_awaited_with(
            settings.REDIS_PROGRESS_PUBSUB_CH
        )
        mocked_redis.pubsub_channel.close.assert_awaited_once()

    @pytest.mark.parametrize(
        "episode_status, progress_status",
        (
            (EpisodeStatus.NEW, EpisodeStatus.DL_PENDING),
            (EpisodeStatus.DOWNLOADING, EpisodeStatus.DL_PENDING),
            (EpisodeStatus.ERROR, EpisodeStatus.ERROR),
        ),
    )
    async def test_single_episode__no_progress_data__ok(
        self,
        dbs,
        client,
        podcast,
        episode,
        user_session,
        mocked_redis,
        episode_status,
        progress_status,
    ):
        mocked_redis.async_get_many.return_value = lambda *_, **__: {}
        await episode.update(dbs, status=episode_status, db_commit=True)

        response_data = self._ws_request(client, user_session, data={"episodeID": episode.id})
        assert response_data == {
            "progressItems": [
                _episode_in_progress(
                    podcast,
                    episode,
                    current_size=0,
                    completed=0,
                    total_file_size=0,
                    status=progress_status,
                )
            ]
        }
        expected_redis_key = episode.audio_filename.removesuffix(".mp3")
        mocked_redis.async_get_many.assert_awaited_with({expected_redis_key}, pkey="event_key")

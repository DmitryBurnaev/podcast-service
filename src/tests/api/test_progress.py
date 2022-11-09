from modules.podcast.models import Podcast, Episode
from common.enums import EpisodeStatus
from tests.api.test_base import BaseTestWSAPI
from tests.helpers import (
    await_,
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


def _progress(
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


def _episode_progress(
    episode: Episode,
    current_size: int,
    completed: float,
    total_file_size: int,
    status: EpisodeStatus = EpisodeStatus.DL_EPISODE_DOWNLOADING,
):
    return {
        "status": str(status),
        "current_file_size": current_size,
        "total_file_size": total_file_size,
        "completed": completed,
        "episode": {
            "id": episode.id,
            "title": episode.title,
            "image_url": episode.image_url,
            "status": str(episode.status),
        },
    }


def _redis_key(filename: str) -> str:
    return filename.partition(".")[0]


class TestProgressAPIView(BaseTestWSAPI):
    url = "/ws/progress/"

    def test_no_items(self, client, user_session):
        response = self._ws_request(client, user_session)
        assert response == {"progressItems": []}

    def test_filter_by_status__ok(self, client, user_session, episode_data, mocked_redis, dbs):
        user_id = user_session.user_id
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user_id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user_id)))

        episode_data["owner_id"] = user_id
        episode_data["source_id"] = None  # should be regenerated for each new episode

        p1_episode_new = create_episode(dbs, episode_data, podcast_1, STATUS.NEW, MB_1)
        p1_episode_down = create_episode(dbs, episode_data, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = create_episode(dbs, episode_data, podcast_2, STATUS.DOWNLOADING, MB_4)
        # p2_episode_new
        create_episode(dbs, episode_data, podcast_2, STATUS.NEW, MB_1)

        mocked_redis.async_get_many.side_effect = lambda *_, **__: (
            {
                _redis_key(p1_episode_new.audio_filename): {
                    "status": EpisodeStatus.DL_PENDING,
                    "processed_bytes": 0,
                    "total_bytes": MB_1,
                },
                _redis_key(p1_episode_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                _redis_key(p2_episode_down.audio_filename): {
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
            _progress(podcast_2, p2_episode_down, current_size=MB_1, completed=25.0)
        )
        assert progress_items[1] == (
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0)
        )

    def test_filter_by_user__ok(self, client, episode_data, mocked_redis, dbs):
        user_1 = create_user(dbs)
        user_2 = create_user(dbs)

        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user_1.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user_2.id)))

        ep_data_1 = get_episode_data(creator=user_1)
        ep_data_2 = get_episode_data(creator=user_2)
        p1_episode_down = create_episode(dbs, ep_data_1, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = create_episode(dbs, ep_data_2, podcast_2, STATUS.DOWNLOADING, MB_4)

        await_(dbs.commit())

        mocked_redis.async_get_many.side_effect = lambda *_, **__: (
            {
                _redis_key(p1_episode_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                _redis_key(p2_episode_down.audio_filename): {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )

        user_session = create_user_session(dbs, user_1)
        response_data = self._ws_request(client, user_session)
        progress_items = response_data["progressItems"]
        assert progress_items == [
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0),
        ]


class TestEpisodeInProgressWSAPI(BaseTestWSAPI):
    url = "/ws/progress/episodes/"

    def test_progress__ok(self, dbs, client, podcast, episode, user_session, mocked_redis):
        await_(episode.update(dbs, status=EpisodeStatus.DOWNLOADING))
        await_(dbs.commit())
        processed_bytes = int(episode.audio.size / 2)
        total_bytes = episode.audio.size
        mocked_redis.async_get_many.side_effect = lambda *_, **__: {
            _redis_key(episode.audio_filename): {
                "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                "processed_bytes": processed_bytes,
                "total_bytes": total_bytes,
            },
        }

        response_data = self._ws_request(client, user_session, data={"episodeID": episode.id})
        assert response_data == _episode_progress(
            episode,
            current_size=processed_bytes,
            completed=50.0,
            total_file_size=total_bytes,
        )
        expected_redis_key = episode.audio_filename.removesuffix(".mp3")
        mocked_redis.async_get_many.assert_awaited_with({expected_redis_key}, pkey="event_key")

    def test_progress__episode_not_in_progress__ok(
        self, dbs, user_session, client, episode, mocked_redis
    ):
        await_(episode.update(dbs, status=EpisodeStatus.NEW))
        await_(dbs.commit())

        response_data = self._ws_request(client, user_session, data={"episodeID": episode.id})
        assert response_data == {
            "episode": {
                "id": episode.id,
                "title": episode.title,
                "image_url": episode.image_url,
                "status": str(episode.status),
            }
        }
        mocked_redis.async_get_many.assert_not_awaited()

    def test_progress__no_progress_data__ok(
        self, dbs, client, podcast, episode, user_session, mocked_redis
    ):
        mocked_redis.async_get_many.return_value = lambda *_, **__: {}
        await_(episode.update(dbs, status=EpisodeStatus.DOWNLOADING))
        await_(dbs.commit())

        response_data = self._ws_request(client, user_session, data={"episodeID": episode.id})
        assert response_data == _episode_progress(
            episode,
            current_size=0,
            completed=0,
            total_file_size=0,
            status=EpisodeStatus.DL_PENDING,
        )
        expected_redis_key = episode.audio_filename.removesuffix(".mp3")
        mocked_redis.async_get_many.assert_awaited_with({expected_redis_key}, pkey="event_key")

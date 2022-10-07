from modules.podcast.models import Podcast, Episode
from common.enums import EpisodeStatus
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_episode_data, create_user, get_podcast_data, await_, create_episode

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


class TestProgressAPIView(BaseTestAPIView):
    url = "/api/progress/"

    def test_filter_by_status__ok(self, client, user, episode_data, mocked_redis, dbs):
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))

        episode_data["owner_id"] = user.id
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
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert len(response_data) == 2, response_data
        assert response_data[0] == (
            _progress(podcast_2, p2_episode_down, current_size=MB_1, completed=25.0)
        )
        assert response_data[1] == (
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
        client.login(user_1)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0),
        ]


class TestEpisodeProgressAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/progress/"

    def test_get_progress__ok(self, dbs, client, podcast, episode, user, mocked_redis):
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

        client.login(user)
        response = client.get(url=self.url.format(id=episode.id))
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_progress(
            episode,
            current_size=processed_bytes,
            completed=50.0,
            total_file_size=total_bytes,
        )
        expected_redis_key = episode.audio_filename.removesuffix(".mp3")
        mocked_redis.async_get_many.assert_awaited_with({expected_redis_key}, pkey="event_key")

    def test_get_progress__episode_not_in_progress__ok(
        self, dbs, user, client, episode, mocked_redis
    ):
        await_(episode.update(dbs, status=EpisodeStatus.NEW))
        await_(dbs.commit())

        client.login(user)
        response = client.get(url=self.url.format(id=episode.id))
        response_data = self.assert_ok_response(response)
        assert response_data == {}
        mocked_redis.async_get_many.assert_not_awaited()

    def test_get_progress__no_progress_data__ok(
        self, dbs, client, podcast, episode, user, mocked_redis
    ):
        mocked_redis.async_get_many.return_value = lambda *_, **__: {}
        await_(episode.update(dbs, status=EpisodeStatus.DOWNLOADING))
        await_(dbs.commit())

        client.login(user)
        response = client.get(url=self.url.format(id=episode.id))
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_progress(
            episode,
            current_size=0,
            completed=0,
            total_file_size=0,
            status=EpisodeStatus.DL_PENDING,
        )
        expected_redis_key = episode.audio_filename.removesuffix(".mp3")
        mocked_redis.async_get_many.assert_awaited_with({expected_redis_key}, pkey="event_key")

from modules.podcast.models import Podcast, Episode, EpisodeStatus
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_episode_data, create_user, get_podcast_data, await_, create_episode

MB_1 = 1 * 1024 * 1024
MB_2 = 2 * 1024 * 1024
MB_4 = 4 * 1024 * 1024
STATUS = Episode.Status


def _progress(podcast: Podcast, episode: Episode, current_size: int, completed: float):
    return {
        "status": str(EpisodeStatus.DL_EPISODE_DOWNLOADING),
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
        "total_file_size": episode.file_size,
        "completed": completed,
    }


class TestProgressAPIView(BaseTestAPIView):
    url = "/api/progress/"

    def test_filter_by_status__ok(self, client, user, episode_data, mocked_redis, dbs):
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user.id)))

        episode_data["created_by_id"] = user.id
        p1_episode_new = create_episode(dbs, episode_data, podcast_1, STATUS.NEW, MB_1)
        p1_episode_down = create_episode(dbs, episode_data, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = create_episode(dbs, episode_data, podcast_2, STATUS.DOWNLOADING, MB_4)
        # p2_episode_new
        create_episode(dbs, episode_data, podcast_2, STATUS.NEW, MB_1)

        mocked_redis.async_get_many.return_value = mocked_redis.async_return(
            {
                p1_episode_new.file_name.partition(".")[0]: {
                    "status": EpisodeStatus.DL_PENDING,
                    "processed_bytes": 0,
                    "total_bytes": MB_1,
                },
                p1_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                p2_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [
            _progress(podcast_2, p2_episode_down, current_size=MB_1, completed=25.0),
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0),
        ]

    def test_filter_by_user__ok(self, client, episode_data, mocked_redis, dbs):
        user_1 = create_user(dbs)
        user_2 = create_user(dbs)

        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user_1.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user_2.id)))

        ep_data_1 = get_episode_data(creator=user_1)
        ep_data_2 = get_episode_data(creator=user_2)
        p1_episode_down = create_episode(dbs, ep_data_1, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = create_episode(dbs, ep_data_2, podcast_2, STATUS.DOWNLOADING, MB_4)

        await_(dbs.commit())

        mocked_redis.async_get_many.return_value = mocked_redis.async_return(
            {
                p1_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatus.DL_EPISODE_DOWNLOADING,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                p2_episode_down.file_name.partition(".")[0]: {
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

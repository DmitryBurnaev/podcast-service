from modules.podcast.models import Podcast, Episode
from modules.podcast.utils import EpisodeStatuses
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_episode_data, create_user, get_podcast_data

MB_1 = 1 * 1024 * 1024
MB_2 = 2 * 1024 * 1024
MB_4 = 4 * 1024 * 1024
STATUS = Episode.Status


def _progress(podcast: Podcast, episode: Episode, current_size: int, completed: float):
    return {
        "status": str(EpisodeStatuses.episode_downloading),
        "status_display": "Downloading",
        "episode_id": episode.id,
        "episode_title": episode.title,
        "podcast_id": episode.podcast_id,
        "podcast_publish_id": podcast.publish_id,
        "current_file_size": current_size,
        "total_file_size": episode.file_size,
        "completed": completed,
    }


class TestProgressAPIView(BaseTestAPIView):
    url = "/api/progress/"

    def test_filter_by_status__ok(self, client, user, episode_data, mocked_redis):
        podcast_1 = self.async_run(Podcast.create(**get_podcast_data(created_by_id=user.id)))
        podcast_2 = self.async_run(Podcast.create(**get_podcast_data(created_by_id=user.id)))

        episode_data["created_by_id"] = user.id
        p1_episode_new = self._create_episode(episode_data, podcast_1, STATUS.NEW, MB_1)
        p1_episode_down = self._create_episode(episode_data, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = self._create_episode(episode_data, podcast_2, STATUS.DOWNLOADING, MB_4)
        # p2_episode_new
        self._create_episode(episode_data, podcast_2, STATUS.NEW, MB_1)

        mocked_redis.async_get_many.return_value = mocked_redis.async_return(
            {
                p1_episode_new.file_name.partition(".")[0]: {
                    "status": EpisodeStatuses.pending,
                    "processed_bytes": 0,
                    "total_bytes": MB_1,
                },
                p1_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatuses.episode_downloading,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                p2_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatuses.episode_downloading,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )
        client.login(user)
        response = client.get(self.url)
        assert response.status_code == 200, f"Progress API is not available: {response.json()}"
        assert response.json() == [
            _progress(podcast_2, p2_episode_down, current_size=MB_1, completed=25.0),
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0),
        ]

    def test_filter_by_user__ok(self, client, episode_data, mocked_redis):
        user_1 = create_user()
        user_2 = create_user()

        podcast_1 = self.async_run(Podcast.create(**get_podcast_data(created_by_id=user_1.id)))
        podcast_2 = self.async_run(Podcast.create(**get_podcast_data(created_by_id=user_2.id)))

        ep_data_1 = get_episode_data(creator=user_1)
        ep_data_2 = get_episode_data(creator=user_2)
        p1_episode_down = self._create_episode(ep_data_1, podcast_1, STATUS.DOWNLOADING, MB_2)
        p2_episode_down = self._create_episode(ep_data_2, podcast_2, STATUS.DOWNLOADING, MB_4)

        mocked_redis.async_get_many.return_value = mocked_redis.async_return(
            {
                p1_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatuses.episode_downloading,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_2,
                },
                p2_episode_down.file_name.partition(".")[0]: {
                    "status": EpisodeStatuses.episode_downloading,
                    "processed_bytes": MB_1,
                    "total_bytes": MB_4,
                },
            }
        )
        client.login(user_1)
        response = client.get(self.url)
        assert response.status_code == 200, f"Progress API is not available: {response.json()}"
        assert response.json() == [
            _progress(podcast_1, p1_episode_down, current_size=MB_1, completed=50.0),
        ]

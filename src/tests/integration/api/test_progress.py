from modules.podcast.models import Podcast, Episode
from modules.podcast.utils import EpisodeStatuses
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import video_id, get_user_data, create_user, get_podcast_data


class TestProgressAPIView(BaseTestAPIView):
    url = "/api/progress/"

    def test_episodes__progress__from_another_user__ok(self, episode, client):
        client.login(create_user())
        response = client.get(self.url)
        # TODO: Put records (with episodes from another user) to RedisMock
        assert response.status_code == 200, f"Progress API is not available: {response.text}"
        assert response.json() == []

    def _create_episode(self, episode_data, podcast: Podcast, status: Episode.Status, file_size: int):
        src_id = video_id()
        episode_data.update({
            "podcast_id": podcast.id,
            "source_id": src_id,
            "file_name": f"file_name_{src_id}.mp3",
            "status": status,
            "file_size": file_size,
        })
        return self.async_run(Episode.create(**episode_data))

    @staticmethod
    def _progress(podcast: Podcast, episode: Episode, current_size: int):
        return {
            "status": EpisodeStatuses.episode_downloading,
            "status_display": "Downloading",
            "episode_id": episode.id,
            "episode_title": episode.title,
            "podcast_id": episode.podcast_id,
            "podcast_publish_id": podcast.publish_id,
            "current_file_size": current_size,
            "total_file_size": episode.file_size,
        }

    #
    def test_filter_by_status__ok(self, client, episode_data, mocked_redis):
        podcast_1 = self.async_run(Podcast.create(**get_podcast_data()))
        podcast_2 = self.async_run(Podcast.create(**get_podcast_data()))
        mb_1 = 1 * 1024 * 1024
        mb_2 = 2 * 1024 * 1024
        mb_4 = 4 * 1024 * 1024
        status = Episode.Status

        p1_episode_new = self._create_episode(episode_data, podcast_1, status.NEW, mb_1)
        p1_episode_down = self._create_episode(episode_data, podcast_1, status.DOWNLOADING, mb_2)
        p2_episode_new = self._create_episode(episode_data, podcast_2, status.NEW, mb_1)
        p2_episode_down = self._create_episode(episode_data, podcast_2, status.DOWNLOADING, mb_4)

        mocked_redis.async_get_many.return_value = mocked_redis.async_return({
            p1_episode_new.file_name.partition(".")[0]: {
                "status": EpisodeStatuses.pending,
                "processed_bytes": 0,
                "total_bytes": mb_1,
            },
            p1_episode_down.file_name.partition(".")[0]: {
                "status": EpisodeStatuses.episode_downloading,
                "processed_bytes": mb_1,
                "total_bytes": mb_2,
            },
            p2_episode_down.file_name.partition(".")[0]: {
                "status": EpisodeStatuses.episode_downloading,
                "processed_bytes": 1024 * 1024,
                "total_bytes": 4 * 1024 * 1024,
            },
        })
        response = client.get(self.url)
        assert response.status_code == 200, f"Progress API is not available: {response.json()}"
        assert response.json() == [
            self._progress(podcast_1, p1_episode_down, current_size=mb_1),
            self._progress(podcast_2, p2_episode_down, current_size=mb_4),
        ]

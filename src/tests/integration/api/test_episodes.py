import pytest

from modules.podcast.models import Episode
from tests.integration.api.test_base import BaseTestAPIView


INVALID_UPDATE_DATA = [
    [{"youtube_link": "fake-url"}, {"youtube_link": "Not a valid URL."}],
]

INVALID_CREATE_DATA = INVALID_UPDATE_DATA + [
    [{}, {"youtube_link": "Missing data for required field."}],
]


def _episode_in_list(episode: Episode):
    return {
        "id": episode.id,
        'title': episode.title,
        'image_url':  episode.image_url,
        'created_at': episode.created_at.isoformat(),
    }


def _episode_details(episode: Episode):
    return {
        "id": episode.id,
        'title': episode.title,
        'author': episode.author,
        'status': episode.status,
        'length': episode.length,
        'watch_url': episode.watch_url,
        'remote_url': episode.remote_url,
        'image_url': episode.image_url,
        'file_size': episode.file_size,
        'description': episode.description,
        'created_at': episode.created_at.isoformat(),
        'published_at': episode.published_at.isoformat() if episode.published_at else None,
    }


class TestEpisodeListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/{podcast_id}/episodes/"

    def test_get_list__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(podcast_id=episode.podcast_id)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == [_episode_in_list(episode)]

    def test_create__ok(self, client, podcast, episode, user, mocked_episode_creator):
        mocked_episode_creator.async_create_mock.return_value = episode
        client.login(user)
        episode_data = {"youtube_link": "http://link.to.resource/"}
        url = self.url.format(podcast_id=podcast.id)
        response = client.post(url, json=episode_data)
        assert response.status_code == 201
        assert response.json() == _episode_in_list(episode)
        # TODO: reformat mock class in order to support next assert
        # mocked_episode_creator.target_class.__init__.assert_called_with(
        #     podcast_id=podcast.id,
        #     youtube_link=episode_data["youtube_link"],
        #     user_id=user.id,
        # )

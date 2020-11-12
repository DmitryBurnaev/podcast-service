import pytest

from modules.podcast.models import Episode
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import create_user

INVALID_UPDATE_DATA = [
    [{"title": "title" * 100}, {"title": "Longer than maximum length 256."}],
    [{"author": "author" * 100}, {"author": "Longer than maximum length 256."}],
]

INVALID_CREATE_DATA = [
    [{"youtube_link": "fake-url"}, {"youtube_link": "Not a valid URL."}],
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
        'status': str(episode.status),
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

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    def test_create__invalid_request__fail(
        self, client, podcast, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(podcast_id=podcast.id)
        response = client.post(url, json=invalid_data)
        response_data = response.json()
        # TODO: move to base class test as common code
        assert response.status_code == 400
        assert response_data["error"] == "Requested data is not valid."
        for error_field, error_value in error_details.items():
            assert error_field in response_data["details"]
            assert error_value in response_data["details"][error_field]


class TestEpisodeRUDAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/"

    def test_get_details__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == _episode_details(episode)

    def test_get_details__episode_from_another_user__fail(self, client, episode, user):
        client.login(create_user())
        url = self.url.format(id=episode.id)
        response = client.get(url)
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Episode #{episode.id} does not exist or belongs to another user",
        }

    def test_update__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.id)
        patch_data = {
            "title": "New title",
            "author": "New author",
            "description": "New description",
        }
        response = client.patch(url, json=patch_data)
        episode = self.async_run(Episode.async_get(id=episode.id))

        assert response.status_code == 200
        assert response.json() == _episode_details(episode)
        assert episode.title == "New title"
        assert episode.author == "New author"
        assert episode.description == "New description"

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    def test_update__invalid_request__fail(
        self, client, episode, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.patch(url, json=invalid_data)
        response_data = response.json()
        # TODO: move as common code's fragment
        assert response.status_code == 400
        assert response_data["error"] == "Requested data is not valid."
        for error_field, error_value in error_details.items():
            assert error_field in response_data["details"]
            assert error_value in response_data["details"][error_field]

    def test_update__episode_from_another_user__fail(self, client, episode):
        client.login(create_user())
        url = self.url.format(id=episode.id)
        response = client.patch(url, json={})
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Episode #{episode.id} does not exist or belongs to another user",
        }

    def test_delete__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        episode = self.async_run(Episode.async_get(id=episode.id))
        assert episode is None

    def test_delete__episode_from_another_user__fail(self, client, episode, user):
        user_2 = create_user()
        client.login(user_2)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Episode #{episode.id} does not exist or belongs to another user",
        }

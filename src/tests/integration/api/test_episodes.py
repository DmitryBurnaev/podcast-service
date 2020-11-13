import pytest

from modules.podcast.models import Episode
from modules.podcast.tasks import DownloadEpisode
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
        mocked_episode_creator.create.return_value = mocked_episode_creator.async_return(episode)
        client.login(user)
        episode_data = {"youtube_link": "http://link.to.resource/"}
        url = self.url.format(podcast_id=podcast.id)
        response = client.post(url, json=episode_data)
        assert response.status_code == 201
        assert response.json() == _episode_in_list(episode)
        mocked_episode_creator.target_class.__init__.assert_called_with(
            podcast_id=podcast.id,
            youtube_link=episode_data["youtube_link"],
            user_id=user.id,
        )
        mocked_episode_creator.create.assert_called_once()

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    def test_create__invalid_request__fail(
        self, client, podcast, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(podcast_id=podcast.id)
        self.assert_bad_request(client.post(url, json=invalid_data), error_details)


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
        self.assert_not_found(client.get(url), episode)

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
        self.assert_bad_request(client.patch(url, json=invalid_data), error_details)

    def test_update__episode_from_another_user__fail(self, client, episode):
        client.login(create_user())
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.patch(url, json={}), episode)

    def test_delete__ok(self, client, episode, user, mocked_s3):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert self.async_run(Episode.async_get(id=episode.id)) is None
        mocked_s3.delete_files_async.assert_called_with([episode.file_name])

    def test_delete__episode_from_another_user__fail(self, client, episode, user):
        client.login(create_user())
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.delete(url), episode)


class TestEpisodeDownloadAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/download/"

    def test_download__ok(self, client, episode, user, mocked_rq_queue):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.put(url)
        episode = self.async_run(Episode.async_get(id=episode.id))
        assert response.status_code == 200
        assert response.json() == _episode_details(episode)
        mocked_rq_queue.enqueue.assert_called_with(DownloadEpisode(), episode_id=episode.id)

    def test_download__episode_from_another_user__fail(self, client, episode, user):
        client.login(create_user())
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.put(url), episode)

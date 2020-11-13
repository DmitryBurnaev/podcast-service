import pytest

from modules.podcast.models import Podcast
from modules.podcast.tasks import GenerateRSS
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import create_user, get_podcast_data

INVALID_UPDATE_DATA = [
    [{"name": "name" * 100}, {"name": "Length must be between 1 and 256."}],
    [{"description": 100}, {"description": "Not a valid string."}],
    [{"download_automatically": "fake-bool"}, {"download_automatically": "Not a valid boolean."}],
]

INVALID_CREATE_DATA = INVALID_UPDATE_DATA + [
    [{}, {"name": "Missing data for required field."}],
]


def _podcast(podcast):
    return {
        "id": podcast.id,
        'name': podcast.name,
        'description': podcast.description,
        'image_url': podcast.image_url,
        'created_at': podcast.created_at.isoformat(),
    }


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/"

    def test_get_list__ok(self, client, podcast, user):
        client.login(user)
        response = client.get(self.url)
        assert response.status_code == 200
        assert response.json() == [_podcast(podcast)]

    def test_get_list__filter_by_created_by__ok(self, client):
        user_1 = create_user()
        user_2 = create_user()

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_1.id
        self.async_run(Podcast.create(**podcast_data))

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_2.id
        podcast_2 = self.async_run(Podcast.create(**podcast_data))

        client.login(user_2)
        response = client.get(self.url)
        assert response.status_code == 200
        assert response.json() == [_podcast(podcast_2)]

    def test_create__ok(self, client, user, podcast_data):
        podcast_data = {
            "name": podcast_data["name"],
            "description": podcast_data["description"]
        }
        client.login(user)
        response = client.post(self.url, json=podcast_data)
        assert response.status_code == 201

        response_data = response.json()
        podcast = self.async_run(Podcast.async_get(id=response_data["id"]))
        assert podcast is not None
        assert response.json() == _podcast(podcast)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    def test_create__invalid_request__fail(
        self, client, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)


class TestPodcastRUDAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/"

    def test_get_detailed__ok(self, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == _podcast(podcast)

    def test_get__podcast_from_another_user__fail(self, client, podcast):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.get(url), podcast)

    def test_update__ok(self, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        patch_data = {
            "name": "New name",
            "description": "New description",
            "download_automatically": True,
        }
        response = client.patch(url, json=patch_data)
        podcast = self.async_run(Podcast.async_get(id=podcast.id))
        assert response.status_code == 200
        assert response.json() == _podcast(podcast)
        assert podcast.name == "New name"
        assert podcast.description == "New description"
        assert podcast.download_automatically is True

    def test_update__podcast_from_another_user__fail(self, client, podcast):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.patch(url, json={}), podcast)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    def test_update__invalid_request__fail(
        self, client, podcast, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(id=podcast.id)
        self.assert_bad_request(client.patch(url, json=invalid_data), error_details)

    def test_delete__ok(self, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 204
        podcast = self.async_run(Podcast.async_get(id=podcast.id))
        assert podcast is None

    def test_delete__podcast_from_another_user__fail(self, client, podcast, user):
        user_2 = create_user()
        client.login(user_2)
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.delete(url), podcast)


class TestPodcastGenerateRSSAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/generate_rss/"

    def test_run_generation__ok(self, client, podcast, user, mocked_rq_queue):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.put(url)
        assert response.status_code == 204
        mocked_rq_queue.enqueue.assert_called_with(GenerateRSS(), podcast.id)

    def test_run_generation__podcast_from_another_user__fail(self, client, podcast, user):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.put(url), podcast)
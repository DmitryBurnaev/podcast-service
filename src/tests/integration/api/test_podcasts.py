import asyncio

from modules.podcast.models import Podcast
from tests.integration.api.test_base import BaseTestAPIView
from tests.integration.conftest import create_user, get_podcast_data


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

    def test_get_list__filter_by_created_by__ok(self, loop, client):
        user_1 = create_user()
        user_2 = create_user()

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_1.id
        loop.run_until_complete(Podcast.create(**podcast_data))

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_2.id
        podcast_2 = loop.run_until_complete(Podcast.create(**podcast_data))

        client.login(user_2)
        response = client.get(self.url)
        assert response.status_code == 200
        assert response.json() == [_podcast(podcast_2)]

    def test_create__ok(self, loop, client, user, podcast_data):
        podcast_data = {
            "name": podcast_data["name"],
            "description": podcast_data["description"]
        }
        client.login(user)
        response = client.post(self.url, json=podcast_data)
        assert response.status_code == 201

        response_data = response.json()
        podcast = loop.run_until_complete(Podcast.async_get(id=response_data["id"]))
        assert podcast is not None
        assert response.json() == _podcast(podcast)


class TestPodcastRUDAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/"

    def test_get_detailed__ok(self, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == _podcast(podcast)

    def test_get_podcast_from_another_user__fail(self, loop, client, podcast):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        response = client.get(url)
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Podcast #{podcast.id} does not exist or belongs to another user",
        }

    def test_update__ok(self, loop, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        patch_data = {
            "name": "New name",
            "description": "New description",
            "download_automatically": True,
        }
        response = client.patch(url, json=patch_data)
        assert response.status_code == 200

        podcast = loop.run_until_complete(Podcast.async_get(id=podcast.id))
        assert response.json() == _podcast(podcast)
        assert podcast.name == "New name"
        assert podcast.description == "New description"
        assert podcast.download_automatically is True

    def test_update__podcast_from_another_user__fail(self, loop, client, podcast):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        response = client.patch(url, json={})
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Podcast #{podcast.id} does not exist or belongs to another user",
        }

    def test_delete__ok(self, loop, client, podcast, user):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 204

        podcast = loop.run_until_complete(Podcast.async_get(id=podcast.id))
        assert podcast is None

    def test_delete__podcast_from_another_user__fail(self, loop, client, podcast, user):
        user_2 = create_user()
        client.login(user_2)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": f"Podcast #{podcast.id} does not exist or belongs to another user",
        }

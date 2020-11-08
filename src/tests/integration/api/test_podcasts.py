from tests.integration.api.test_base import BaseTestAPIView


def _podcast_in_list(podcast):
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
        assert response.json() == [_podcast_in_list(podcast)]

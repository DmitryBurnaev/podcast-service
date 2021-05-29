import pytest

from core import settings
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks import GenerateRSSTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import create_user, get_podcast_data, get_episode_data, async_run, create_episode

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
        "name": podcast.name,
        "description": podcast.description,
        "image_url": podcast.image_url,
        "download_automatically": podcast.download_automatically,
        "created_at": podcast.created_at.isoformat(),
        "rss_link": podcast.rss_link,
        "episodes_count": 0,
    }


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/"

    def test_get_list__ok(self, client, podcast, user):
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast)]

    def test_get_list__check_episodes_count__ok(self, client, user, loop):

        podcast_1 = async_run(Podcast.create(**get_podcast_data(created_by_id=user.id)))
        create_episode(get_episode_data(), podcast_1)
        create_episode(get_episode_data(), podcast_1)

        podcast_2 = async_run(Podcast.create(**get_podcast_data(created_by_id=user.id)))
        create_episode(get_episode_data(), podcast_2)

        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)

        expected_episodes_counts = {podcast_1.id: 2, podcast_2.id: 1}
        actual_episodes_counts = {
            podcast["id"]: podcast["episodes_count"] for podcast in response_data
        }
        assert expected_episodes_counts == actual_episodes_counts

    def test_get_list__filter_by_created_by__ok(self, client):
        user_1 = create_user()
        user_2 = create_user()

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_1.id
        async_run(Podcast.create(**podcast_data))

        podcast_data = get_podcast_data()
        podcast_data["created_by_id"] = user_2.id
        podcast_2 = async_run(Podcast.create(**podcast_data))

        client.login(user_2)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast_2)]

    def test_create__ok(self, client, user, podcast_data):
        podcast_data = {
            "name": podcast_data["name"],
            "description": podcast_data["description"],
        }
        client.login(user)
        response = client.post(self.url, json=podcast_data)
        response_data = self.assert_ok_response(response, status_code=201)
        podcast = async_run(Podcast.async_get(id=response_data["id"]))
        assert podcast is not None
        assert response_data == _podcast(podcast)

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
        response_data = self.assert_ok_response(response)
        assert response_data == _podcast(podcast)

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
        podcast = async_run(Podcast.async_get(id=podcast.id))
        response_data = self.assert_ok_response(response)
        assert response_data == _podcast(podcast)
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

    def test_delete__ok(self, client, podcast, user, mocked_s3):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert async_run(Podcast.async_get(id=podcast.id)) is None
        mocked_s3.delete_files_async.assert_called_with(
            [f"{podcast.publish_id}.xml"], remote_path=settings.S3_BUCKET_RSS_PATH
        )

    def test_delete__podcast_from_another_user__fail(self, client, podcast, user):
        user_2 = create_user()
        client.login(user_2)
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.delete(url), podcast)

    def test_delete__episodes_deleted_too__ok(self, client, podcast, user, mocked_s3):
        episode_1 = async_run(Episode.create(**get_episode_data(podcast)))
        episode_2 = async_run(Episode.create(**get_episode_data(podcast, "published")))

        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert async_run(Podcast.async_get(id=podcast.id)) is None
        assert async_run(Episode.async_get(id=episode_1.id)) is None
        assert async_run(Episode.async_get(id=episode_2.id)) is None

        mocked_s3.delete_files_async.assert_called_with([episode_2.file_name])

    def test_delete__episodes_in_another_podcast__ok(self, client, episode_data, user, mocked_s3):
        podcast_1 = async_run(Podcast.create(**get_podcast_data(created_by_id=user.id)))
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["podcast_id"] = podcast_1.id
        episode_1 = async_run(Episode.create(**episode_data))
        episode_1_1 = async_run(Episode.create(**get_episode_data(podcast_1, "published")))

        podcast_2 = async_run(Podcast.create(**get_podcast_data()))
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["podcast_id"] = podcast_2.id
        # creating episode with same `source_id` in another podcast
        episode_2 = async_run(Episode.create(**episode_data))

        client.login(user)
        url = self.url.format(id=podcast_1.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert async_run(Podcast.async_get(id=podcast_1.id)) is None
        assert async_run(Episode.async_get(id=episode_1.id)) is None

        assert async_run(Podcast.async_get(id=podcast_2.id)) is not None
        assert async_run(Episode.async_get(id=episode_2.id)) is not None

        mocked_s3.delete_files_async.assert_called_with([episode_1_1.file_name])


class TestPodcastGenerateRSSAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/generate_rss/"

    def test_run_generation__ok(self, client, podcast, user, mocked_rq_queue):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.put(url)
        assert response.status_code == 204
        mocked_rq_queue.enqueue.assert_called_with(GenerateRSSTask(), podcast.id)

    def test_run_generation__podcast_from_another_user__fail(self, client, podcast, user):
        client.login(create_user())
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.put(url), podcast)

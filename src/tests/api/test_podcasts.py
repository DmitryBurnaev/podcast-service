import io
from unittest.mock import patch

import pytest

from common.statuses import ResponseStatus
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks import GenerateRSSTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import (
    create_user,
    get_podcast_data,
    get_episode_data,
    create_episode,
    await_,
)

INVALID_UPDATE_DATA = [
    [{"name": "name" * 100}, {"name": "Length must be between 1 and 256."}],
    [{"description": 100}, {"description": "Not a valid string."}],
    [{"download_automatically": "fake-bool"}, {"download_automatically": "Not a valid boolean."}],
]

INVALID_CREATE_DATA = INVALID_UPDATE_DATA + [
    [{}, {"name": "Missing data for required field."}],
]


def _podcast(podcast):
    data = {
        "id": podcast.id,
        "name": podcast.name,
        "description": podcast.description,
        "download_automatically": podcast.download_automatically,
        "created_at": podcast.created_at.isoformat(),
        "episodes_count": 0,
    }
    if podcast.image:
        data["image_url"] = podcast.image.url
    if podcast.rss:
        data["rss_url"] = podcast.rss.url

    return data


class TestPodcastListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/"

    def test_get_list__ok(self, client, podcast, user):
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast)]

    def test_get_list__check_episodes_count__ok(self, client, user, loop, dbs):
        dbs = dbs
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        create_episode(dbs, get_episode_data(), podcast_1)
        create_episode(dbs, get_episode_data(), podcast_1)

        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        create_episode(dbs, get_episode_data(), podcast_2)

        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)

        expected_episodes_counts = {podcast_1.id: 2, podcast_2.id: 1}
        actual_episodes_counts = {
            podcast["id"]: podcast["episodes_count"] for podcast in response_data
        }
        assert expected_episodes_counts == actual_episodes_counts

    def test_get_list__filter_by_owner__ok(self, client, dbs, image_file, rss_file):
        user_1 = create_user(dbs)
        user_2 = create_user(dbs)

        podcast_data = get_podcast_data()
        podcast_data["owner_id"] = user_1.id
        podcast_data["image_id"] = image_file.id
        podcast_data["rss_id"] = rss_file.id
        await_(Podcast.async_create(dbs, db_commit=True, **podcast_data))

        podcast_data = get_podcast_data()
        podcast_data["owner_id"] = user_2.id
        podcast_data["image_id"] = image_file.id
        podcast_data["rss_id"] = rss_file.id
        podcast_2 = await_(Podcast.async_create(dbs, db_commit=True, **podcast_data))

        client.login(user_2)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast_2)]

    def test_create__ok(self, client, user, podcast_data, dbs):
        podcast_data = {
            "name": podcast_data["name"],
            "description": podcast_data["description"],
        }
        client.login(user)
        response = client.post(self.url, json=podcast_data)
        response_data = self.assert_ok_response(response, status_code=201)
        podcast = await_(Podcast.async_get(dbs, id=response_data["id"]))
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

    def test_get__podcast_from_another_user__fail(self, client, podcast, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.get(url), podcast)

    def test_update__ok(self, client, podcast, user, dbs):
        client.login(user)
        url = self.url.format(id=podcast.id)
        patch_data = {
            "name": "New name",
            "description": "New description",
            "download_automatically": True,
        }
        response = client.patch(url, json=patch_data)
        await_(dbs.refresh(podcast))
        response_data = self.assert_ok_response(response)
        assert response_data == _podcast(podcast)
        assert podcast.name == "New name"
        assert podcast.description == "New description"
        assert podcast.download_automatically is True

    def test_update__podcast_from_another_user__fail(self, client, podcast, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.patch(url, json={}), podcast)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    def test_update__invalid_request__fail(
        self, client, podcast, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(id=podcast.id)
        self.assert_bad_request(client.patch(url, json=invalid_data), error_details)

    def test_delete__ok(self, client, podcast, user, mocked_s3, dbs):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await_(Podcast.async_get(dbs, id=podcast.id)) is None
        mocked_s3.delete_files_async.assert_called_with([podcast.rss.name], remote_path="rss")

    def test_delete__podcast_from_another_user__fail(self, client, podcast, user, dbs):
        user_2 = create_user(dbs)
        client.login(user_2)
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.delete(url), podcast)

    def test_delete__episodes_deleted_too__ok(self, client, podcast, user, mocked_s3, dbs):
        episode_1 = await_(Episode.async_create(dbs, **get_episode_data(podcast)))
        episode_2 = await_(Episode.async_create(dbs, **get_episode_data(podcast, "published")))
        await_(dbs.commit())

        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await_(Podcast.async_get(dbs, id=podcast.id)) is None
        assert await_(Episode.async_get(dbs, id=episode_1.id)) is None
        assert await_(Episode.async_get(dbs, id=episode_2.id)) is None

        mocked_s3.delete_files_async.assert_called_with([episode_2.file_name])

    def test_delete__episodes_in_another_podcast__ok(
        self, client, episode_data, user, mocked_s3, dbs
    ):
        dbs = dbs
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id)))
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["podcast_id"] = podcast_1.id
        episode_1 = await_(Episode.async_create(dbs, **episode_data))
        episode_1_1 = await_(Episode.async_create(dbs, **get_episode_data(podcast_1, "published")))

        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data()))
        episode_data["status"] = Episode.Status.PUBLISHED
        episode_data["podcast_id"] = podcast_2.id
        # creating episode with same `source_id` in another podcast
        episode_2 = await_(Episode.async_create(dbs, **episode_data))

        await_(dbs.commit())
        client.login(user)
        url = self.url.format(id=podcast_1.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await_(Podcast.async_get(dbs, id=podcast_1.id)) is None
        assert await_(Episode.async_get(dbs, id=episode_1.id)) is None

        assert await_(Podcast.async_get(dbs, id=podcast_2.id)) is not None
        assert await_(Episode.async_get(dbs, id=episode_2.id)) is not None

        mocked_s3.delete_files_async.assert_called_with([episode_1_1.file_name])


class TestPodcastGenerateRSSAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/generate-rss/"

    def test_run_generation__ok(self, client, podcast, user, mocked_rq_queue):
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.put(url)
        assert response.status_code == 204
        mocked_rq_queue.enqueue.assert_called_with(GenerateRSSTask(), podcast.id)

    def test_run_generation__podcast_from_another_user__fail(self, client, podcast, user, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.put(url), podcast)


class TestPodcastUploadImageAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/upload-image/"
    remote_path = "/remote/path-to-file.png"
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    @staticmethod
    def _file() -> io.BytesIO:
        return io.BytesIO(b"Binary image data: \x00\x01")

    @patch("common.storage.StorageS3.upload_file")
    def test_upload__ok(self, mocked_upload_file, client, podcast, user, dbs):
        client.login(user)
        mocked_upload_file.return_value = self.remote_path
        response = client.post(url=self.url.format(id=podcast.id), files={"image": self._file()})
        await_(dbs.refresh(podcast))
        response_data = self.assert_ok_response(response)
        assert response_data == {"id": podcast.id, "image_url": podcast.image_url}
        assert podcast.image.path == self.remote_path

    @patch("common.storage.StorageS3.upload_file")
    def test_upload__upload_failed__fail(self, mocked_upload_file, client, podcast, user, dbs):
        client.login(user)
        mocked_upload_file.side_effect = RuntimeError("Oops")
        response = client.post(url=self.url.format(id=podcast.id), files={"image": self._file()})
        response_data = self.assert_fail_response(
            response, response_status=ResponseStatus.INTERNAL_ERROR, status_code=503
        )
        assert response_data == {
            "error": "Reached max attempt to make action",
            "details": f"Couldn't upload cover for podcast {podcast.id}",
        }

    def test_upload__image_missing__fail(self, client, podcast, user):
        client.login(user)
        response = client.post(
            url=self.url.format(id=podcast.id), files={"fake-image": self._file()}
        )
        response_data = self.assert_fail_response(response, status_code=400)
        assert response_data == {
            "details": "Image is required field",
            "error": "Requested data is not valid.",
        }

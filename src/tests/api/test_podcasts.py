import io
import os.path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from common.enums import EpisodeStatus
from common.statuses import ResponseStatus
from modules.auth.models import User
from modules.media.models import File
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks import GenerateRSSTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import (
    create_user,
    get_podcast_data,
    get_episode_data,
    create_episode,
    get_source_id,
    PodcastTestClient,
)
from tests.mocks import MockS3Client

INVALID_UPDATE_DATA = [
    [{"name": "name" * 100}, {"name": "Length must be between 1 and 256."}],
    [{"description": 100}, {"description": "Not a valid string."}],
    [{"download_automatically": "fake-bool"}, {"download_automatically": "Not a valid boolean."}],
]

INVALID_CREATE_DATA = INVALID_UPDATE_DATA + [
    [{}, {"name": "Missing data for required field."}],
]

pytestmark = pytest.mark.asyncio


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

    async def test_get_list__ok(self, client: PodcastTestClient, podcast: Podcast, user: User):
        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast)]

    async def test_get_list__check_episodes_count__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        await create_episode(dbs, get_episode_data(), podcast_1)
        await create_episode(dbs, get_episode_data(), podcast_1)

        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        await create_episode(dbs, get_episode_data(), podcast_2)

        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)

        expected_episodes_counts = {podcast_1.id: 2, podcast_2.id: 1}
        actual_episodes_counts = {
            podcast["id"]: podcast["episodes_count"] for podcast in response_data
        }
        assert expected_episodes_counts == actual_episodes_counts

    async def test_get_list__filter_by_owner__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        image_file: File,
        rss_file: File,
    ):
        user_1 = await create_user(dbs)
        user_2 = await create_user(dbs)

        podcast_data = get_podcast_data()
        podcast_data["owner_id"] = user_1.id
        podcast_data["image_id"] = image_file.id
        podcast_data["rss_id"] = rss_file.id
        await Podcast.async_create(dbs, db_commit=True, **podcast_data)

        podcast_data = get_podcast_data()
        podcast_data["owner_id"] = user_2.id
        podcast_data["image_id"] = image_file.id
        podcast_data["rss_id"] = rss_file.id
        podcast_2 = await Podcast.async_create(dbs, db_commit=True, **podcast_data)

        await client.login(user_2)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_podcast(podcast_2)]

    async def test_create__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        podcast_data,
    ):
        podcast_data = {
            "name": podcast_data["name"],
            "description": podcast_data["description"],
        }
        await client.login(user)
        response = client.post(self.url, json=podcast_data)
        response_data = self.assert_ok_response(response, status_code=201)
        podcast = await Podcast.async_get(dbs, id=response_data["id"])
        assert podcast is not None
        assert response_data == _podcast(podcast)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    async def test_create__invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        self.assert_bad_request(client.post(self.url, json=invalid_data), error_details)


class TestPodcastRUDAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/"

    async def test_get_detailed__ok(self, client: PodcastTestClient, user: User, podcast: Podcast):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _podcast(podcast)

    async def test_get__podcast_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.get(url), podcast)

    async def test_update__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        patch_data = {
            "name": "New name",
            "description": "New description",
            "download_automatically": True,
        }
        response = client.patch(url, json=patch_data)
        await dbs.refresh(podcast)
        response_data = self.assert_ok_response(response)
        assert response_data == _podcast(podcast)
        assert podcast.name == "New name"
        assert podcast.description == "New description"
        assert podcast.download_automatically is True

    async def test_update__podcast_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.patch(url, json={}), podcast)

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    async def test_update__invalid_request__fail(
        self,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        self.assert_bad_request(client.patch(url, json=invalid_data), error_details)

    async def test_delete__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
        mocked_s3: MockS3Client,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await Podcast.async_get(dbs, id=podcast.id) is None
        mocked_s3.delete_files_async.assert_any_call(
            [podcast.rss.name], remote_path=settings.S3_BUCKET_RSS_PATH
        )
        mocked_s3.delete_files_async.assert_any_call(
            [podcast.image.name], remote_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH
        )

    async def test_delete__podcast_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
    ):
        user_2 = await create_user(dbs)
        await client.login(user_2)
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.delete(url), podcast)

    async def test_delete__episodes_deleted_too__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
        mocked_s3: MockS3Client,
    ):
        episode_1 = await create_episode(dbs, get_episode_data(podcast), status=EpisodeStatus.NEW)
        episode_2 = await create_episode(
            dbs, get_episode_data(podcast), status=EpisodeStatus.PUBLISHED
        )
        await dbs.commit()

        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.delete(url)
        assert response.status_code == 200
        assert await Podcast.async_get(dbs, id=podcast.id) is None
        assert await Episode.async_get(dbs, id=episode_1.id) is None
        assert await Episode.async_get(dbs, id=episode_2.id) is None

        ra = settings.S3_BUCKET_AUDIO_PATH
        ri = settings.S3_BUCKET_EPISODE_IMAGES_PATH
        # episode_1 is in NEW state. we don't need to remove remote files for it
        self.assert_not_called_with(
            mocked_s3.delete_files_async, [episode_1.audio_filename], remote_path=ra
        )
        self.assert_not_called_with(
            mocked_s3.delete_files_async, [episode_1.image.name], remote_path=ri
        )
        # episode_2 is in PUBLISH state. we have to remove files from S3
        mocked_s3.delete_files_async.assert_any_call([episode_2.audio.name], remote_path=ra)
        mocked_s3.delete_files_async.assert_any_call([episode_2.image.name], remote_path=ri)

    async def test_delete__episodes_in_another_podcast__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_s3: MockS3Client,
    ):
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        episode_data = get_episode_data(podcast_1, creator=user)

        episode_data["podcast_id"] = podcast_1.id
        episode_data["status"] = Episode.Status.PUBLISHED

        episode_1 = await create_episode(dbs, episode_data)

        source_id = get_source_id()
        episode_1_1 = await create_episode(dbs, episode_data, source_id=source_id)

        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data())
        episode_data["podcast_id"] = podcast_2.id

        # creating episode with same `source_id` in another podcast
        # not-available files (with same source_id will NOT be deleted)
        episode_2 = await create_episode(
            dbs, episode_data, source_id=source_id, status=EpisodeStatus.NEW
        )

        await dbs.commit()
        await client.login(user)
        url = self.url.format(id=podcast_1.id)
        response = client.delete(url)

        assert response.status_code == 200
        assert await Podcast.async_get(dbs, id=podcast_1.id) is None
        assert await Episode.async_get(dbs, id=episode_1.id) is None

        assert await Podcast.async_get(dbs, id=podcast_2.id) is not None
        assert await Episode.async_get(dbs, id=episode_2.id) is not None

        ra = settings.S3_BUCKET_AUDIO_PATH
        ri = settings.S3_BUCKET_EPISODE_IMAGES_PATH

        mocked_s3.delete_files_async.assert_any_call([episode_1.audio.name], remote_path=ra)
        mocked_s3.delete_files_async.assert_any_call([episode_1.image.name], remote_path=ri)

        mocked_s3.delete_files_async.assert_any_call([episode_1_1.audio.name], remote_path=ra)
        mocked_s3.delete_files_async.assert_any_call([episode_1_1.image.name], remote_path=ri)

        self.assert_not_called_with(
            mocked_s3.delete_files_async, [episode_2.audio_filename], remote_path=ra
        )
        self.assert_not_called_with(
            mocked_s3.delete_files_async, [episode_2.image.name], remote_path=ri
        )


class TestPodcastGenerateRSSAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/generate-rss/"

    async def test_run_generation__ok(
        self,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
        mocked_rq_queue,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.put(url)
        assert response.status_code == 202
        mocked_rq_queue.enqueue.assert_called_with(
            GenerateRSSTask(), podcast.id, job_id=GenerateRSSTask.get_job_id(podcast.id)
        )

    async def test_run_generation__podcast_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=podcast.id)
        self.assert_not_found(client.put(url), podcast)


class TestPodcastUploadImageAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/upload-image/"
    remote_path = "/remote/path-to-file.png"
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    @patch("common.storage.StorageS3.upload_file")
    async def test_upload__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_upload_file,
        mocked_s3: MockS3Client,
    ):
        podcast_data = get_podcast_data(owner_id=user.id)
        podcast = await Podcast.async_create(dbs, db_commit=True, **podcast_data)

        await client.login(user)
        mocked_upload_file.return_value = self.remote_path
        response = client.post(url=self.url.format(id=podcast.id), files={"image": self._file()})
        await dbs.refresh(podcast)
        response_data = self.assert_ok_response(response)
        assert response_data == {"id": podcast.id, "image_url": podcast.image_url}
        assert podcast.image.path == self.remote_path
        mocked_s3.delete_files_async.assert_not_called()

    @staticmethod
    def _file() -> io.BytesIO:
        return io.BytesIO(b"Binary image data: \x00\x01")

    @patch("common.storage.StorageS3.upload_file")
    async def test_upload__replace_image__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_upload_file,
        mocked_s3: MockS3Client,
        podcast: Podcast,
    ):
        assert podcast.image_id is not None
        old_image_id = podcast.image_id
        old_image_name = podcast.image.name
        old_image_url = podcast.image.url

        await client.login(user)
        mocked_upload_file.return_value = self.remote_path
        response = client.post(url=self.url.format(id=podcast.id), files={"image": self._file()})
        response_data = self.assert_ok_response(response)

        dbs.expunge(podcast)
        dbs.expunge(podcast.image)
        podcast = await Podcast.async_get(dbs, id=podcast.id)

        assert response_data == {"id": podcast.id, "image_url": podcast.image.url}
        assert podcast.image.path == self.remote_path
        assert podcast.image.id == old_image_id

        assert podcast.image.name != old_image_name
        assert podcast.image.name == os.path.basename(self.remote_path)
        assert podcast.image.url != old_image_url
        assert podcast.image.url.endswith(self.remote_path)
        mocked_s3.delete_files_async.assert_awaited_with(
            [old_image_name], remote_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH
        )

    @patch("common.storage.StorageS3.upload_file")
    async def test_upload__upload_failed__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        mocked_upload_file,
        podcast: Podcast,
    ):
        await client.login(user)
        mocked_upload_file.side_effect = RuntimeError("Oops")
        response = client.post(url=self.url.format(id=podcast.id), files={"image": self._file()})
        response_data = self.assert_fail_response(
            response, response_status=ResponseStatus.INTERNAL_ERROR, status_code=503
        )
        assert response_data == {
            "error": "Reached max attempt to make action",
            "details": f"Couldn't upload cover for podcast {podcast.id}",
        }

    async def test_upload__image_missing__fail(
        self,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
    ):
        await client.login(user)
        response = client.post(
            url=self.url.format(id=podcast.id), files={"fake-image": self._file()}
        )
        response_data = self.assert_fail_response(response, status_code=400)
        assert response_data == {
            "details": "Image is required field",
            "error": "Requested data is not valid.",
        }

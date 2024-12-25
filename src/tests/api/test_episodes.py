import uuid
from functools import partial
from typing import Type
from unittest.mock import patch, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import SourceType, EpisodeStatus
from common.statuses import ResponseStatus
from core import settings
from modules.providers.exceptions import SourceFetchError
from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast, EpisodeChapter
from modules.auth.models import User
from modules.podcast.tasks import DownloadEpisodeTask, UploadedEpisodeTask, DownloadEpisodeImageTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import (
    get_source_id,
    create_user,
    get_podcast_data,
    create_episode,
    PodcastTestClient,
)
from tests.mocks import MockEpisodeCreator, MockRQQueue, MockS3Client

INVALID_UPDATE_DATA = [
    [{"title": "title" * 100}, {"title": "Longer than maximum length 256."}],
    [{"author": "author" * 100}, {"author": "Longer than maximum length 256."}],
]

INVALID_CREATE_DATA = [
    [{"source_url": "fake-url"}, {"source_url": "Not a valid URL."}],
    [{}, {"source_url": "Missing data for required field."}],
]

INVALID_UPLOADED_EPISODES_DATA = [
    [{"path": "path" * 100}, {"path": "Longer than maximum length 256."}],
    [{"name": "filename" * 100}, {"name": "Longer than maximum length 256."}],
    [{"meta": {"duration": "fake-int"}}, {"meta": {"duration": "Not a valid integer."}}],
    [{"meta": {"title": "1"}}, {"meta": {"duration": "Missing data for required field."}}],
    [{"size": "fake-int"}, {"size": "Not a valid integer."}],
]
pytestmark = pytest.mark.asyncio


def _episode_in_list(episode: Episode):
    return {
        "id": episode.id,
        "title": episode.title,
        "status": str(episode.status),
        "source_type": str(episode.source_type),
        "image_url": episode.image.url if episode.image_id else settings.DEFAULT_EPISODE_COVER,
        "created_at": episode.created_at.isoformat(),
    }


def _episode_details(episode: Episode, status: EpisodeStatus | None = None):
    status = status or episode.status
    return {
        "id": episode.id,
        "title": episode.title,
        "author": episode.author,
        "status": str(status),
        "length": episode.length,
        "audio_url": episode.audio.url,
        "audio_size": episode.audio.size,
        "watch_url": episode.watch_url,
        "image_url": episode.image.url if episode.image_id else settings.DEFAULT_EPISODE_COVER,
        "description": episode.description,
        "source_type": str(episode.source_type),
        "created_at": episode.created_at.isoformat(),
        "published_at": episode.published_at.isoformat() if episode.published_at else None,
        "podcast": {
            "id": episode.podcast_id,
            "image_url": episode.podcast.image_url,
            "name": episode.podcast.name,
        },
        "chapters": [
            {"title": chapter.title, "start": chapter.start_str, "end": chapter.end_str}
            for chapter in episode.list_chapters
        ],
    }


class TestEpisodeListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/episodes/"

    async def test_get_list__ok(self, client: PodcastTestClient, episode: Episode, user: User):
        await client.login(user)
        url = self.url.format(id=episode.podcast_id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [_episode_in_list(episode)]

    async def test_get_list__filter_by_podcast__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode_data: dict,
    ):
        await client.login(user)
        episode_data |= {"owner_id": user.id}
        podcast_data = partial(get_podcast_data, owner_id=user.id)
        podcast_1 = await Podcast.async_create(dbs, **podcast_data())
        podcast_2 = await Podcast.async_create(dbs, **podcast_data())
        ep = await create_episode(
            dbs, episode_data, podcast=podcast_1, status=EpisodeStatus.PUBLISHED
        )
        await create_episode(dbs, episode_data, podcast=podcast_2)
        url = self.url.format(id=podcast_1.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [_episode_in_list(ep)]

    async def test_get_list__filter_status__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        episode_data: dict,
    ):
        await client.login(user)
        episode_data |= {"owner_id": user.id}
        ep = await create_episode(dbs, episode_data, podcast, status=EpisodeStatus.PUBLISHED)
        await create_episode(dbs, episode_data, podcast, status=EpisodeStatus.ERROR)

        url = self.url.format(id=podcast.id)
        response = client.get(url, params={"status": str(EpisodeStatus.PUBLISHED)})
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [_episode_in_list(ep)]

    async def test_get_list__search_by_title__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        episode_data: dict,
    ):
        await client.login(user)
        episode_data |= {"owner_id": user.id, "status": EpisodeStatus.PUBLISHED}
        ep1 = await create_episode(dbs, episode_data | {"title": "Python NEWS"}, podcast)
        ep2 = await create_episode(dbs, episode_data | {"title": "PyPI is free"}, podcast)
        await create_episode(dbs, episode_data | {"title": "Django"}, podcast)

        url = self.url.format(id=podcast.id)
        response = client.get(url, params={"q": "py"})
        response_data = self.assert_ok_response(response)
        assert response_data["items"] == [_episode_in_list(ep2), _episode_in_list(ep1)]

    async def test_create__ok(
        self,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        episode: Episode,
        episode_data: dict,
        mocked_episode_creator: MockEpisodeCreator,
        mocked_rq_queue: MockRQQueue,
    ):
        mocked_episode_creator.create.return_value = episode
        await client.login(user)
        episode_data = {"source_url": episode_data["watch_url"]}
        url = self.url.format(id=podcast.id)
        response = client.post(url, json=episode_data)
        response_data = self.assert_ok_response(response, status_code=201)
        assert response_data == _episode_in_list(episode), response.json()
        self.assert_called_with(
            mocked_episode_creator.target_class.__init__,
            podcast_id=podcast.id,
            source_url=episode_data["source_url"],
            user_id=user.id,
        )
        mocked_episode_creator.create.assert_called_once()
        mocked_rq_queue.enqueue.assert_called_with(
            tasks.DownloadEpisodeImageTask(),
            episode_id=episode.id,
            job_id=DownloadEpisodeImageTask.get_job_id(episode_id=episode.id),
        )

    async def test_create__start_downloading__ok(
        self,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        episode: Episode,
        episode_data: dict,
        mocked_episode_creator: MockEpisodeCreator,
        mocked_rq_queue: MockRQQueue,
    ):
        mocked_episode_creator.create.return_value = episode
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": episode_data["watch_url"]})
        self.assert_ok_response(response, status_code=201)

        job_download_id = DownloadEpisodeTask.get_job_id(episode_id=episode.id)
        job_download_image_id = DownloadEpisodeImageTask.get_job_id(episode_id=episode.id)
        expected_calls = [
            {
                "args": (tasks.DownloadEpisodeTask(),),
                "kwargs": {"episode_id": episode.id, "job_id": job_download_id},
            },
            {
                "args": (tasks.DownloadEpisodeImageTask(),),
                "kwargs": {"episode_id": episode.id, "job_id": job_download_image_id},
            },
        ]
        actual_calls = [
            {"args": call.args, "kwargs": call.kwargs}
            for call in mocked_rq_queue.enqueue.call_args_list
        ]
        assert actual_calls == expected_calls

    async def test_create__youtube_error__fail(
        self,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        episode_data: dict,
        mocked_episode_creator: MockEpisodeCreator,
    ):
        mocked_episode_creator.create.side_effect = SourceFetchError("Oops")
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": episode_data["watch_url"]})
        response_data = self.assert_fail_response(response, status_code=500)
        assert response_data == {
            "error": "We couldn't extract info about requested episode.",
            "details": "Oops",
        }

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    async def test_create__invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        self.assert_bad_request(client.post(url, json=invalid_data), error_details)

    async def test_create__podcast_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=podcast.id)
        data = {"source_url": "http://link.to.resource/"}
        self.assert_not_found(client.post(url, json=data), podcast)


class TestUploadedEpisodesAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/episodes/uploaded/"
    url_fetch_exists = "/api/podcasts/{id}/episodes/uploaded/{hash}/"

    @pytest.mark.parametrize("auto_start_task", (True, False))
    async def test_create__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        podcast: Podcast,
        user: User,
        mocked_rq_queue: MockRQQueue,
        auto_start_task: bool,
    ):
        audio_duration = 90
        await podcast.update(dbs, download_automatically=auto_start_task, db_commit=True)

        await client.login(user)
        url = self.url.format(id=podcast.id)
        data = {
            "path": f"remote/tmp/{uuid.uuid4().hex}.mp3",
            "name": "uploaded-file.mp3",
            "meta": {
                "duration": audio_duration,
                "author": "Test Author",
                "title": "Test Title",
                "album": "Test Album",
            },
            "hash": str(uuid.uuid4().hex),
            "size": 5000,
            "cover": {
                "preview_url": "https://s3.storage/image.png",
                "path": "tmp/images/cover_39f55d2d833e20e7922f0f7ef462748e.jpg",
                "hash": str(uuid.uuid4().hex),
                "size": 586569,
            },
        }
        response = client.post(url, json=data)
        response_data = self.assert_ok_response(response, status_code=201)

        episode = await Episode.async_get(dbs, id=response_data["id"])
        assert response_data == _episode_details(episode), response.json()
        assert episode.source_type == SourceType.UPLOAD
        assert episode.title == "Test Album. Test Title"
        assert episode.length == audio_duration
        assert episode.author == "Test Author"
        assert episode.owner_id == user.id

        assert episode.audio.path == data["path"]
        assert episode.audio.size == data["size"]
        assert episode.audio.hash == data["hash"]
        assert episode.audio.meta == data["meta"]
        assert episode.audio.available is False

        assert episode.image is not None
        assert episode.image.path == data["cover"]["path"]
        assert episode.image.size == data["cover"]["size"]
        assert episode.image.hash == data["cover"]["hash"]
        assert episode.image.available is True

        if auto_start_task:
            mocked_rq_queue.enqueue.assert_called_with(
                tasks.UploadedEpisodeTask(),
                episode_id=episode.id,
                job_id=tasks.UploadedEpisodeTask.get_job_id(episode_id=episode.id),
            )
        else:
            mocked_rq_queue.enqueue.assert_not_called()

    async def test_create_duplicated_episode__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        episode: Episode,
        client: PodcastTestClient,
        mocked_rq_queue: MockRQQueue,
    ):
        audio_hash = str(uuid.uuid4().hex)
        await episode.update(dbs, source_type=SourceType.UPLOAD, source_id=f"upl_{audio_hash[:11]}")
        await dbs.commit()

        await client.login(user)
        url = self.url.format(id=podcast.id)
        data = {
            "path": f"remote/tmp/{uuid.uuid4().hex}.mp3",
            "name": "uploaded-file.mp3",
            "meta": {
                "duration": 1,
                "author": "Test Author",
                "title": "Test Title",
                "album": "Test Album",
            },
            "hash": audio_hash,
            "size": 50,
        }
        response = client.post(url, json=data)
        response_data = self.assert_ok_response(response)

        assert episode.id == response_data["id"]

        episode = await Episode.async_get(dbs, id=response_data["id"])
        assert response_data == _episode_details(episode), response.json()
        assert episode.source_type == SourceType.UPLOAD
        mocked_rq_queue.enqueue.assert_called_with(
            tasks.UploadedEpisodeTask(),
            episode_id=episode.id,
            job_id=tasks.UploadedEpisodeTask.get_job_id(episode_id=episode.id),
        )

    async def test_get_exists_episode__ok(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        episode: Episode,
        client: PodcastTestClient,
    ):
        audio_hash = str(uuid.uuid4().hex)
        await episode.update(dbs, source_type=SourceType.UPLOAD, source_id=f"upl_{audio_hash[:11]}")
        await dbs.commit()

        await client.login(user)
        url = self.url_fetch_exists.format(id=podcast.id, hash=audio_hash)
        response = client.get(url)
        response_data = self.assert_ok_response(response)

        assert episode.id == response_data["id"]
        episode = await Episode.async_get(dbs, id=response_data["id"])
        assert response_data == _episode_details(episode), response.json()

    async def test_get_exists_episode__fake_hash__fail(
        self,
        dbs: AsyncSession,
        user: User,
        podcast: Podcast,
        client: PodcastTestClient,
    ):
        await client.login(user)
        url = self.url_fetch_exists.format(id=podcast.id, hash="fake-audio-hash")
        response = client.get(url)
        response_data = self.assert_fail_response(
            response,
            status_code=404,
            response_status=ResponseStatus.EXPECTED_NOT_FOUND,
        )

        assert response_data["details"] == "Episode by requested hash not found"

    # fmt: off
    @pytest.mark.parametrize(
        "label, metadata,episode_data",
        [
            (
                "only_title",
                {"duration": 1, "title": "Test title"},
                {"title": "Test title", "author": "", "description": "Uploaded Episode 'Test title'"}
            ),
            (
                "title_author",
                {"duration": 1, "title": "Test Title", "author": "Test Author"},
                {"title": "Test Title", "author": "Test Author", "description": "Uploaded Episode 'Test Title'\nAuthor: Test Author"}
            ),
            (
                "only_author",
                {"duration": 1, "title": '', "author": "Test Author"},
                {"title": "filename", "author": "Test Author", "description": "Uploaded Episode 'filename'\nAuthor: Test Author"}
            ),
            (
                "only_track",
                {"duration": 1, "track": "01"},
                {"title": "Track #01. filename", "description": "Uploaded Episode 'Track #01. filename'\nTrack: #01"}
            ),
            (
                "title_album_track",
                {"duration": 1, "title": "Test Title", "album": "Test Album", "track": "01"},
                {"title": "Test Album #01. Test Title", "description": "Uploaded Episode 'Test Album #01. Test Title'\nAlbum: Test Album (track #01)"}
            ),
            (
                "album_track",
                {"duration": 1, "album": "Test Album", "track": "01"},
                {"title": "Test Album #01. filename", "description": "Uploaded Episode 'Test Album #01. filename'\nAlbum: Test Album (track #01)"}
            ),
            (
                "large_title",
                {"duration": 1, "title": "l-title-" * 100},
                {"title": ("l-title-" * 100)[:252] + "...", "description": f"Uploaded Episode \'{('l-title-' * 100)}\'"}
            ),
        ]
    )
    # fmt: on
    async def test_create__various_metadata__ok(
        self,
        dbs: AsyncSession,
        user: User,
        client: PodcastTestClient,
        podcast: Podcast,
        mocked_rq_queue: MockRQQueue,
        label: str,
        metadata: dict,
        episode_data: dict,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        data = {
            "path": f"remote/tmp/audio-{uuid.uuid4().hex}.mp3",
            "name": "filename",
            "meta": metadata,
            "hash": str(uuid.uuid4().hex),
            "size": 50,
        }
        response = client.post(url, json=data)
        response_data = self.assert_ok_response(response, status_code=201)

        episode = await Episode.async_get(dbs, id=response_data["id"])
        assert response_data == _episode_details(episode), response.json()

        for field, value in episode_data.items():
            assert getattr(episode, field) == value, (
                f"Episode's field {field} value mismatch: "
                f"expected: {value} | actual {getattr(episode, field)} "
            )

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPLOADED_EPISODES_DATA)
    async def test_create__invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        podcast: Podcast,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json=invalid_data)
        assert response.status_code == 400, f"Unexpected status code. Response: {response.content}"

        response_data = response.json()
        response_data = response_data["payload"]
        for error_field, error_value in error_details.items():
            if isinstance(error_value, dict):
                print(error_field, error_value)
                for e_key, e_val in error_value.items():
                    assert e_key in response_data["details"][error_field]
                    assert e_val in response_data["details"][error_field][e_key]
            else:
                assert error_field in response_data["details"]
                assert error_value in response_data["details"][error_field]


class TestEpisodeRUDAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/"

    async def test_get_details__ok(self, client: PodcastTestClient, episode: Episode, user: User):
        await client.login(user)
        url = self.url.format(id=episode.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)

    async def test_get_details__episode_with_chapters__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode: Episode,
        user: User,
    ):
        await client.login(user)
        await episode.update(
            dbs,
            db_commit=True,
            chapters=[
                EpisodeChapter(title="Chapter 1", start=0, end=3600).as_dict,
                EpisodeChapter(title="Chapter 2", start=3601, end=4200).as_dict,
            ],
        )
        episode = await Episode.async_get(dbs, id=episode.id)
        url = self.url.format(id=episode.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)

    async def test_get_details__episode_from_another_user__fail(
        self, dbs: AsyncSession, client: PodcastTestClient, episode: Episode
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.get(url), episode)

    async def test_update__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
    ):
        await client.login(user)
        url = self.url.format(id=episode.id)
        patch_data = {
            "title": "New title",
            "author": "New author",
            "description": "New description",
        }
        response = client.patch(url, json=patch_data)
        await dbs.refresh(episode)

        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)
        assert episode.title == "New title"
        assert episode.author == "New author"
        assert episode.description == "New description"

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_UPDATE_DATA)
    async def test_update__invalid_request__fail(
        self,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
        invalid_data: dict,
        error_details: dict,
    ):
        await client.login(user)
        url = self.url.format(id=episode.id)
        self.assert_bad_request(client.patch(url, json=invalid_data), error_details)

    async def test_update__episode_from_another_user__fail(self, client, episode: Episode, dbs):
        await client.login(await create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.patch(url, json={}), episode)

    async def test_delete__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
        mocked_s3: MockS3Client,
    ):
        await client.login(user)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert await Episode.async_get(dbs, id=episode.id) is None
        mocked_s3.delete_files_async.assert_any_call([episode.audio.name], remote_path="audio")
        mocked_s3.delete_files_async.assert_any_call(
            [episode.image.name], remote_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH
        )

    async def test_delete__episode_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode: Episode,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.delete(url), episode)

    @pytest.mark.parametrize("status", (EpisodeStatus.DOWNLOADING, EpisodeStatus.CANCELING))
    async def test_delete__episode_in_progress_state__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
        status: EpisodeStatus,
    ):
        await client.login(user)
        await episode.update(dbs, status=status, db_commit=True)

        url = self.url.format(id=episode.id)
        response = client.delete(url)
        response_data = response.json()
        assert response_data["payload"]["details"] == f"Can't remove episode in '{status}' status"
        assert await Episode.async_get(dbs, id=episode.id) is not None

    @pytest.mark.parametrize(
        "same_episode_status, delete_called",
        [
            (Episode.Status.NEW, True),
            (Episode.Status.PUBLISHED, False),
            (Episode.Status.DOWNLOADING, True),
        ],
    )
    async def test_delete__same_episode_exists__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode_data: dict,
        mocked_s3: MockS3Client,
        same_episode_status: EpisodeStatus,
        delete_called: bool,
    ):
        source_id = get_source_id()

        user_1 = await create_user(dbs)
        user_2 = await create_user(dbs)

        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_1.id))
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user_2.id))

        # episode-1 (from another podcast)
        episode_data["source_id"] = source_id
        episode_data["owner_id"] = user_1.id
        await create_episode(dbs, episode_data, podcast_1, status=same_episode_status)

        # episode-2 (will be removed)
        episode_data["owner_id"] = user_2.id
        episode_2 = await create_episode(
            dbs, episode_data, podcast_2, status=Episode.Status.PUBLISHED
        )

        url = self.url.format(id=episode_2.id)
        await client.login(user_2)
        response = client.delete(url)
        assert response.status_code == 204, f"Delete API is not available: {response.text}"

        assert await Episode.async_get(dbs, id=episode_2.id) is None

        if delete_called:
            mocked_s3.delete_files_async.assert_any_call(
                [episode_2.audio.name], remote_path=settings.S3_BUCKET_AUDIO_PATH
            )

        mocked_s3.delete_files_async.assert_any_call(
            [episode_2.image.name], remote_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH
        )

    @pytest.mark.parametrize(
        "episode_status",
        (
            Episode.Status.NEW,
            Episode.Status.PUBLISHED,
            Episode.Status.ERROR,
        ),
    )
    @patch("modules.podcast.tasks.base.RQTask.cancel_task")
    async def test_delete__no_cancel_task(
        self,
        mock_cancel_task: Mock,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
        mocked_s3: MockS3Client,
        episode_status: EpisodeStatus,
    ):
        await episode.update(dbs, status=episode_status, db_commit=True)
        await client.login(user)

        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert await Episode.async_get(dbs, id=episode.id) is None

        mock_cancel_task.assert_not_called()
        mocked_s3.delete_files_async.assert_called()
        mocked_s3.delete_files_async.assert_called()


class TestEpisodeDownloadAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/download/"

    @pytest.mark.parametrize(
        "source_type, task",
        (
            (SourceType.YOUTUBE, DownloadEpisodeTask),
            (SourceType.YANDEX, DownloadEpisodeTask),
            (SourceType.UPLOAD, UploadedEpisodeTask),
        ),
    )
    async def test_download__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
        mocked_rq_queue: MockRQQueue,
        source_type: SourceType,
        task: Type[DownloadEpisodeTask],
    ):
        await episode.update(dbs, source_type=source_type, db_commit=True)
        assert episode.status == EpisodeStatus.NEW

        await client.login(user)
        url = self.url.format(id=episode.id)
        response = client.put(url)
        response_data = self.assert_ok_response(response)
        await dbs.refresh(episode)
        assert episode.status == EpisodeStatus.DOWNLOADING
        assert response_data == _episode_details(episode, status=EpisodeStatus.DOWNLOADING)
        mocked_rq_queue.enqueue.assert_called_with(
            task(), episode_id=episode.id, job_id=task.get_job_id(episode_id=episode.id)
        )

    async def test_download__episode_from_another_user__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode: Episode,
    ):
        await client.login(await create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.put(url), episode)


class TestEpisodeCancelDownloadingAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/cancel-downloading/"
    default_fail_response_status = ResponseStatus.INVALID_PARAMETERS

    @patch("modules.podcast.tasks.download.DownloadEpisodeTask.cancel_task")
    @patch("modules.podcast.tasks.download.DownloadEpisodeImageTask.cancel_task")
    async def test_cancel_downloading__ok(
        self,
        mocked_cancel_download_episode_task: Mock,
        mocked_cancel_download_image_task: Mock,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode: Episode,
    ):
        await episode.update(dbs, status=EpisodeStatus.DOWNLOADING, db_commit=True)
        await client.login(user)
        url = self.url.format(id=episode.id)
        response_data = self.assert_ok_response(client.put(url))
        await dbs.refresh(episode)
        assert episode.status == EpisodeStatus.CANCELING
        assert response_data == _episode_details(episode, status=EpisodeStatus.CANCELING)

        mocked_cancel_download_episode_task.assert_called_with(episode_id=episode.id)
        mocked_cancel_download_image_task.assert_called_with(episode_id=episode.id)

    @patch("modules.podcast.tasks.download.DownloadEpisodeTask.cancel_task")
    @patch("modules.podcast.tasks.download.DownloadEpisodeImageTask.cancel_task")
    async def test_cancel_downloading__episode_not_in_progress__fail(
        self,
        mocked_cancel_download_episode_task: Mock,
        mocked_cancel_download_image_task: Mock,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode: Episode,
        user: User,
    ):
        await episode.update(dbs, status=EpisodeStatus.NEW, db_commit=True)
        await client.login(user)
        url = self.url.format(id=episode.id)
        response_data = self.assert_fail_response(client.put(url), status_code=400)
        assert response_data["details"] == (
            f"Episode #{episode.id} not found or is not in progress now"
        )
        await dbs.refresh(episode)
        assert episode.status == EpisodeStatus.NEW
        mocked_cancel_download_episode_task.assert_not_called()
        mocked_cancel_download_image_task.assert_not_called()


class TestEpisodeFlatListAPIView(BaseTestAPIView):
    url = "/api/episodes/"

    async def setup_episodes(self, dbs: AsyncSession, user: User, episode_data: dict):
        self.user_2 = await create_user(dbs)
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        podcast_3_from_user_2 = await Podcast.async_create(
            dbs, **get_podcast_data(owner_id=self.user_2.id)
        )
        episode_data |= {"owner_id": user.id}
        self.episode_1 = await create_episode(dbs, episode_data, podcast_1)
        self.episode_2 = await create_episode(dbs, episode_data, podcast_2)

        episode_data["owner_id"] = self.user_2.id
        self.episode_3 = await create_episode(dbs, episode_data, podcast_3_from_user_2)

    @staticmethod
    def assert_episodes(response_data: dict, expected_episode_ids: list[int]):
        actual_episode_ids = [episode["id"] for episode in response_data["items"]]
        assert actual_episode_ids == expected_episode_ids

    async def test_get_list__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        episode_data: dict,
        user: User,
    ):
        await self.setup_episodes(dbs, user, episode_data)

        await client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        expected_episode_ids = [self.episode_2.id, self.episode_1.id]
        self.assert_episodes(response_data, expected_episode_ids)

    async def test_get_list__limited__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode_data: dict,
    ):
        await self.setup_episodes(dbs, user, episode_data)
        await client.login(user)
        response = client.get(self.url, params={"limit": 1})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episode_ids=[self.episode_2.id])
        assert response_data.get("has_next") is True, response_data

    async def test_get_list__offset__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode_data: dict,
    ):
        await self.setup_episodes(dbs, user, episode_data)
        await client.login(user)
        response = client.get(self.url, params={"offset": 1})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episode_ids=[self.episode_1.id])
        assert response_data.get("has_next") is False, response_data

    @pytest.mark.parametrize(
        "search,title1,title2,expected_titles",
        [
            ("new", "New episode", "Old episode", ["New episode"]),
            ("epi", "New episode", "Old episode", ["New episode", "Old episode"]),
        ],
    )
    async def test_get_list__filter_by_title__ok(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
        episode_data: dict,
        search: str,
        title1: str,
        title2: str,
        expected_titles: list[str],
    ):
        await self.setup_episodes(dbs, user, episode_data)
        await self.episode_1.update(dbs, **{"title": title1})
        await self.episode_2.update(dbs, **{"title": title2})
        await dbs.commit()
        await dbs.refresh(self.episode_1)
        await dbs.refresh(self.episode_2)

        episodes = [self.episode_2, self.episode_1]
        expected_episodes = [episode.id for episode in episodes if episode.title in expected_titles]
        await client.login(user)
        response = client.get(self.url, params={"q": search})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episodes)

    async def test_create_without_podcast__fail(
        self,
        dbs: AsyncSession,
        client: PodcastTestClient,
        user: User,
    ):
        await client.login(user)
        response = client.post(self.url, data=get_podcast_data())
        self.assert_fail_response(
            response, status_code=405, response_status=ResponseStatus.NOT_ALLOWED
        )

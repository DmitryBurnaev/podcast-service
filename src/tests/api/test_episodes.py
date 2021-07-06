import pytest

from modules.youtube.exceptions import YoutubeFetchError
from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast
from modules.podcast.tasks import DownloadEpisodeTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_video_id, create_user, get_podcast_data, create_episode, async_run

INVALID_UPDATE_DATA = [
    [{"title": "title" * 100}, {"title": "Longer than maximum length 256."}],
    [{"author": "author" * 100}, {"author": "Longer than maximum length 256."}],
]

INVALID_CREATE_DATA = [
    [{"source_url": "fake-url"}, {"source_url": "Not a valid URL."}],
    [{}, {"source_url": "Missing data for required field."}],
]


def _episode_in_list(episode: Episode):
    return {
        "id": episode.id,
        "title": episode.title,
        "status": str(episode.status),
        "image_url": episode.image_url,
        "created_at": episode.created_at.isoformat(),
    }


def _episode_details(episode: Episode):
    return {
        "id": episode.id,
        "title": episode.title,
        "author": episode.author,
        "status": str(episode.status),
        "length": episode.length,
        "watch_url": episode.watch_url,
        "remote_url": episode.remote_url,
        "image_url": episode.image_url,
        "file_size": episode.file_size,
        "description": episode.description,
        "created_at": episode.created_at.isoformat(),
        "published_at": episode.published_at.isoformat() if episode.published_at else None,
    }


class TestEpisodeListCreateAPIView(BaseTestAPIView):
    url = "/api/podcasts/{id}/episodes/"

    def test_get_list__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.podcast_id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == [_episode_in_list(episode)]

    def test_create__ok(self, client, podcast, episode, episode_data, user, mocked_episode_creator):
        mocked_episode_creator.create.return_value = mocked_episode_creator.async_return(episode)
        client.login(user)
        episode_data = {"source_url": episode_data["watch_url"]}
        url = self.url.format(id=podcast.id)
        response = client.post(url, json=episode_data)
        response_data = self.assert_ok_response(response, status_code=201)
        assert response_data == _episode_in_list(episode)
        mocked_episode_creator.target_class.__init__.assert_called_with(
            mocked_episode_creator.target_obj,
            podcast_id=podcast.id,
            source_url=episode_data["source_url"],
            user_id=user.id,
        )
        mocked_episode_creator.create.assert_called_once()

    def test_create__start_downloading__ok(
        self, client, podcast, episode, episode_data, user, mocked_episode_creator, mocked_rq_queue
    ):
        mocked_episode_creator.create.return_value = mocked_episode_creator.async_return(episode)
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": episode_data["watch_url"]})
        self.assert_ok_response(response, status_code=201)
        mocked_rq_queue.enqueue.assert_called_with(
            tasks.DownloadEpisodeTask(), episode_id=episode.id
        )

    def test_create__youtube_error__fail(
        self, client, podcast, episode_data, user, mocked_episode_creator
    ):
        mocked_episode_creator.create.side_effect = YoutubeFetchError("Oops")
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": episode_data["watch_url"]})
        response_data = self.assert_fail_response(response, status_code=500)
        assert response_data == {
            "error": "We couldn't extract info about requested episode.",
            "details": "Oops",
        }

    @pytest.mark.parametrize("invalid_data, error_details", INVALID_CREATE_DATA)
    def test_create__invalid_request__fail(
        self, client, podcast, user, invalid_data: dict, error_details: dict
    ):
        client.login(user)
        url = self.url.format(id=podcast.id)
        self.assert_bad_request(client.post(url, json=invalid_data), error_details)

    def test_create__podcast_from_another_user__fail(self, client, podcast, db_session):
        client.login(create_user(db_session))
        url = self.url.format(id=podcast.id)
        data = {"source_url": "http://link.to.resource/"}
        self.assert_not_found(client.post(url, json=data), podcast)


class TestEpisodeRUDAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/"

    def test_get_details__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)

    def test_get_details__episode_from_another_user__fail(self, client, episode, user, db_session):
        client.login(create_user(db_session))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.get(url), episode)

    def test_update__ok(self, client, episode, user, db_session):
        client.login(user)
        url = self.url.format(id=episode.id)
        patch_data = {
            "title": "New title",
            "author": "New author",
            "description": "New description",
        }
        response = client.patch(url, json=patch_data)
        episode = async_run(Episode.async_get(db_session, id=episode.id))

        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)
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

    def test_update__episode_from_another_user__fail(self, client, episode, db_session):
        client.login(create_user(db_session))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.patch(url, json={}), episode)

    def test_delete__ok(self, client, episode, user, mocked_s3, db_session):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert async_run(Episode.async_get(db_session, id=episode.id)) is None
        mocked_s3.delete_files_async.assert_called_with([episode.file_name])

    def test_delete__episode_from_another_user__fail(self, client, episode, user, db_session):
        client.login(create_user(db_session))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.delete(url), episode)

    @pytest.mark.parametrize(
        "same_episode_status, delete_called",
        [
            (Episode.Status.NEW, True),
            (Episode.Status.PUBLISHED, False),
            (Episode.Status.DOWNLOADING, False),
        ],
    )
    def test_delete__same_episode_exists__ok(
        self,
        client,
        podcast,
        episode_data,
        mocked_s3,
        same_episode_status,
        delete_called,
        db_session,
    ):
        source_id = get_video_id()

        user_1 = create_user(db_session)
        user_2 = create_user(db_session)

        podcast_1 = async_run(Podcast.async_create(**get_podcast_data(created_by_id=user_1.id)))
        podcast_2 = async_run(Podcast.async_create(**get_podcast_data(created_by_id=user_2.id)))

        episode_data["created_by_id"] = user_1.id
        _ = create_episode(episode_data, podcast_1, status=same_episode_status, source_id=source_id)

        episode_data["created_by_id"] = user_2.id
        episode_2 = create_episode(
            episode_data, podcast_2, status=Episode.Status.NEW, source_id=source_id
        )

        url = self.url.format(id=episode_2.id)
        client.login(user_2)
        response = client.delete(url)
        assert response.status_code == 204, f"Delete API is not available: {response.text}"
        assert async_run(Episode.async_get(db_session, id=episode_2.id)) is None
        if delete_called:
            mocked_s3.delete_files_async.assert_called_with([episode_2.file_name])
        else:
            assert not mocked_s3.delete_files_async.called


class TestEpisodeDownloadAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/download/"

    def test_download__ok(self, client, episode, user, mocked_rq_queue, db_session):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.put(url)
        episode = async_run(Episode.async_get(db_session, id=episode.id))
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)
        mocked_rq_queue.enqueue.assert_called_with(DownloadEpisodeTask(), episode_id=episode.id)

    def test_download__episode_from_another_user__fail(self, client, episode, user, db_session):
        client.login(create_user(db_session))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.put(url), episode)

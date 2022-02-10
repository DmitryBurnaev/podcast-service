import pytest

from common.enums import SourceType
from common.statuses import ResponseStatus
from modules.providers.exceptions import SourceFetchError
from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast, Cookie
from modules.podcast.tasks import DownloadEpisodeTask
from tests.api.test_base import BaseTestAPIView
from tests.helpers import get_video_id, create_user, get_podcast_data, create_episode, await_


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
        "source_type": str(SourceType.YOUTUBE),
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
        "source_type": str(SourceType.YOUTUBE),
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
        assert response_data["items"] == [_episode_in_list(episode)]

    def test_create__ok(
        self,
        client,
        podcast,
        episode,
        episode_data,
        user,
        mocked_episode_creator,
        mocked_rq_queue,
        dbs,
    ):
        mocked_episode_creator.create.return_value = mocked_episode_creator.async_return(episode)
        client.login(user)
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
            tasks.DownloadEpisodeImageTask(), episode_id=episode.id
        )

    def test_create__start_downloading__ok(
        self, client, podcast, episode, episode_data, user, mocked_episode_creator, mocked_rq_queue
    ):
        mocked_episode_creator.create.return_value = mocked_episode_creator.async_return(episode)
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": episode_data["watch_url"]})
        self.assert_ok_response(response, status_code=201)

        expected_calls = [
            {"args": (tasks.DownloadEpisodeTask(),), "kwargs": {"episode_id": episode.id}},
            {"args": (tasks.DownloadEpisodeImageTask(),), "kwargs": {"episode_id": episode.id}},
        ]
        actual_calls = [
            {"args": call.args, "kwargs": call.kwargs}
            for call in mocked_rq_queue.enqueue.call_args_list
        ]
        assert actual_calls == expected_calls

    def test_create__youtube_error__fail(
        self, client, podcast, episode_data, user, mocked_episode_creator
    ):
        mocked_episode_creator.create.side_effect = SourceFetchError("Oops")
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

    def test_create__podcast_from_another_user__fail(self, client, podcast, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=podcast.id)
        data = {"source_url": "http://link.to.resource/"}
        self.assert_not_found(client.post(url, json=data), podcast)


class TestCreateEpisodesWithCookies(BaseTestAPIView):
    source_url = "http://link.to.source/"
    cdata = {"data": "cookie in netscape format", "source_type": SourceType.YANDEX}

    def _request(self, client, user, podcast) -> dict:
        client.login(user)
        url = self.url.format(id=podcast.id)
        response = client.post(url, json={"source_url": self.source_url})
        return self.assert_ok_response(response, status_code=201)

    @staticmethod
    def _assert_source(response_data, dbs, cookie_id):
        episode = await_(Episode.async_get(dbs, id=response_data["id"]))
        assert response_data["source_type"] == SourceType.YANDEX
        assert episode.source_id == "source-id"
        assert episode.source_type == SourceType.YANDEX
        assert episode.cookie_id == cookie_id

    def test_no_cookies_found(self, mocked_source_info, dbs, client, user, podcast):
        response_data = self._request(client, user, podcast)
        self._assert_source(response_data, dbs, cookie_id=None)

    def test_specific_cookie(self, mocked_source_info, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        await_(Cookie.async_create(dbs, **(cdata | {"source_type": SourceType.YANDEX})))
        cookie_yandex = await_(Cookie.async_create(dbs, **cdata))
        response_data = self._request(client, user, podcast)
        self._assert_source(response_data, dbs, cookie_id=cookie_yandex.id)
        mocked_source_info.assert_called_with(self.source_url)

    def test_cookie_from_another_user(self, mocked_source_info, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        cookie_yandex = await_(Cookie.async_create(dbs, **cdata))
        cdata = self.cdata | {"created_by_id": create_user(dbs).id}
        await_(Cookie.async_create(dbs, **cdata))

        response_data = self._request(client, user, podcast)
        self._assert_source(response_data, dbs, cookie_id=cookie_yandex.id)

    def test_use_last_cookie(self, mocked_source_info, dbs, client, user, podcast):
        cdata = self.cdata | {"created_by_id": user.id}
        await_(Cookie.async_create(dbs, **cdata))
        c2 = await_(Cookie.async_create(dbs, **cdata))
        response_data = self._request(client, user, podcast)

        self._assert_source(response_data, dbs, cookie_id=c2.id)


class TestEpisodeRUDAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/"

    def test_get_details__ok(self, client, episode, user):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.get(url)
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)

    def test_get_details__episode_from_another_user__fail(self, client, episode, user, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.get(url), episode)

    def test_update__ok(self, client, episode, user, dbs):
        client.login(user)
        url = self.url.format(id=episode.id)
        patch_data = {
            "title": "New title",
            "author": "New author",
            "description": "New description",
        }
        response = client.patch(url, json=patch_data)
        await_(dbs.refresh(episode))

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

    def test_update__episode_from_another_user__fail(self, client, episode, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.patch(url, json={}), episode)

    def test_delete__ok(self, client, episode, user, mocked_s3, dbs):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.delete(url)
        assert response.status_code == 204
        assert await_(Episode.async_get(dbs, id=episode.id)) is None
        mocked_s3.delete_files_async.assert_called_with([episode.file_name])

    def test_delete__episode_from_another_user__fail(self, client, episode, user, dbs):
        client.login(create_user(dbs))
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
        dbs,
    ):
        source_id = get_video_id()

        user_1 = create_user(dbs)
        user_2 = create_user(dbs)

        podcast_1 = await_(
            Podcast.async_create(dbs, db_commit=True, **get_podcast_data(created_by_id=user_1.id))
        )
        podcast_2 = await_(
            Podcast.async_create(dbs, db_commit=True, **get_podcast_data(created_by_id=user_2.id))
        )

        episode_data["created_by_id"] = user_1.id
        _ = create_episode(
            dbs, episode_data, podcast_1, status=same_episode_status, source_id=source_id
        )

        episode_data["created_by_id"] = user_2.id
        episode_2 = create_episode(
            dbs, episode_data, podcast_2, status=Episode.Status.NEW, source_id=source_id
        )

        url = self.url.format(id=episode_2.id)
        client.login(user_2)
        response = client.delete(url)
        assert response.status_code == 204, f"Delete API is not available: {response.text}"
        assert await_(Episode.async_get(dbs, id=episode_2.id)) is None
        if delete_called:
            mocked_s3.delete_files_async.assert_called_with([episode_2.file_name])
        else:
            assert not mocked_s3.delete_files_async.called


class TestEpisodeDownloadAPIView(BaseTestAPIView):
    url = "/api/episodes/{id}/download/"

    def test_download__ok(self, client, episode, user, mocked_rq_queue, dbs):
        client.login(user)
        url = self.url.format(id=episode.id)
        response = client.put(url)
        await_(dbs.refresh(episode))
        response_data = self.assert_ok_response(response)
        assert response_data == _episode_details(episode)
        mocked_rq_queue.enqueue.assert_called_with(DownloadEpisodeTask(), episode_id=episode.id)

    def test_download__episode_from_another_user__fail(self, client, episode, user, dbs):
        client.login(create_user(dbs))
        url = self.url.format(id=episode.id)
        self.assert_not_found(client.put(url), episode)


class TestEpisodeFlatListAPIView(BaseTestAPIView):
    url = "/api/episodes/"

    def setup_episodes(self, dbs, user, episode_data):
        self.user_2 = create_user(dbs)
        podcast_1 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user.id)))
        podcast_2 = await_(Podcast.async_create(dbs, **get_podcast_data(created_by_id=user.id)))
        podcast_3_from_user_2 = await_(
            Podcast.async_create(dbs, **get_podcast_data(created_by_id=self.user_2.id))
        )
        episode_data = episode_data | {"created_by_id": user.id}
        self.episode_1 = create_episode(dbs, episode_data, podcast_1)
        self.episode_2 = create_episode(dbs, episode_data, podcast_2)

        episode_data["created_by_id"] = self.user_2.id
        self.episode_3 = create_episode(dbs, episode_data, podcast_3_from_user_2)
        await_(dbs.commit())

    @staticmethod
    def assert_episodes(response_data: dict, expected_episode_ids: list[int]):
        actual_episode_ids = [episode["id"] for episode in response_data["items"]]
        assert actual_episode_ids == expected_episode_ids

    def test_get_list__ok(self, client, episode_data, user, dbs):
        self.setup_episodes(dbs, user, episode_data)

        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        expected_episode_ids = [self.episode_2.id, self.episode_1.id]
        self.assert_episodes(response_data, expected_episode_ids)

    def test_get_list__limited__ok(self, client, episode_data, user, dbs):
        self.setup_episodes(dbs, user, episode_data)
        client.login(user)
        response = client.get(self.url, params={"limit": 1})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episode_ids=[self.episode_2.id])
        assert response_data["has_next"] is True, response_data

    def test_get_list__offset__ok(self, client, episode_data, user, dbs):
        self.setup_episodes(dbs, user, episode_data)
        client.login(user)
        response = client.get(self.url, params={"offset": 1})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episode_ids=[self.episode_1.id])
        assert response_data["has_next"] is False, response_data

    @pytest.mark.parametrize(
        "search,title1,title2,expected_titles",
        [
            ("new", "New episode", "Old episode", ["New episode"]),
            ("epi", "New episode", "Old episode", ["New episode", "Old episode"]),
        ],
    )
    def test_get_list__filter_by_title__ok(
        self, client, episode_data, user, dbs, search, title1, title2, expected_titles
    ):
        self.setup_episodes(dbs, user, episode_data)
        await_(self.episode_1.update(dbs, **{"title": title1}))
        await_(self.episode_2.update(dbs, **{"title": title2}))
        await_(dbs.commit())
        await_(dbs.refresh(self.episode_1))
        await_(dbs.refresh(self.episode_2))

        episodes = [self.episode_2, self.episode_1]
        expected_episodes = [episode.id for episode in episodes if episode.title in expected_titles]
        client.login(user)
        response = client.get(self.url, params={"q": search})
        response_data = self.assert_ok_response(response)
        self.assert_episodes(response_data, expected_episodes)

    def test_create_without_podcast__fail(self, client, episode_data, user, dbs):
        client.login(user)
        response = client.post(self.url, data=get_podcast_data())
        self.assert_fail_response(
            response, status_code=405, response_status=ResponseStatus.NOT_ALLOWED
        )

import logging

from starlette import status

from common.db_utils import db_transaction
from common.views import BaseHTTPEndpoint
from modules.podcast import tasks
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Episode, Podcast
from modules.podcast.serializers import (
    EpisodeCreateModel,
    EpisodeListModel,
    EpisodeDetailsModel,
    EpisodeUpdateModel,
)


logger = logging.getLogger(__name__)


class EpisodeListCreateAPIView(BaseHTTPEndpoint):
    schema_request = EpisodeCreateModel
    schema_response = EpisodeListModel

    async def get(self, request):
        podcast_id = request.path_params['podcast_id']
        episodes = await Episode.async_filter(podcast_id=podcast_id)
        return self._response(episodes)

    @db_transaction
    async def post(self, request):
        podcast_id = request.path_params['podcast_id']
        podcast = await self._get_object(podcast_id, db_model=Podcast)
        episode_data: EpisodeCreateModel = await self._validate(request)
        episode_creator = EpisodeCreator(
            podcast_id=podcast_id,
            youtube_link=episode_data.youtube_link,
            user_id=request.user.id,
        )
        episode = await episode_creator.create()
        if podcast.download_automatically:
            await episode.update(status=Episode.Status.DOWNLOADING).apply()
            await self._run_task(
                tasks.download_episode, youtube_link=episode.watch_url, episode_id=episode.id,
            )

        return self._response(episode, status_code=status.HTTP_201_CREATED)


class EpisodeRUDAPIView(BaseHTTPEndpoint):
    db_model = Episode
    schema_request = EpisodeUpdateModel
    schema_response = EpisodeDetailsModel

    async def get(self, request):
        episode_id = request.path_params['episode_id']
        episode = await self._get_object(episode_id)
        return self._response(episode)

    @db_transaction
    async def patch(self, request):
        episode_id = request.path_params['episode_id']
        episode_data: EpisodeUpdateModel = await self._validate(request)
        episode = await self._get_object(episode_id)
        await episode.update(**episode_data.dict()).apply()
        return self._response(episode)

    @db_transaction
    async def delete(self, request):
        episode_id = request.path_params['episode_id']
        episode = await self._get_object(episode_id)
        await episode.delete()
        # TODO: remove episode from the cloud
        return self._response(None, status_code=status.HTTP_204_NO_CONTENT)

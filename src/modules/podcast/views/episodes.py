from starlette import status

from common.storage import StorageS3
from common.utils import get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast import tasks
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Episode, Podcast
from modules.podcast.schemas import (
    EpisodeListSchema,
    EpisodeCreateSchema,
    EpisodeUpdateSchema,
    EpisodeDetailsSchema,
)

logger = get_logger(__name__)


class EpisodeListCreateAPIView(BaseHTTPEndpoint):
    """ List and Create (based on `EpisodeCreator` logic) API for episodes """

    schema_request = EpisodeCreateSchema
    schema_response = EpisodeListSchema

    async def get(self, request):
        podcast_id = request.path_params["podcast_id"]
        episodes = await Episode.async_filter(self.db_session, podcast_id=podcast_id)
        return self._response(episodes)

    async def post(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id, db_model=Podcast)
        cleaned_data = await self._validate(request)
        episode_creator = EpisodeCreator(
            self.db_session,
            podcast_id=podcast_id,
            source_url=cleaned_data["source_url"],
            user_id=request.user.id,
        )
        episode = await episode_creator.create()
        if podcast.download_automatically:
            await episode.update(status=Episode.Status.DOWNLOADING).apply()
            await self._run_task(tasks.DownloadEpisodeTask, episode_id=episode.id)

        return self._response(episode, status_code=status.HTTP_201_CREATED)


class EpisodeRUDAPIView(BaseHTTPEndpoint):
    """ Retrieve, Update, Delete API for episodes """

    db_model = Episode
    schema_request = EpisodeUpdateSchema
    schema_response = EpisodeDetailsSchema

    async def get(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        return self._response(episode)

    async def patch(self, request):
        episode_id = request.path_params["episode_id"]
        cleaned_data = await self._validate(request, partial_=True)
        episode = await self._get_object(episode_id)
        await episode.update(**cleaned_data).apply()
        return self._response(episode)

    async def delete(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        await episode.delete()
        await self._delete_file(episode)
        return self._response(None, status_code=status.HTTP_204_NO_CONTENT)

    async def _delete_file(self, episode: Episode):
        """ Removing file associated with requested episode """

        same_file_episodes = await Episode.async_filter(
            self.db_session,
            source_id=episode.source_id,
            status__ne=Episode.Status.NEW,
            id__ne=episode.id,
        )
        if same_file_episodes:
            episode_ids = ",".join([f"#{episode.id}" for episode in same_file_episodes])
            logger.warning(
                f"There are another episodes for file {episode.file_name}: {episode_ids}. "
                f"Skip file removing."
            )
            return

        return await StorageS3().delete_files_async([episode.file_name])


class EpisodeDownloadAPIView(BaseHTTPEndpoint):
    """ RUN episode's downloading (enqueue background task in RQ) """

    db_model = Episode
    schema_request = EpisodeUpdateSchema
    schema_response = EpisodeDetailsSchema

    async def put(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)

        logger.info(f'Start download process for "{episode.watch_url}"')
        episode.status = Episode.Status.DOWNLOADING
        await episode.update(status=episode.status).apply()
        await self._run_task(tasks.DownloadEpisodeTask, episode_id=episode.id)
        return self._response(episode)

from sqlalchemy import select, func
from starlette import status

from core import settings
from common.utils import get_logger
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.db_utils import db_transaction
from modules.podcast.models import Podcast, Episode
from modules.podcast.schemas import PodcastCreateUpdateSchema, PodcastDetailsSchema
from modules.podcast.tasks.rss import GenerateRSSTask

logger = get_logger(__name__)


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    """ List and Create API for podcasts """

    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema
    auth_backend = None

    async def get(self, request):
        func_count = func.count(Episode.id).label("episodes_count")
        stmt = (
            select([Podcast, func_count])
            .join(Episode, Episode.podcast_id == Podcast.id)
            # TODO: rollback user
            .filter(Podcast.created_by_id == 1)
            .group_by(Podcast.id)
            .order_by(Podcast.id)
        )
        podcasts = await request.db_session.execute(stmt)
        podcast_list = []
        for podcast, episodes_count in podcasts.all():
            podcast.episodes_count = episodes_count
            podcast_list.append(podcast)

        return self._response(podcast_list)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        # TODO:fix podcast creation
        podcast = await Podcast.create(
            db_session=request.db_session,
            name=cleaned_data["name"],
            publish_id=Podcast.generate_publish_id(),
            description=cleaned_data["description"],
            # TODO: rollback user
            created_by_id=1,
        )
        return self._response(podcast, status_code=status.HTTP_201_CREATED)


class PodcastRUDAPIView(BaseHTTPEndpoint):
    """ Retrieve, Update, Delete API for podcasts """

    db_model = Podcast
    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        return self._response(podcast)

    @db_transaction
    async def patch(self, request):
        cleaned_data = await self._validate(request, partial_=True)
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        await podcast.update(**cleaned_data).apply()
        return self._response(podcast)

    @db_transaction
    async def delete(self, request):
        podcast_id = int(request.path_params["podcast_id"])
        podcast = await self._get_object(podcast_id)
        episodes = await Episode.async_filter(podcast_id=podcast_id)
        await podcast.delete()
        await self._delete_files(podcast, episodes)
        return self._response(status_code=status.HTTP_204_NO_CONTENT)

    @staticmethod
    async def _delete_files(podcast: Podcast, episodes: list[Episode]):
        podcast_file_names = {
            episode.file_name for episode in episodes if episode.status == Episode.Status.PUBLISHED
        }
        same_file_episodes = await Episode.async_filter(
            podcast_id__ne=podcast.id,
            file_name__in=podcast_file_names,
            status=Episode.Status.PUBLISHED,
        )
        exist_file_names = {episode.file_name for episode in same_file_episodes or []}

        files_to_remove = podcast_file_names - exist_file_names
        files_to_skip = exist_file_names & podcast_file_names
        if files_to_skip:
            logger.warning(
                "There are another episodes with files %s. Skip this files removing.",
                files_to_skip,
            )

        storage = StorageS3()
        await storage.delete_files_async(
            [f"{podcast.publish_id}.xml"], remote_path=settings.S3_BUCKET_RSS_PATH
        )
        if files_to_remove:
            await storage.delete_files_async(list(files_to_remove))


class PodcastGenerateRSSAPIView(BaseHTTPEndpoint):
    """ Allows to start RSS generation task """

    db_model = Podcast

    async def put(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        await self._run_task(GenerateRSSTask, podcast.id)
        return self._response(status_code=status.HTTP_204_NO_CONTENT)

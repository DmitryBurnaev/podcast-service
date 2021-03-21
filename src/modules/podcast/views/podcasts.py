from starlette import status

from core import settings
from common.utils import get_logger
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.db_utils import db_transaction
from core.database import db
from modules.podcast.models import Podcast, Episode
from modules.podcast.schemas import PodcastCreateUpdateSchema, PodcastDetailsSchema
from modules.podcast.tasks.rss import GenerateRSSTask

logger = get_logger(__name__)


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    """ List and Create API for podcasts """

    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        episodes_count = db.func.count(Episode.id)
        # podcasts = await Podcast.join(Episode).select(Podcast).group_by(*Podcast.__dict__).gino.all()
        # podcasts = await Podcast.join(Episode).select(Podcast.id, Episode.status).gino.all()
        # podcasts = await Podcast.join(Episode).select([Podcast, episodes_count]).group_by(*Podcast.__dict__).gino.all()



        # q = db.select([
        #     Podcast,
        #     episodes_count,
        # ]).select_from(
        #     Podcast.outerjoin(Episode)
        # ).group_by(
        #     *Podcast,
        # ).gino.load((Podcast, ColumnLoader(episodes_count)))
        # async with db.transaction():
        #     podcasts = await q.iterate()
        # TODO: we need to add aggregation for this query
        podcasts = await Podcast.async_filter(created_by_id=request.user.id)
        return self._response(podcasts)

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        podcast = await Podcast.create(
            name=cleaned_data["name"],
            publish_id=Podcast.generate_publish_id(),
            description=cleaned_data["description"],
            created_by_id=request.user.id,
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

from starlette import status

from common.db_utils import db_transaction
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Podcast
from modules.podcast.schemas import *
from modules.podcast.tasks.rss import GenerateRSS


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        podcasts = await Podcast.async_filter(created_by_id=request.user.id)
        return self._response(podcasts)

    @db_transaction
    async def post(self, request):
        cleaned_data = await self._validate(request)
        podcast = await Podcast.create(
            name=cleaned_data["name"],
            publish_id=Podcast.generate_publish_id(),
            description=cleaned_data["description"],
            created_by_id=request.user.id
        )
        return self._response(podcast, status_code=status.HTTP_201_CREATED)


class PodcastRUDAPIView(BaseHTTPEndpoint):
    db_model = Podcast
    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        podcast_id = request.path_params['podcast_id']
        podcast = await self._get_object(podcast_id)
        return self._response(podcast)

    @db_transaction
    async def patch(self, request):
        cleaned_data = await self._validate(request, partial=True)
        podcast_id = request.path_params['podcast_id']
        podcast = await self._get_object(podcast_id)
        await podcast.update(**cleaned_data).apply()
        return self._response(podcast)

    @db_transaction
    async def delete(self, request):
        podcast_id = int(request.path_params['podcast_id'])
        podcast = await self._get_object(podcast_id)
        await podcast.delete()
        return self._response(status_code=status.HTTP_204_NO_CONTENT)


class PodcastGenerateRSSAPIView(BaseHTTPEndpoint):
    """ Allows to start RSS generation task """

    db_model = Podcast

    async def put(self, request):
        podcast_id = request.path_params['podcast_id']
        podcast = await self._get_object(podcast_id)
        await self._run_task(GenerateRSS, podcast.id)
        return self._response(status_code=status.HTTP_204_NO_CONTENT)
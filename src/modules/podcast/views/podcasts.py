from marshmallow import Schema
from starlette import status

from common.db_utils import db_transaction
from common.views import BaseHTTPEndpoint
from modules.podcast.models import Podcast
from modules.podcast.serializers import (
    PodcastCreateModel,
    PodcastListModel,
    PodcastDetailsModel,
    PodcastUpdateModel,
)
from webargs import fields
from webargs_starlette import parser


class PodcastRequestSchema(Schema):
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    download_automatically = fields.Bool(required=True)


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    model = PodcastCreateModel
    model_response = PodcastListModel

    async def get(self, request):
        podcasts = await Podcast.async_filter(created_by_id=request.user.id)
        return self._response(podcasts)

    @db_transaction
    async def post(self, request):
        podcast_data: PodcastCreateModel = await self._validate(request)
        podcast = await Podcast.create(
            name=podcast_data.name,
            publish_id=Podcast.generate_publish_id(),
            description=podcast_data.description,
            created_by_id=request.user.id
        )
        return self._response(podcast, status_code=status.HTTP_201_CREATED)


class PodcastRUDAPIView(BaseHTTPEndpoint):
    db_model = Podcast
    model = PodcastUpdateModel
    model_response = PodcastDetailsModel
    request_schema = PodcastRequestSchema

    async def get(self, request):
        podcast_id = request.path_params['podcast_id']
        podcast = await self.get_object(podcast_id)
        return self._response(podcast)

    @db_transaction
    async def patch(self, request):
        # schema = self.request_schema(partial=("description",))
        # cleaned_data = await parser.parse(self.request_schema, request)
        podcast_data: PodcastUpdateModel = await self._validate(request)
        podcast_id = request.path_params['podcast_id']
        podcast = await self.get_object(podcast_id)
        await podcast.update(**podcast_data.dict()).apply()
        return self._response(podcast)

    @db_transaction
    async def delete(self, request):
        podcast_id = int(request.path_params['podcast_id'])
        podcast = await self.get_object(podcast_id)
        await podcast.delete()
        return self._response(data={"id": podcast.id})

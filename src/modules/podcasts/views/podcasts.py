import uuid
from starlette import status

from common.views import BaseHTTPEndpoint
from modules.podcasts.models import Podcast
from modules.podcasts.serializers import (
    PodcastCreateModel,
    PodcastListModel,
    PodcastDetailsModel,
    PodcastUpdateModel,
)


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    db_model = Podcast
    model = PodcastCreateModel
    model_response = PodcastListModel

    async def get(self, request):
        podcasts = await Podcast.query.order_by(Podcast.created_at).gino.all()
        return self._response(podcasts)

    async def post(self, request):
        podcast_data = await self._validate(request)
        pub_id = uuid.uuid4().hex
        podcast = await Podcast.create(name=podcast_data.name, publish_id=pub_id, created_by_id=1)
        return self._response(podcast, status_code=status.HTTP_201_CREATED)

        # TODO: replace to normal podcast creation


class PodcastRUDAPIView(BaseHTTPEndpoint):
    db_model = Podcast
    model = PodcastUpdateModel
    model_response = PodcastDetailsModel

    async def get(self, request):
        podcast_id = request.path_params['podcast_id']
        podcast = await Podcast.get_or_404(podcast_id)
        return self._response(podcast)

    async def delete(self, request):
        podcast_id = int(request.path_params['podcast_id'])
        podcast = await Podcast.get_or_404(podcast_id)
        await podcast.delete()
        return self._response(data={"id": podcast.id})

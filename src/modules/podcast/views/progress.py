from common.views import BaseHTTPEndpoint
from modules.podcast.models import Podcast, Episode
from modules.podcast.schemas import ProgressResponseSchema
from modules.podcast.utils import check_state


class ProgressAPIView(BaseHTTPEndpoint):
    """
    Temp solution (web-socket for poor) to quick access to downloading process
    (statistic is saved in Redis)
    # TODO: Rewrite this to web-socket
    """

    schema_response = ProgressResponseSchema

    async def get(self, request):
        podcast_items = {
            podcast.id: podcast
            for podcast in await Podcast.async_filter(created_by_id=request.user.id)
        }
        episodes = {
            episode.id: episode for episode in await Episode.get_in_progress(request.user.id)
        }
        progress = await check_state(episodes.values())

        for progress_item in progress:
            podcast: Podcast = podcast_items.get(progress_item.pop("podcast_id"))
            episode: Episode = episodes.get(progress_item.pop("episode_id"))
            progress_item["episode"] = {
                "id": episode.id,
                "title": episode.title,
                "image_url": episode.image_url,
                "status": episode.status,
            }
            progress_item["podcast"] = {
                "id": podcast.id,
                "name": podcast.name,
                "image_url": podcast.image_url,
            }

        return self._response(data=progress)

from typing import Any

from starlette.endpoints import WebSocketEndpoint
from starlette.websockets import WebSocket

from common.views import BaseHTTPEndpoint
from modules.auth.backend import LoginRequiredAuthBackend
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
            for podcast in await Podcast.async_filter(self.db_session, owner_id=request.user.id)
        }
        episodes = {
            episode.id: episode
            for episode in await Episode.get_in_progress(self.db_session, request.user.id)
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


class EpisodeInProgressAPIView(BaseHTTPEndpoint):
    """Current downloading progress for requested episode"""

    schema_response = ProgressResponseSchema
    db_model = Episode

    async def get(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        progress_data = {}
        if episode.status in Episode.PROGRESS_STATUSES:
            if progress := await check_state([episode]):
                progress_data = progress[0]

        progress_data["episode"] = episode
        return self._response(progress_data)


class ProgressWS(WebSocketEndpoint):
    auth_backend = LoginRequiredAuthBackend

    async def dispatch(self) -> None:
        self.app = self.scope.get("app")
        async with self.app.session_maker() as session:
            self.db_session = session
            await super().dispatch()
            # TODO: think about auth
            # if self.auth_backend:
            #     backend = self.auth_backend(self.request)
            #     user, session_id = await backend.authenticate()
            #     self.scope["user"] = user
            #     self.request.user_session_id = session_id

    async def on_connect(self, websocket: WebSocket) -> None:
        """Override to handle an incoming websocket connection"""
        # TODO: start sending messages to connected clients
        await websocket.accept()

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        """Override to handle an incoming websocket message"""

    async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
        """Override to handle a disconnecting websocket"""
        # TODO: may be reconnect client
        await websocket.close()

    async def _get_progress_items(self, request):
        podcast_items = {
            podcast.id: podcast
            for podcast in await Podcast.async_filter(self.db_session, owner_id=request.user.id)
        }
        episodes = {
            episode.id: episode
            for episode in await Episode.get_in_progress(self.db_session, request.user.id)
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

        return progress


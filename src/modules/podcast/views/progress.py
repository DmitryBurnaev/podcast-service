import json
from asyncio import sleep
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
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

@dataclass
class WSRequest:
    headers: dict[str, str]
    db_session: AsyncSession


class ProgressWS(WebSocketEndpoint):
    auth_backend = LoginRequiredAuthBackend
    request: WSRequest
    db_session: AsyncSession

    async def dispatch(self) -> None:
        app = self.scope.get("app")
        async with app.session_maker() as session:
            self.db_session = session
            await super().dispatch()

    async def on_connect(self, websocket: WebSocket) -> None:
        """Override to handle an incoming websocket connection"""
        # TODO: start sending messages to connected clients
        await websocket.accept()
        # self.scan_started = True
        # while self.scan_started:
        #     progress = await self._get_progress_items()
        # for i in range(10):
        #     await sleep(1)
        #     await websocket.send_json({"data": {"foo": "bar"}})

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        """Override to handle an incoming websocket message"""
        request_data = json.loads(data)
        # TODO: validate data, disconnect if auth problems
        self.request = WSRequest(headers=request_data.get("headers"), db_session=self.db_session)
        user = await self._auth()
        # TODO: subscribe to redis key's changes
        for i in range(10):
            progress_data = await self._get_progress_items(user.id)
            payload = ProgressResponseSchema(many=True).dump(progress_data)
            await websocket.send_json({"progressData": payload})
            await sleep(2)

    async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
        """Override to handle a disconnecting websocket"""
        # TODO: may be reconnect client
        await websocket.close()

    async def _auth(self):
        backend = self.auth_backend(self.request)
        user, session_id = await backend.authenticate()
        self.scope["user"] = user
        print(user)
        return user

    async def _get_progress_items(self, user_id: int) -> list[dict]:
        episode_id = 441
        episode = await Episode.async_get(self.db_session, id=episode_id)

        import random
        from modules.podcast.utils import episode_process_hook
        from modules.podcast.models import EpisodeStatus
        total_bytes = 1024 * 1024 * 12
        processed_bytes = 1024 * 1024 * random.randint(1, 12)
        episode_process_hook(
            status=EpisodeStatus.DL_EPISODE_DOWNLOADING,
            filename=episode.audio.path,
            total_bytes=total_bytes,
            processed_bytes=processed_bytes,
        )

        podcast_items = {
            podcast.id: podcast
            for podcast in await Podcast.async_filter(self.db_session, owner_id=user_id)
        }
        # episodes = {
        #     episode.id: episode
        #     for episode in await Episode.get_in_progress(self.db_session, user_id)
        # }
        episodes = {episode.id: episode}
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


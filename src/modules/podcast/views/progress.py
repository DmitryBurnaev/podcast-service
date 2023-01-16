import asyncio
import logging
from typing import cast, Iterable

import async_timeout
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from common.redis import RedisClient
from core import settings
from common.views import BaseWSEndpoint
from modules.podcast.models import Podcast, Episode
from modules.podcast.utils import check_state
from modules.podcast.schemas import ProgressResponseSchema, WSProgressRequestSchema

logger = logging.getLogger(__name__)


class ProgressWS(BaseWSEndpoint):
    """Provide updates for episodes progress (storage - Redis)"""

    request_schema = WSProgressRequestSchema

    async def _background_handler(self, websocket: WebSocket):
        await self._send_progress_for_episodes(websocket)
        await self._pubsub(websocket)

    async def _send_progress_for_episodes(self, websocket: WebSocket):
        episode_id = self.request.data.get("episode_id")
        async with self.app.session_maker() as db_session:
            progress_data = await self._get_progress_items(db_session, episode_id)
            progress_items = ProgressResponseSchema(many=True).dump(progress_data)

        await websocket.send_json({"progressItems": progress_items})

    async def _pubsub(self, websocket: WebSocket):
        redis_client = RedisClient()
        pubsub = redis_client.async_pubsub()

        async def reader(channel: aioredis.client.PubSub):
            while True:
                try:
                    async with async_timeout.timeout(1):
                        message = await channel.get_message(ignore_subscribe_messages=True)
                        if message is not None:
                            logger.debug("Redis channel's reader | Message Received: %s", message)
                            if message["data"] == settings.REDIS_PROGRESS_PUBSUB_SIGNAL:
                                await self._send_progress_for_episodes(websocket)

                        await asyncio.sleep(0.01)

                except asyncio.TimeoutError:
                    logger.error("Couldn't read message from redis pubsub channel: timeout")

                if self.background_task.cancelled():
                    logger.debug("Background task was cancelled!")
                    break

        async with pubsub as psub_channel:
            await psub_channel.subscribe(settings.REDIS_PROGRESS_PUBSUB_CH)
            await reader(psub_channel)  # wait for reader to complete
            await psub_channel.unsubscribe(settings.REDIS_PROGRESS_PUBSUB_CH)

        # closing all open connections
        await pubsub.close()

    async def _get_progress_items(
        self, db_session: AsyncSession, episode_id: int | None = None
    ) -> list[dict]:
        podcast_items = {
            podcast.id: podcast
            for podcast in await Podcast.async_filter(db_session, owner_id=self.user.id)
        }
        if episode_id:
            episode = await Episode.async_get(db_session, id=episode_id)
            episodes = {episode.id: episode}
        else:
            episodes = {
                episode.id: episode
                for episode in await Episode.get_in_progress(db_session, self.user.id)
            }

        progress_items = await check_state(cast(Iterable, episodes.values()))

        for progress_item in progress_items:
            podcast: Podcast = podcast_items.get(progress_item.pop("podcast_id"))
            episode: Episode = episodes.get(progress_item.pop("episode_id"))
            progress_item["episode"] = episode
            progress_item["podcast"] = podcast

        return progress_items

import json
from typing import Iterable, Any

import redis
from redis import asyncio as aioredis

from core import settings
from common.utils import get_logger

logger = get_logger(__name__)

JSONT = list[Any] | dict[str, Any] | str


class RedisClient:
    """The class is used to create a redis connection in a single instance."""

    __instance = None
    sync_redis: redis.Redis
    async_redis: aioredis.Redis

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
            cls.async_redis: aioredis.Redis = aioredis.Redis(**settings.REDIS)
            cls.sync_redis: redis.Redis | None = None
        return cls.__instance

    async def set(self, key: str, value: JSONT, ttl: int = 120) -> None:
        await self.async_redis.set(key, json.dumps(value), ttl)

    async def get(self, key: str) -> JSONT:
        return json.loads(await self.async_redis.get(key) or "null")

    async def publish(self, message: str, channel: str = settings.REDIS_PROGRESS_PUBSUB_CH):
        logger.debug("Redis > Publishing message %s to channel %s ", message, channel)
        await self.async_redis.publish(channel, message)

    async def get_many(self, keys: Iterable[str], pkey: str) -> dict:
        """
        Allows to get several values from redis for 1 request
        :param keys: any iterable object with needed keys
        :param pkey: key in each record for grouping by it
        :return: dict with keys (given from stored records by `pkey`)

        """
        stored_items = map(json.loads, [item for item in await self.async_redis.mget(keys) if item])
        try:
            result = {stored_item[pkey]: stored_item for stored_item in stored_items}
        except (TypeError, KeyError) as exc:
            logger.debug("Try to extract redis data: %s", list(stored_items))
            logger.exception("Couldn't extract event data from redis: %s", exc)
            result = {}

        return result

    @staticmethod
    def get_key_by_filename(filename) -> str:
        return filename.partition(".")[0]

    # TODO: rename: sync_get -> get, set -> aset / publish -> apublish ....
    def sync_get(self, key: str) -> JSONT:
        if not (redis_client := self.sync_redis):
            redis_client = redis.Redis(*settings.REDIS_CON)
            self.sync_redis = redis_client

        return json.loads(redis_client.get(key) or "null")

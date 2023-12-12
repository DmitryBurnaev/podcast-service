import json
import logging
from typing import Iterable, Any

import redis
from redis import asyncio as aioredis

from core import settings

logger = logging.getLogger(__name__)
JSONT = list[Any] | dict[str, Any] | str


class RedisClient:
    """The class is used to create a redis connection in a single instance."""

    __instance = None
    __sync_redis: redis.Redis = None
    __async_redis: aioredis.Redis = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    @property
    def sync_redis(self) -> redis.Redis:
        if not (sync_redis := self.__sync_redis):
            sync_redis = redis.Redis(*settings.REDIS_CON)
            self.__sync_redis = sync_redis

        return sync_redis

    @property
    def async_redis(self) -> aioredis.Redis:
        if not (async_redis := self.__async_redis):
            async_redis = aioredis.Redis(**settings.REDIS)
            self.__async_redis = async_redis

        return async_redis

    def get(self, key: str) -> JSONT:
        logger.debug("Redis > Getting value by key %s", key)
        return json.loads(self.sync_redis.get(key) or "null")

    def set(self, key: str, value: JSONT, ttl: int = 120) -> None:
        logger.debug("Redis > Setting value by key %s", key)
        self.sync_redis.set(key, json.dumps(value), ttl)

    def publish(self, channel: str, message: str) -> None:
        logger.debug("Redis > Publishing message %s to channel %s ", message, channel)
        self.sync_redis.publish(channel, message)

    async def async_set(self, key: str, value: JSONT, ttl: int = 120) -> None:
        logger.debug("AsyncRedis > Setting value by key %s", key)
        await self.async_redis.set(key, json.dumps(value), ttl)

    async def async_get(self, key: str) -> JSONT:
        logger.debug("AsyncRedis > Getting value by key %s", key)
        return json.loads(await self.async_redis.get(key) or "null")

    async def async_publish(self, channel: str, message: str) -> None:
        logger.debug("AsyncRedis > Publishing message %s to channel %s ", message, channel)
        await self.async_redis.publish(channel, message)

    def async_pubsub(self, **kwargs) -> aioredis.client.PubSub:
        logger.debug("AsyncRedis > PubSub with kwargs %s", kwargs)
        return self.async_redis.pubsub(**kwargs)

    async def async_get_many(self, keys: Iterable[str], pkey: str) -> dict:
        """
        Allows to get several values from redis for 1 request
        :param keys: any iterable object with needed keys
        :param pkey: key in each record for grouping by it

        :return: dict with keys (given from stored records by `pkey`)

        input from redis: ['{"event_key": "episode-1", "data": {"key": 1}}', ...]
        >>> async def get_items_from_redis():
        ...    return await RedisClient().async_get_many(["episode-1"], pkey="event_key")
        {"episode-1": {"event_key": "episode-1", "data": {"key": 1}}, ...}

        """
        stored_items = [json.loads(item) for item in await self.async_redis.mget(keys) if item]
        # stored_items = (json.loads(item) for item in await self.async_redis.mget(keys) if item)
        try:
            logger.debug("Try to extract redis data: %s", list(stored_items))
            result = {
                stored_item[pkey]: stored_item
                for stored_item in stored_items
                if pkey in stored_item
            }
        except TypeError as exc:
            logger.exception("Couldn't extract event data from redis: %r", exc)
            result = {}

        return result

    @staticmethod
    def get_key_by_filename(filename) -> str:
        return filename.partition(".")[0]

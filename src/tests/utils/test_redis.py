import json
import logging
from unittest.mock import Mock, AsyncMock, patch

import pytest
from redis.client import Redis
from redis import asyncio as aioredis

from common.redis import RedisClient
from tests.helpers import mock_target_class
from tests.mocks import BaseMock

TEST_DATA = {"test": "my-value"}


class MockRedis(BaseMock):
    target_class = Redis

    def __init__(self):
        self.set = Mock()
        self.get = Mock()
        self.publish = Mock()


class MockAIORedis(BaseMock):
    target_class = aioredis.Redis

    class MockedPubSubChannel:
        pass

    def __init__(self):
        self.pubsub_channel = self.MockedPubSubChannel()
        self.set = AsyncMock()
        self.get = AsyncMock()
        self.mget = AsyncMock()
        self.publish = AsyncMock()
        self.mget = AsyncMock()
        self.pubsub = Mock()


@pytest.fixture
def m_redis(monkeypatch) -> MockRedis:
    yield from mock_target_class(MockRedis, monkeypatch)


@pytest.fixture
def m_aioredis(monkeypatch) -> MockAIORedis:
    yield from mock_target_class(MockAIORedis, monkeypatch)


def test_sync_redis__get(m_redis: MockRedis):
    m_redis.get.return_value = json.dumps(TEST_DATA)
    result = RedisClient().get("my-key")
    assert result == TEST_DATA
    m_redis.get.assert_called_with("my-key")


def test_sync_redis__set(m_redis: MockRedis):
    RedisClient().set("my-key", TEST_DATA, ttl=180)
    m_redis.set.assert_called_with("my-key", json.dumps(TEST_DATA), 180)


def test_sync_redis__publish(m_redis: MockRedis):
    RedisClient().publish("test-channel", "test-message")
    m_redis.publish.assert_called_with("test-channel", "test-message")


@pytest.mark.asyncio
async def test_async_redis__get(m_aioredis: MockAIORedis):
    m_aioredis.get.return_value = json.dumps(TEST_DATA)
    result = await RedisClient().async_get("my-key")
    assert result == TEST_DATA
    m_aioredis.get.assert_awaited_with("my-key")


@pytest.mark.asyncio
async def test_async_redis__set(m_aioredis: MockAIORedis):
    await RedisClient().async_set("my-key", TEST_DATA, ttl=180)
    m_aioredis.set.assert_awaited_with("my-key", json.dumps(TEST_DATA), 180)


@pytest.mark.asyncio
async def test_async_redis__publish(m_aioredis: MockAIORedis):
    await RedisClient().async_publish("test-channel", "test-message")
    m_aioredis.publish.assert_awaited_with("test-channel", "test-message")


def test_async_redis__pubsub(m_aioredis: MockAIORedis):
    m_aioredis.pubsub.return_value = m_aioredis.pubsub_channel
    pubsub = RedisClient().async_pubsub(arg_1=123)
    assert pubsub is m_aioredis.pubsub_channel
    m_aioredis.pubsub.assert_called_with(arg_1=123)


@pytest.mark.asyncio
async def test_async_redis__get_many(m_aioredis: MockAIORedis):
    m_aioredis.mget.return_value = [
        json.dumps({"pkey1": "my-key-1", "data": TEST_DATA}),
        json.dumps({"pkey1": "my-key-2", "data": TEST_DATA}),
    ]
    result = await RedisClient().async_get_many(["my-key-1", "my-key-2"], pkey="pkey1")
    assert result == {
        "my-key-1": {"pkey1": "my-key-1", "data": TEST_DATA},
        "my-key-2": {"pkey1": "my-key-2", "data": TEST_DATA},
    }
    m_aioredis.mget.assert_awaited_with(["my-key-1", "my-key-2"])


@pytest.mark.asyncio
async def test_async_redis__get_many__bad_keys_matched(m_aioredis: MockAIORedis):
    m_aioredis.mget.return_value = [
        json.dumps({"pkey1": ["my-key-1"], "data": TEST_DATA}),  # list can be used as key in dict
    ]
    with patch.object(logging.Logger, "exception") as mock_logger:
        result = await RedisClient().async_get_many(["my-key-1", "my-key-2"], pkey="pkey1")

    assert result == {}
    m_aioredis.mget.assert_awaited_with(["my-key-1", "my-key-2"])

    msg, err = mock_logger.call_args_list[0].args
    assert msg == "Couldn't extract event data from redis: %r"
    assert type(err) == TypeError
    assert err.args == ("unhashable type: 'list'",)


def test_sync_redis__get_key():
    assert RedisClient().get_key_by_filename("test-file.mp3") == "test-file"

import asyncio
import json

import async_timeout

import aioredis

from core import settings

STOPWORD = "STOP"
conn_kwargs = dict(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
)


async def pubsub():
    redis = aioredis.Redis(
        **conn_kwargs,
        max_connections=10,
        decode_responses=True
    )
    psub = redis.pubsub()

    async def reader(channel: aioredis.client.PubSub):
        while True:
            try:
                async with async_timeout.timeout(1):
                    message = await channel.get_message(ignore_subscribe_messages=True)
                    if message is not None:
                        print(f"(Reader) Message Received: {message}")
                        if message["data"] == STOPWORD:
                            print("(Reader) STOP")
                            break
                    await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                pass

    await asyncio.sleep(10)
    async with psub as p:
        await p.subscribe("channel:1")
        await reader(p)  # wait for reader to complete
        await p.unsubscribe("channel:1")

    # closing all open connections
    await psub.close()


async def main():
    tsk = asyncio.create_task(pubsub())

    async def publish():
        pub = aioredis.Redis(**settings.REDIS, decode_responses=True)
        while not tsk.done():
            print("while not tsk.done():")
            # wait for clients to subscribe
            # while True:
            #     subs = dict(await pub.pubsub_numsub("channel:1"))
            #     if subs["channel:1"] == 1:
            #         break
            #     await asyncio.sleep(1)
            # publish some messages
            msg = json.dumps({"episodes_ids": 444})
            await pub.publish(settings.REDIS_PROGRESS_PUBSUB_CH, msg)
            await asyncio.sleep(1)

            # for msg in ["one", "two", "three"]:
            #     print(f"(Publisher) Publishing Message: {msg}")
            #     await pub.publish(settings.REDIS_PROGRESS_PUBSUB_CH, msg)
            #     await asyncio.sleep(1)

            # send stop word

        await pub.publish(settings.REDIS_PROGRESS_PUBSUB_CH, STOPWORD)
        await pub.close()

    await publish()


if __name__ == "__main__":
    asyncio.run(main())

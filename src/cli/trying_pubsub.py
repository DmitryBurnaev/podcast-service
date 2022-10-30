import asyncio
import random

import async_timeout

import aioredis

from common.utils import publish_message_to_redis_pubsub
from core import settings, app
from modules.podcast.models import Episode

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


async def update_episode_progress(episode_id: int):
    async with app.get_app().session_maker() as db_session:
        episode = await Episode.async_get(db_session, id=episode_id)

    from modules.podcast.utils import episode_process_hook
    from modules.podcast.models import EpisodeStatus
    total_bytes = 1024 * 1024 * 12
    processed_bytes = 1024 * 1024 * random.randint(1, 12)
    statuses = [
        EpisodeStatus.DL_PENDING,
        EpisodeStatus.DL_EPISODE_DOWNLOADING,
        EpisodeStatus.DL_EPISODE_POSTPROCESSING,
        EpisodeStatus.DL_EPISODE_UPLOADING,
    ]
    episode_process_hook(
        status=statuses[random.randint(0, len(statuses)-1)],
        filename=episode.audio.path,
        total_bytes=total_bytes,
        processed_bytes=processed_bytes,
    )


async def main():
    # tsk = asyncio.create_task(pubsub())
    episode_ids = [432, 414, 124]

    async def publish():
        pub = aioredis.Redis(**settings.REDIS)
        while True:
            print("while True")
            for episode_id in episode_ids:
                await update_episode_progress(episode_id)

            await publish_message_to_redis_pubsub(message=settings.REDIS_PROGRESS_PUBSUB_SIGNAL)
            # wait for clients to subscribe
            # while True:
            #     subs = dict(await pub.pubsub_numsub("channel:1"))
            #     if subs["channel:1"] == 1:
            #         break
            #     await asyncio.sleep(1)
            # publish some messages
            # await pub.publish(settings.REDIS_PROGRESS_PUBSUB_CH, settings.REDIS_PROGRESS_PUBSUB_SIGNAL)
            # await asyncio.sleep(random.randint(1, 5))

            # for msg in ["one", "two", "three"]:
            #     print(f"(Publisher) Publishing Message: {msg}")
            #     await pub.publish(settings.REDIS_PROGRESS_PUBSUB_CH, msg)
            #     await asyncio.sleep(1)

            # send stop word

        await pub.close()

    await publish()


if __name__ == "__main__":
    asyncio.run(main())

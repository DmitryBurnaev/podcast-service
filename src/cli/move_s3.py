import asyncio
import logging
from typing import Iterable

import aioboto3

import tqdm.asyncio

from common.enums import EpisodeStatus
from common.utils import get_logger
from core import settings

# ...S3_CONFIG_FROM
# ...S3_CONFIG_TO
from modules.podcast.models import Episode

DOWNLOAD_DIR = settings.PROJECT_ROOT_DIR / 'media/s3'

logger = get_logger(__name__)


async def progress_as_completed(tasks):
    return [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]


# async def download_object(s3, obj_key: str):
#     await s3.download_file(settings.S3_BUCKET_NAME, obj_key, filename=(DOWNLOAD_DIR / obj_key))
    # with open(DOWNLOAD_DIR / obj_key, 'wb') as file:
    #     await s3.download_fileobj(settings.S3_BUCKET_NAME, obj_key, file)


# async def upload_object(s3, obj_key: str):
#     await s3.upload_file((DOWNLOAD_DIR / obj_key), settings.S3_BUCKET_NAME, obj_key)


async def check_object(s3, obj_key: str, expected_size):
    response = await s3.meta.client.head_object(
        Bucket=settings.S3_BUCKET_NAME, Key=obj_key)

    assert response.get('ContentLength', 0) == expected_size

# async def delete_object(s3, obj_key: str):
#


async def process_file(s3, obj_url: str):
    if not obj_url.startswith(settings.S3_STORAGE_URL):
        logger.info("Skip, %s", obj_url)
        return

    obj_key = obj_url.replace(settings.S3_STORAGE_URL, "")
    await s3.download_file(settings.S3_BUCKET_NAME, obj_key, filename=(DOWNLOAD_DIR / obj_key))
    # TODO: check size for downloaded file
    await s3.upload_file((DOWNLOAD_DIR / obj_key), settings.S3_BUCKET_NAME, obj_key)
    # TODO: check size for uploaded file
    await check_object(s3, obj_key, expected_size=10)  # TODO: get expected size from episode
    # TODO: update episode's URL (with transaction)


async def process_episodes(db_session) -> list[dict]:
    episodes: Iterable[Episode] = await Episode.async_filter(
        db_session, status=EpisodeStatus.PUBLISHED
    )
    return [
        {
            "id": episode.id,
            "url": episode.remote_url,
        }
        for episode in episodes
    ]


async def main():
    print(f" ===== Running moving ===== ")
    session = aioboto3.Session(
        aws_access_key_id=settings.S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_AWS_SECRET_ACCESS_KEY,
        region_name="ru-central1",
    )
    print("session", session)
    # TODO: DB session
    db_session = None
    episode_files = await process_episodes(db_session)
    async with session.resource("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
        # bucket = await s3.Bucket(settings.S3_BUCKET_NAME)
        tasks = [
            process_file(s3, episode_file['url'])
            for episode_file in episode_files
        ]

    # TODO: Limit with max downloads per time
    # [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]
    await progress_as_completed(tasks)

    # objects = []
    # async with session.resource("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
    #     bucket = await s3.Bucket(settings.S3_BUCKET_NAME)
    #     async for s3_object in bucket.objects.all():
    #         print(s3_object)
    #         if not s3_object.key.endswith('/'):
    #             objects.append(s3_object)
    #             break
    #
    # tasks = []
    # async with session.client("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
    #     for obj in objects:
    #         tasks.append(process_file(s3, obj.key))
    #
    # # TODO: Limit with max downloads per time
    # await progress_as_completed(tasks)


if __name__ == "__main__":
    asyncio.run(main())

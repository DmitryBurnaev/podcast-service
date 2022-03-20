import asyncio
import logging
from typing import Iterable, NamedTuple

import aioboto3

import tqdm.asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import EpisodeStatus
from common.utils import get_logger
from core import settings

# ...S3_CONFIG_FROM
# ...S3_CONFIG_TO
from core.settings import config
from modules.podcast.models import Episode
from modules.podcast.utils import get_file_size

# TODO: create folder for downloading files
DOWNLOAD_DIR = settings.PROJECT_ROOT_DIR / 'media/s3'
STORAGE_URL_FROM = config("S3_STORAGE_URL_FROM")
STORAGE_URL_TO = config("S3_STORAGE_URL_TO")


logger = get_logger(__name__)


class EpisodeFileData(NamedTuple):
    id: int
    url: str
    size: int


async def progress_as_completed(tasks):
    return [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]


async def check_object(s3, obj_key: str, expected_size):
    response = await s3.meta.client.head_object(
        Bucket=settings.S3_BUCKET_NAME, Key=obj_key)

    assert response.get('ContentLength', 0) == expected_size


async def get_episode_files(dbs: AsyncSession) -> list[EpisodeFileData]:
    episodes: Iterable[Episode] = await Episode.async_filter(
        dbs, status=EpisodeStatus.PUBLISHED
    )
    return [
        EpisodeFileData(
            id=episode.id,
            url=episode.remote_url,
            size=episode.file_size,
        )
        for episode in episodes
    ]


async def process_file(s3_from, s3_to, episode_file: EpisodeFileData, dbs: AsyncSession):
    if not episode_file.url.startswith(settings.S3_STORAGE_URL):
        logger.info("Skip episode #%i | url %s", episode_file.id, episode_file.url)
        return

    obj_key = episode_file.url.replace(STORAGE_URL_FROM, "")
    local_file_name = DOWNLOAD_DIR / obj_key
    await s3_from.download_file(settings.S3_BUCKET_NAME, obj_key, filename=local_file_name)
    downloaded_size = get_file_size(local_file_name)
    if episode_file.size != downloaded_size:
        logger.error(
            "File %s has incorrect size: %i != %i | episode #%i",
            local_file_name, downloaded_size, episode_file.size, episode_file.id
        )
        return

    # TODO: upload with non public access
    await s3_to.upload_file((DOWNLOAD_DIR / obj_key), settings.S3_BUCKET_NAME, obj_key)
    # TODO: check size for uploaded file
    await check_object(s3_to, obj_key, expected_size=10)  # TODO: get expected size from episode
    # TODO: update episode's URL (with transaction)

    await Episode.async_update(
        dbs,
        filter_kwargs={'id': episode_file.id},
        update_data={'public_url': episode_file.url.replace(STORAGE_URL_FROM, STORAGE_URL_TO)}
    )






async def main():
    print(f" ===== Running moving ===== ")
    session = aioboto3.Session(
        aws_access_key_id=settings.S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_AWS_SECRET_ACCESS_KEY,
        region_name="ru-central1",
    )
    print("session", session)
    # TODO: DB session
    dbs = None
    episode_files = await get_episode_files(dbs)
    async with session.resource("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
        # bucket = await s3.Bucket(settings.S3_BUCKET_NAME)
        tasks = [
            process_file(s3, episode_file)
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

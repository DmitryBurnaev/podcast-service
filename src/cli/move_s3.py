import os
import asyncio
from typing import Iterable, NamedTuple

import aioboto3
import tqdm.asyncio
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core import settings
from common.utils import get_logger
from common.enums import EpisodeStatus
from modules.podcast.models import Episode
from modules.podcast.utils import get_file_size

DOWNLOAD_DIR = settings.PROJECT_ROOT_DIR / '.misc/s3'

# S3 storage "FROM"
S3_STORAGE_URL_FROM = settings.config("S3_STORAGE_URL_FROM")
S3_AWS_ACCESS_KEY_ID_FROM = settings.config("S3_AWS_ACCESS_KEY_ID_FROM")
S3_AWS_SECRET_ACCESS_KEY_FROM = settings.config("S3_AWS_SECRET_ACCESS_KEY_FROM")
S3_BUCKET_FROM = settings.config("S3_BUCKET_NAME_FROM")
S3_REGION_FROM = settings.config("S3_REGION_NAME_FROM")

# S3 storage "TO"
S3_STORAGE_URL_TO = settings.config("S3_STORAGE_URL_TO")
S3_AWS_ACCESS_KEY_ID_TO = settings.config("S3_AWS_ACCESS_KEY_ID_TO")
S3_AWS_SECRET_ACCESS_KEY_TO = settings.config("S3_AWS_SECRET_ACCESS_KEY_TO")
S3_BUCKET_TO = settings.config("S3_BUCKET_NAME_TO")
S3_REGION_TO = settings.config("S3_REGION_TO")


logger = get_logger(__name__)
os.makedirs(DOWNLOAD_DIR)


class EpisodeFileData(NamedTuple):
    id: int
    url: str
    size: int
    content_type: str


processed_files: list[EpisodeFileData] = []


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
            content_type=episode.content_type,
        )
        for episode in episodes
    ]


async def process_episode(s3_from, s3_to, episode_file: EpisodeFileData, dbs: AsyncSession):

    if not episode_file.url.startswith(S3_STORAGE_URL_FROM):
        logger.info("Skip episode #%i | url %s", episode_file.id, episode_file.url)
        return

    obj_key = episode_file.url.replace(S3_STORAGE_URL_FROM, "")
    dirname = DOWNLOAD_DIR / os.path.dirname(obj_key)
    if not os.path.isdir(dirname):
        os.makedirs(dirname)

    local_file_name = DOWNLOAD_DIR / obj_key
    await s3_from.download_file(s3_from.bucket, obj_key, filename=local_file_name)
    downloaded_size = get_file_size(local_file_name)
    if episode_file.size != downloaded_size:
        logger.error(
            "File %s has incorrect size: %i != %i | episode #%i",
            local_file_name, downloaded_size, episode_file.size, episode_file.id
        )
        return

    # TODO: for tests only
    if len(processed_files) > 1:
        raise RuntimeError('MAX processed_files')

    await s3_to.upload_file(
        local_file_name,
        s3_to.bucket,
        obj_key,
        # TODO: check "ACL": "public-read" ?
        ExtraArgs={"ContentType": episode_file.content_type},
    )
    await check_object(s3_to, obj_key, expected_size=episode_file.size)
    try:
        await Episode.async_update(
            dbs,
            filter_kwargs={'id': episode_file.id},
            update_data={
                'public_url': episode_file.url.replace(S3_STORAGE_URL_FROM, "")
            }
        )
    except Exception as err:
        logger.exception(
            "Couldn't update episode #%i | %s | err: %s",
            episode_file.id, obj_key, err
        )
        await dbs.rollback()
    else:
        await dbs.commit()
        processed_files.append(episode_file)


async def main():
    logger.info(f" ===== Running moving ===== ")
    session_s3_from = aioboto3.Session(
        aws_access_key_id=S3_AWS_SECRET_ACCESS_KEY_FROM,
        aws_secret_access_key=S3_AWS_ACCESS_KEY_ID_FROM,
        region_name=S3_REGION_FROM,
    )
    session_s3_to = aioboto3.Session(
        aws_access_key_id=S3_AWS_SECRET_ACCESS_KEY_TO,
        aws_secret_access_key=S3_AWS_ACCESS_KEY_ID_TO,
        region_name=S3_REGION_TO,
    )
    db_engine = create_async_engine(settings.DATABASE_DSN, echo=settings.DB_ECHO)
    session_maker = sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as db_session:
        episode_files = await get_episode_files(db_session)
        async with session_s3_from.resource("s3", endpoint_url=S3_STORAGE_URL_FROM) as s3_from:
            async with session_s3_to.resource("s3", endpoint_url=S3_STORAGE_URL_TO) as s3_to:
                s3_from.bucket = S3_BUCKET_FROM
                s3_to.bucket = S3_BUCKET_TO
                tasks = [
                    process_episode(s3_from, s3_to, episode_file, db_session)
                    for episode_file in episode_files
                ]
                # TODO: Limit with max downloads per time
                # [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]
                await progress_as_completed(tasks)


if __name__ == "__main__":
    asyncio.run(main())

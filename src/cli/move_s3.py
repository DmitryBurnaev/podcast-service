import logging.config
import mimetypes
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
LOG_FILENAME = settings.PROJECT_ROOT_DIR / '.misc/logs/moving.log'

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
S3_REGION_TO = settings.config("S3_REGION_NAME_TO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%d.%m.%Y %H:%M:%S",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "formatter": "standard",
            "filename": LOG_FILENAME
        }
    },
    "loggers": {
        "move_s3": {"handlers": ["file"], "level": "DEBUG", "propagate": False},
    },
}
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILENAME), exist_ok=True)

logging.config.dictConfig(LOGGING)
logger = logging.getLogger("move_s3")


class EpisodeFileData(NamedTuple):
    id: int
    url: str
    size: int = None
    image_url: str = None
    content_type: str = None


processed_files: list[EpisodeFileData] = []


async def progress_as_completed(tasks):
    return [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]


def check_size(file_name: str, actual_size: int, expected_size: int = None):
    if expected_size:
        if expected_size != actual_size:
            raise ValueError(
                f"File {file_name} has incorrect size: "
                f"{file_name} != {expected_size}"
            )
    elif actual_size < 1:
        raise ValueError(f"File {file_name} has null-like size: {actual_size}")


async def check_object(s3, obj_key: str, expected_size):
    logger.debug('Checking KEY %s | size %s', obj_key, expected_size)
    response = await s3.head_object(Bucket=s3.bucket, Key=obj_key)
    check_size(
        obj_key,
        actual_size=response.get('ContentLength', 0),
        expected_size=expected_size
    )


async def get_episode_files(dbs: AsyncSession) -> list[EpisodeFileData]:
    episodes: Iterable[Episode] = await Episode.async_filter(
        dbs, status=EpisodeStatus.PUBLISHED
    )
    # TODO: remove limitation after testing
    return [
        EpisodeFileData(
            id=episode.id,
            url=episode.remote_url,
            size=episode.file_size,
            image_url=episode.image_url,
            content_type=episode.content_type,
        )
        for episode in episodes
    ][:7]


async def move_file(s3_from, s3_to, episode_file: EpisodeFileData) -> str:
    if not episode_file.url.startswith(S3_STORAGE_URL_FROM):
        logger.info('Episode %s | Skip %s', episode_file.id, episode_file.url)
        return episode_file.url

    logger.debug('Episode %s | Moving %s', episode_file.id, episode_file.url)
    obj_key = '/'.join(episode_file.url.replace(S3_STORAGE_URL_FROM, '').rsplit('/')[1:])
    dirname = DOWNLOAD_DIR / os.path.dirname(obj_key)
    os.makedirs(dirname, exist_ok=True)

    local_file_name = DOWNLOAD_DIR / obj_key
    logger.debug('Episode %s | downloading %s', episode_file.id, episode_file.url)
    await s3_from.download_file(
        Bucket=s3_from.bucket,
        Key=obj_key,
        Filename=local_file_name
    )
    downloaded_size = get_file_size(local_file_name)
    check_size(
        local_file_name,
        actual_size=downloaded_size,
        expected_size=episode_file.size,
    )

    if not (content_type := episode_file.content_type):
        content_type, _ = mimetypes.guess_type(local_file_name)

    logger.debug('Episode %s | uploading %s', episode_file.id, episode_file.url)
    await s3_to.upload_file(
        Filename=local_file_name,
        Bucket=s3_to.bucket,
        Key=obj_key,
        ExtraArgs={"ContentType": content_type},
    )
    await check_object(s3_to, obj_key, expected_size=episode_file.size)
    logger.debug('Episode %s | moving done %s', episode_file.id, episode_file.url)
    return obj_key


async def process_episode(s3_from, s3_to, episode_file: EpisodeFileData, dbs: AsyncSession):
    if not (
        episode_file.url.startswith(S3_STORAGE_URL_FROM) or
        episode_file.image_url.startswith(S3_STORAGE_URL_FROM)
    ):
        logger.info(
            "Episode %s | Skip | url %s | image url %s",
            episode_file.id, episode_file.url, episode_file.image_url,
        )
        return

    logger.info(
        "Episode %s | START PROCESSING | url %s | image url %s ",
        episode_file.id, episode_file.url, episode_file.image_url,
    )
    try:
        audio_obj_key = await move_file(s3_from, s3_to, episode_file)
        image_obj_key = await move_file(
            s3_from, s3_to,
            episode_file=EpisodeFileData(id=episode_file.id, url=episode_file.image_url)
        )
    except ValueError as e:
        logger.error("Couldn't download file: %s | episode %s", e, episode_file.id)
        return

    try:
        await Episode.async_update(
            dbs,
            filter_kwargs={'id': episode_file.id},
            update_data={
                'remote_url': audio_obj_key,
                'image_url': image_obj_key,
            }
        )
    except Exception as err:
        logger.exception(
            "Episode %s | Couldn't update %s | %s | err: %s",
            episode_file.id, audio_obj_key, image_obj_key, err
        )
        await dbs.rollback()
    else:
        await dbs.commit()
        logger.info(
            "Episode %s | PROCESSED | url %s | image url %s ",
            episode_file.id,  audio_obj_key, image_obj_key,
        )


async def main():
    logger.info(f" ===== Running moving ===== ")
    session_s3_from = aioboto3.Session(
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID_FROM,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY_FROM,
        region_name=S3_REGION_FROM,
    )
    session_s3_to = aioboto3.Session(
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID_TO,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY_TO,
        region_name=S3_REGION_TO,
    )
    db_engine = create_async_engine(settings.DATABASE_DSN, echo=settings.DB_ECHO)
    session_maker = sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as db_session:
        episode_files = await get_episode_files(db_session)
        async with session_s3_from.client("s3", endpoint_url=S3_STORAGE_URL_FROM) as s3_from:
            async with session_s3_to.client("s3", endpoint_url=S3_STORAGE_URL_TO) as s3_to:
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

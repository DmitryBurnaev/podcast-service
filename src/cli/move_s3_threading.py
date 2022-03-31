import concurrent.futures
import logging.config
import mimetypes
import os
import asyncio
from typing import Iterable, NamedTuple

import boto3
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core import settings
from common.enums import EpisodeStatus
from modules.podcast.models import Episode
from modules.podcast.utils import get_file_size

DOWNLOAD_DIR = settings.PROJECT_ROOT_DIR / '.misc/s3'
LOG_FILENAME = settings.PROJECT_ROOT_DIR / '.misc/logs/moving.log'
MAX_CONCUR_REQ = 10

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
            "format": "%(asctime)s | %(threadName)s | %(levelname)s | %(message)s",
            "datefmt": "%d.%m.%Y %H:%M:%S",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "formatter": "standard",
            "filename": LOG_FILENAME
        },
        "console": {"class": "logging.StreamHandler", "formatter": "standard", "level": "INFO"}
    },
    "loggers": {
        "move_s3": {"handlers": ["file", "console"], "level": "DEBUG", "propagate": False},
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


class EpisodeUploadData(NamedTuple):
    episode_id: int
    audio_key: str
    image_key: str

    def __str__(self):
        return f"ep #{self.episode_id} | audio: {self.audio_key} | image: {self.audio_key}"


class SkipError(Exception):
    def __init__(self, skip_result: EpisodeUploadData):
        self.skip_result = skip_result


def check_size(file_name: str, actual_size: int, expected_size: int = None):
    if expected_size:
        if expected_size != actual_size:
            raise ValueError(
                f"File {file_name} has incorrect size: "
                f"{file_name} != {expected_size}"
            )
    elif actual_size < 1:
        raise ValueError(f"File {file_name} has null-like size: {actual_size}")


def check_object(s3, bucket: str, obj_key: str, expected_size):
    logger.debug('Checking KEY %s | size %s', obj_key, expected_size)
    response = s3.head_object(Bucket=bucket, Key=obj_key)
    check_size(
        obj_key,
        actual_size=response.get('ContentLength', 0),
        expected_size=expected_size
    )


async def get_episode_files(dbs: AsyncSession) -> list[EpisodeFileData]:
    episodes: Iterable[Episode] = await Episode.async_filter(
        dbs, status=EpisodeStatus.PUBLISHED
    )
    # TODO: remove limits after testing
    return [
        EpisodeFileData(
            id=episode.id,
            url=episode.remote_url,
            size=episode.file_size,
            image_url=episode.image_url,
            content_type=episode.content_type,
        )
        for episode in episodes
    ][:5]


async def update_episode(dbs: AsyncSession, upload_result: EpisodeUploadData):
    try:
        await Episode.async_update(
            dbs,
            filter_kwargs={'id': upload_result.episode_id},
            update_data={
                'remote_url': upload_result.audio_key,
                'image_url': upload_result.image_key,
            }
        )

    except Exception as err:
        logger.exception(
            "[episode %s] Couldn't update | %s | err: %s",
            upload_result.episode_id, upload_result, err
        )
        await dbs.rollback()
    else:
        await dbs.commit()
        logger.info("[episode %s] PROCESSED | %s", upload_result.episode_id, upload_result)


class S3Moving:

    def __init__(self):
        session_s3_from = boto3.session.Session(
            aws_access_key_id=S3_AWS_ACCESS_KEY_ID_FROM,
            aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY_FROM,
            region_name=S3_REGION_FROM,
        )
        session_s3_to = boto3.session.Session(
            aws_access_key_id=S3_AWS_ACCESS_KEY_ID_TO,
            aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY_TO,
            region_name=S3_REGION_TO,
        )
        db_engine = create_async_engine(settings.DATABASE_DSN, echo=settings.DB_ECHO)
        self.session_maker = sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
        self.s3_from = session_s3_from.client(service_name="s3", endpoint_url=S3_STORAGE_URL_FROM)
        self.s3_to = session_s3_to.client(service_name="s3", endpoint_url=S3_STORAGE_URL_TO)

    async def run(self):
        async with self.session_maker() as db_session:
            episode_files = await get_episode_files(db_session)
            episodes_count = len(episode_files)
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCUR_REQ) as executor:
                futures = {
                    executor.submit(self._move_episode_files, episode_file): episode_file
                    for episode_file in episode_files
                }
                logger.info(f"==== Moving [{episodes_count}] episodes ====")
                for ind, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    episode_file = futures[future]
                    logger.info(
                        '[episode %i] | START (%i from %i) |', episode_file.id, ind, episodes_count
                    )
                    try:
                        upload_result = future.result()
                    except SkipError as err:
                        upload_result = err.skip_result
                        logger.info('[episode %i] | SKIP | %s', episode_file.id, upload_result)
                    except Exception as err:
                        logger.exception(
                            "[episode %i] | ERROR | Couldn't move file: %r | err %s",
                            episode_file.id, episode_file, err
                        )
                    else:
                        await update_episode(db_session, upload_result)
                        logger.info(
                            '[episode %i] | DONE (%i / %i) | %s', episode_file.id, ind,
                            episodes_count, upload_result
                        )

    def _move_episode_files(self, episode_file: EpisodeFileData) -> EpisodeUploadData:
        if not (
            episode_file.url.startswith(S3_STORAGE_URL_FROM) or
            episode_file.image_url.startswith(S3_STORAGE_URL_FROM)
        ):
            logger.debug(
                "[episode %s] Skip | url %s | image url %s",
                episode_file.id, episode_file.url, episode_file.image_url,
            )
            raise SkipError

        logger.info(
            "[episode %s] START MOVING | url %s | image url %s ",
            episode_file.id, episode_file.url, episode_file.image_url,
        )
        audio_obj_key = self._move_file(episode_file)
        image_obj_key = self._move_file(
            episode_file=EpisodeFileData(id=episode_file.id, url=episode_file.image_url)
        )
        return EpisodeUploadData(
            episode_id=episode_file.id,
            audio_key=audio_obj_key,
            image_key=image_obj_key
        )

    def _move_file(self, episode_file: EpisodeFileData) -> str:
        if not episode_file.url.startswith(S3_STORAGE_URL_FROM):
            logger.info('[episode %s] SKIP %s', episode_file.id, episode_file.url)
            return episode_file.url

        logger.debug('[episode %s] moving %s', episode_file.id, episode_file.url)
        obj_key = '/'.join(episode_file.url.replace(S3_STORAGE_URL_FROM, '').rsplit('/')[1:])
        dirname = DOWNLOAD_DIR / os.path.dirname(obj_key)
        os.makedirs(dirname, exist_ok=True)

        local_file_name = DOWNLOAD_DIR / obj_key
        logger.debug('[episode %s] downloading %s', episode_file.id, episode_file.url)
        self.s3_from.download_file(
            Bucket=S3_BUCKET_FROM,
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

        logger.debug('[episode %s] uploading %s', episode_file.id, episode_file.url)
        self.s3_to.upload_file(
            Filename=local_file_name,
            Bucket=S3_BUCKET_TO,
            Key=obj_key,
            ExtraArgs={"ContentType": content_type},
        )
        check_object(
            self.s3_to,
            bucket=S3_BUCKET_TO,
            obj_key=obj_key,
            expected_size=episode_file.size
        )
        logger.debug('[episode %s] moving done %s', episode_file.id, episode_file.url)
        return obj_key


if __name__ == "__main__":
    asyncio.run(S3Moving().run())

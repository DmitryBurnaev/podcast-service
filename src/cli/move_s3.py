import asyncio
import logging

import aioboto3

import tqdm.asyncio
from common.utils import get_logger
from core import settings

# ...S3_CONFIG_FROM
# ...S3_CONFIG_TO


logger = get_logger(__name__)


async def progress_as_completed(tasks):
    return [await task for task in tqdm.asyncio.tqdm.as_completed(tasks)]


async def main():
    print(f" ===== Running moving ===== ")
    session = aioboto3.Session(
        aws_access_key_id=settings.S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_AWS_SECRET_ACCESS_KEY,
        region_name="ru-central1",
    )
    print("session", session)

    objects = []
    async with session.resource("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
        bucket = await s3.Bucket(settings.S3_BUCKET_NAME)
        async for s3_object in bucket.objects.all():
            print(s3_object)
            if not s3_object.key.endswith('/'):
                objects.append(s3_object)
                break

    tasks = []
    async with session.client("s3", endpoint_url=settings.S3_STORAGE_URL) as s3:
        for obj in objects:
            with open(settings.PROJECT_ROOT_DIR / 'media/s3' / obj.key, 'wb') as file:
                tasks.append(
                    s3.download_fileobj(settings.S3_BUCKET_NAME, obj.key, file)
                )
                # await s3.download_fileobj(settings.S3_BUCKET_NAME, obj.key, file)
                # await s3.upload_fileobj(spfp, bucket, blob_s3_key)

    # TODO: Limit with max downloads per time
    await progress_as_completed(tasks)


if __name__ == "__main__":
    asyncio.run(main())

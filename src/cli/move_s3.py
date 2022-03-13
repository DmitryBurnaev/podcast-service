import asyncio

import aioboto3

from core import settings


async def main():
    print(f" ===== Running moving ===== ")
    session = aioboto3.Session(
        aws_access_key_id=settings.S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_AWS_SECRET_ACCESS_KEY,
        region_name="ru-central1",
    )
    async with session.resource("s3") as s3:
        bucket = await s3.Bucket(settings.S3_BUCKET_NAME)
        async for s3_object in bucket.objects.all():
            print(s3_object)


if __name__ == "__main__":
    asyncio.run(main())

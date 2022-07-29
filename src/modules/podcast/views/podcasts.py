import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select, func
from starlette import status
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from core import settings
from common.enums import FileType
from common.utils import get_logger
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.exceptions import MaxAttemptsReached, InvalidParameterError
from modules.media.models import File
from modules.podcast.models import Podcast, Episode
from modules.podcast.schemas import (
    PodcastCreateUpdateSchema,
    PodcastDetailsSchema,
    PodcastUploadImageResponseSchema,
)
from modules.podcast.tasks.rss import GenerateRSSTask
from modules.podcast.utils import get_file_size, save_uploaded_file

logger = get_logger(__name__)


class PodcastListCreateAPIView(BaseHTTPEndpoint):
    """List and Create API for podcasts"""

    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        func_count = func.count(Episode.id).label("episodes_count")
        stmt = (
            select([Podcast, func_count])
            .outerjoin(Episode, Episode.podcast_id == Podcast.id)
            .filter(Podcast.owner_id == request.user.id)
            .group_by(
                Podcast.id,
            )
            .order_by(Podcast.id)
        )
        podcasts = await request.db_session.execute(stmt)
        podcast_list = []
        for podcast, episodes_count in podcasts.all():
            podcast.episodes_count = episodes_count
            podcast_list.append(podcast)

        return self._response(podcast_list)

    async def post(self, request):
        cleaned_data = await self._validate(request)
        podcast = await Podcast.async_create(
            db_session=request.db_session,
            name=cleaned_data["name"],
            publish_id=Podcast.generate_publish_id(),
            description=cleaned_data["description"],
            owner_id=request.user.id,
        )
        return self._response(podcast, status_code=status.HTTP_201_CREATED)


class PodcastRUDAPIView(BaseHTTPEndpoint):
    """Retrieve, Update, Delete API for podcasts"""

    db_model = Podcast
    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        podcast = await self._get_object(request)
        return self._response(podcast)

    async def patch(self, request):
        cleaned_data = await self._validate(request, partial_=True)
        podcast = await self._get_object(request)
        await podcast.update(self.db_session, **cleaned_data)
        return self._response(podcast)

    async def delete(self, request):
        podcast = await self._get_object(request)
        await self._delete_episodes(podcast)
        if podcast.rss_id:
            await podcast.rss.delete(self.db_session, remote_path=settings.S3_BUCKET_RSS_PATH)

        if podcast.image_id:
            await podcast.image.delete(
                self.db_session, remote_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH
            )

        await podcast.delete(self.db_session)
        return self._response()

    async def _get_object(self, request: Request, **_) -> Podcast:
        podcast_id = int(request.path_params["podcast_id"])
        return await super()._get_object(podcast_id)

    async def _delete_episodes(self, podcast: Podcast):
        episodes = await Episode.async_filter(self.db_session, podcast_id=podcast.id)
        del_actions = [episode.delete(self.db_session, db_flush=False) for episode in episodes]
        await asyncio.gather(*del_actions)


class PodcastUploadImageAPIView(BaseHTTPEndpoint):
    """Upload image as podcast's cover"""

    db_model = Podcast
    schema_response = PodcastUploadImageResponseSchema

    async def post(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast: Podcast = await self._get_object(podcast_id)
        logger.info("Uploading cover for podcast %s", podcast)
        cleaned_data = await self._validate(request)
        # TODO: ValueError
        tmp_path = await save_uploaded_file(
            uploaded_file=cleaned_data["image"],
            prefix=f"podcast_cover_{uuid.uuid4().hex}",
            max_file_size=settings.MAX_UPLOAD_IMAGE_FILESIZE,
            tmp_path=settings.TMP_IMAGE_PATH,
        )

        image_remote_path = await self._upload_cover(podcast, tmp_path)
        image_data = {
            "path": image_remote_path,
            "size": get_file_size(tmp_path),
            "available": True,
        }
        if image_file := podcast.image:
            old_image_name = image_file.name
            await image_file.update(self.db_session, **image_data)
            await StorageS3().delete_files_async(
                [old_image_name], remote_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH
            )
        else:
            image_file = await File.create(
                db_session=request.db_session,
                file_type=FileType.IMAGE,
                owner_id=request.user.id,
                **image_data,
            )
            await podcast.update(self.db_session, image_id=image_file.id)
            await self.db_session.refresh(podcast)

        return self._response(podcast)

    async def _validate(self, request, **_) -> dict:
        form = await request.form()
        if not (image := form.get("image")):
            raise InvalidParameterError(details="Image is required field")

        return {"image": image}

    @staticmethod
    async def _upload_cover(podcast: Podcast, tmp_path: Path) -> str:
        logger.info("Uploading cover to S3: podcast %s", podcast)
        storage = StorageS3()
        attempt = settings.MAX_UPLOAD_ATTEMPT + 1
        while attempt := (attempt - 1):
            try:
                remote_path = await run_in_threadpool(
                    storage.upload_file,
                    src_path=str(tmp_path),
                    dst_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH,
                    filename=podcast.generate_image_name(),
                )
            except Exception as err:
                logger.exception(
                    "Couldn't upload image to S3. podcast %s | err: %s", podcast.id, err
                )
                await asyncio.sleep(settings.RETRY_UPLOAD_TIMEOUT)
            else:
                return remote_path

        raise MaxAttemptsReached(f"Couldn't upload cover for podcast {podcast.id}")


class PodcastGenerateRSSAPIView(BaseHTTPEndpoint):
    """Allows starting RSS generation task"""

    db_model = Podcast

    async def put(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        await self._run_task(GenerateRSSTask, podcast.id)
        return self._response(status_code=status.HTTP_202_ACCEPTED)

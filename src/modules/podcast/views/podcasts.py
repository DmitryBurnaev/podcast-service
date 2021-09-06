from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select, func
from starlette import status
from starlette.requests import Request

from core import settings
from common.utils import get_logger
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.exceptions import MaxAttemptsReached
from modules.podcast.models import Podcast, Episode
from modules.podcast.schemas import PodcastCreateUpdateSchema, PodcastDetailsSchema, PodcastUploadImageResponseSchema
from modules.podcast.tasks.rss import GenerateRSSTask
from modules.youtube.utils import ffmpeg_preparation

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
            .filter(Podcast.created_by_id == request.user.id)
            .group_by(Podcast.id)
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
            created_by_id=request.user.id,
        )
        return self._response(podcast, status_code=status.HTTP_201_CREATED)


class PodcastRUDAPIView(BaseHTTPEndpoint):
    """Retrieve, Update, Delete API for podcasts"""

    db_model = Podcast
    schema_request = PodcastCreateUpdateSchema
    schema_response = PodcastDetailsSchema

    async def get(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        return self._response(podcast)

    async def patch(self, request):
        cleaned_data = await self._validate(request, partial_=True)
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        await podcast.update(self.db_session, **cleaned_data)
        return self._response(podcast)

    async def delete(self, request):
        podcast_id = int(request.path_params["podcast_id"])
        podcast = await self._get_object(podcast_id)
        episodes = await Episode.async_filter(self.db_session, podcast_id=podcast_id)

        await Episode.async_delete(self.db_session, {"podcast_id": podcast_id})
        await podcast.delete(self.db_session)
        await self._delete_files(podcast, episodes)
        return self._response()

    async def _delete_files(self, podcast: Podcast, episodes: Iterable[Episode]):
        podcast_file_names = {
            episode.file_name for episode in episodes if episode.status == Episode.Status.PUBLISHED
        }
        same_file_episodes = await Episode.async_filter(
            self.db_session,
            podcast_id__ne=podcast.id,
            file_name__in=podcast_file_names,
            status=Episode.Status.PUBLISHED,
        )
        exist_file_names = {episode.file_name for episode in same_file_episodes or []}

        files_to_remove = podcast_file_names - exist_file_names
        files_to_skip = exist_file_names & podcast_file_names
        if files_to_skip:
            logger.warning(
                "There are another episodes with files %s. Skip this files removing.",
                files_to_skip,
            )

        storage = StorageS3()
        await storage.delete_files_async(
            [f"{podcast.publish_id}.xml"], remote_path=settings.S3_BUCKET_RSS_PATH
        )
        if files_to_remove:
            await storage.delete_files_async(list(files_to_remove))


class PodcastUploadImageAPIView(BaseHTTPEndpoint):
    """Upload image as podcast's cover"""

    db_model = Podcast
    schema_response = PodcastUploadImageResponseSchema

    def post(self, request: Request):
        podcast_id = request.path_params["podcast_id"]
        podcast: Podcast = await self._get_object(podcast_id)
        logger.info("Uploading cover for podcast %s", podcast)
        tmp_path = await self._save_uploaded_image(request)
        tmp_path = self._crop_image(tmp_path)

        podcast.image_url = await self._upload_cover(podcast, tmp_path)
        await podcast.update(self.db_session, image_url=podcast.image_url)
        return podcast

    @staticmethod
    async def _save_uploaded_image(request: Request) -> Path:
        # TODO: implement uploading image saving here
        ...

    @staticmethod
    def _crop_image(tmp_path: Path) -> Optional[Path]:
        ffmpeg_preparation(src_path=tmp_path, ffmpeg_params=["-vf", "scale=400:400"])
        return tmp_path

    @staticmethod
    async def _upload_cover(podcast: Podcast, tmp_path: Path):
        storage = StorageS3()
        attempt = settings.MAX_UPLOAD_ATTEMPT
        while attempt := (attempt - 1):
            if result_url := storage.upload_file(
                src_path=str(tmp_path),
                dst_path=settings.S3_BUCKET_PODCAST_IMAGES_PATH,
                filename=podcast.generate_image_name(),
            ):
                return result_url

        raise MaxAttemptsReached(f"Couldn't upload cover for podcast {podcast}")


class PodcastGenerateRSSAPIView(BaseHTTPEndpoint):
    """Allows to start RSS generation task"""

    db_model = Podcast

    async def put(self, request):
        podcast_id = request.path_params["podcast_id"]
        podcast = await self._get_object(podcast_id)
        await self._run_task(GenerateRSSTask, podcast.id)
        return self._response(status_code=status.HTTP_204_NO_CONTENT)

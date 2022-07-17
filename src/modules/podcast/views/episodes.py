import os.path
import uuid
from pathlib import Path

from sqlalchemy import exists
from starlette import status
from starlette.datastructures import UploadFile

from common.enums import FileType, SourceType
from common.utils import get_logger, cut_string
from common.views import BaseHTTPEndpoint
from common.exceptions import MethodNotAllowedError, InvalidParameterError
from core import settings
from modules.media.models import File
from modules.podcast import tasks
from modules.podcast.episodes import EpisodeCreator
from modules.podcast.models import Episode, Podcast
from modules.podcast.schemas import (
    EpisodeCreateSchema,
    EpisodeUpdateSchema,
    EpisodeDetailsSchema,
    EpisodeListRequestSchema,
    EpisodeListResponseSchema,
    EpisodeListSchema,
    EpisodeUploadedSchema,
)
from modules.podcast.utils import save_uploaded_file
from modules.providers.utils import audio_metadata
from tests.helpers import get_source_id

logger = get_logger(__name__)


class EpisodeListCreateAPIView(BaseHTTPEndpoint):
    """List and Create (based on `EpisodeCreator` logic) API for episodes"""

    @property
    def schema_request(self):
        schema_map = {"get": EpisodeListRequestSchema, "post": EpisodeCreateSchema}
        return schema_map.get(self.request.method.lower())

    @property
    def schema_response(self):
        schema_map = {"get": EpisodeListResponseSchema, "post": EpisodeListSchema}
        return schema_map.get(self.request.method.lower())

    async def get(self, request):
        filter_kwargs = {"owner_id": request.user.id}
        cleaned_data = await self._validate(request, location="query")
        limit, offset = cleaned_data["limit"], cleaned_data["offset"]
        if podcast_id := request.path_params.get("podcast_id"):
            filter_kwargs["podcast_id"] = podcast_id
        if search := cleaned_data.get("q"):
            filter_kwargs["title__icontains"] = search
        if episode_status := cleaned_data.get("status"):
            filter_kwargs["status"] = episode_status

        episodes = await Episode.async_filter(
            self.db_session, limit=limit, offset=offset, **filter_kwargs
        )
        query = Episode.prepare_query(offset=(limit + offset), **filter_kwargs)
        (has_next_episodes,) = next(await self.db_session.execute(exists(query).select()))
        return self._response({"has_next": has_next_episodes, "items": episodes})

    async def post(self, request):
        if not (podcast_id := request.path_params.get("podcast_id")):
            raise MethodNotAllowedError("Couldn't create episode without provided podcast_id")

        podcast = await self._get_object(podcast_id, db_model=Podcast)
        cleaned_data = await self._validate(request)
        episode_creator = EpisodeCreator(
            self.db_session,
            podcast_id=podcast_id,
            source_url=cleaned_data["source_url"],
            user_id=request.user.id,
        )
        episode = await episode_creator.create()
        if podcast.download_automatically:
            await episode.update(self.db_session, status=Episode.Status.DOWNLOADING)
            await self._run_task(tasks.DownloadEpisodeTask, episode_id=episode.id)

        await self._run_task(tasks.DownloadEpisodeImageTask, episode_id=episode.id)
        return self._response(episode, status_code=status.HTTP_201_CREATED)


class UploadedEpisodesAPIView(BaseHTTPEndpoint):
    schema_request = EpisodeUploadedSchema
    schema_response = EpisodeListSchema
    db_model = Podcast

    async def post(self, request):
        podcast: Podcast = await self._get_object(request.path_params["podcast_id"])
        logger.info("Creating episode for uploaded file for podcast %s", podcast)

        cleaned_data = await self._validate(request)
        episode = await self._create_episode(podcast_id=podcast.id, cleaned_data=cleaned_data)
        if podcast.download_automatically:
            await self._run_task(tasks.UploadedEpisodeTask, episode_id=episode.id)

        return self._response(episode, status_code=status.HTTP_201_CREATED)

    async def _create_episode(self, podcast_id: int, cleaned_data: dict) -> Episode:
        metadata = cleaned_data.get("meta")
        audio_file = await File.create(
            self.db_session,
            FileType.AUDIO,
            available=False,
            owner_id=self.request.user.id,
            source_url="",
            path=cleaned_data["path"],
            size=cleaned_data["size"],
        )
        title, description = self._prepare_meta(cleaned_data)
        logger.debug(
            "Creating episode with data: title: %s | description %s | metadata: %s.",
            title, description, cleaned_data.get("meta")
        )

        episode = await Episode.async_create(
            self.db_session,
            title=title,
            source_id=get_source_id(),
            source_type=SourceType.UPLOAD,
            podcast_id=podcast_id,
            audio_id=audio_file.id,
            watch_url="",
            length=metadata["duration"],
            description=description,
            author=metadata.get("author", ''),
        )
        return episode

    @staticmethod
    def _prepare_meta(cleaned_data: dict) -> tuple[str, str]:
        metadata = cleaned_data["meta"]
        if not (title := metadata.get("title")):
            filename = os.path.basename(cleaned_data["path"])
            title = filename.rpartition('.')[0] if "." in filename else filename

        title_prefix = ""
        if album := metadata.get("album"):
            title_prefix += album
        if track := metadata.get("track"):
            title_prefix += f" #{track}" if title_prefix else f"Track #{track}"

        title = f"{title_prefix}. {title}" if title_prefix else title

        description = f"Uploaded Episode '{title}'"
        if album:
            description += f"\nAlbum: {album}"
        if album and track:
            description += f" (track #{track})"
        elif track:
            description += f"\nTrack: #{track}"
        if author := metadata.get("author"):
            description += f"\nAuthor: {author}"

        return cut_string(title, 255), description


class EpisodeRUDAPIView(BaseHTTPEndpoint):
    """Retrieve, Update, Delete API for episodes"""

    db_model = Episode
    schema_request = EpisodeUpdateSchema
    schema_response = EpisodeDetailsSchema

    async def get(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        return self._response(episode)

    async def patch(self, request):
        episode_id = request.path_params["episode_id"]
        cleaned_data = await self._validate(request, partial_=True)
        episode = await self._get_object(episode_id)
        await episode.update(self.db_session, **cleaned_data)
        return self._response(episode)

    async def delete(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        await episode.delete(self.db_session)
        return self._response(None, status_code=status.HTTP_204_NO_CONTENT)


class EpisodeDownloadAPIView(BaseHTTPEndpoint):
    """RUN episode's downloading (enqueue background task in RQ)"""

    db_model = Episode
    schema_request = EpisodeUpdateSchema
    schema_response = EpisodeDetailsSchema
    perform_tasks_map = {
        SourceType.YOUTUBE: tasks.DownloadEpisodeTask,
        SourceType.YANDEX: tasks.DownloadEpisodeTask,
        SourceType.UPLOAD: tasks.UploadedEpisodeTask,
    }

    async def put(self, request):
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)

        logger.info(f'Start download process for "{episode.watch_url}"')
        episode.status = Episode.Status.DOWNLOADING
        await episode.update(self.db_session, status=episode.status)
        task_class = self.perform_tasks_map.get(episode.source_type)
        await self._run_task(task_class, episode_id=episode.id)
        return self._response(episode)


# Upload file as a new episode
# 1) create new endpoint for uploading file
# 2) save file to tmp directory
# 3) create episode + audio (without image, use default instead)
#       link episode with downloaded file in tmp dir (ex.: save local path to "path" field)
# 4) run task for uploading to s3 storage (or reuse DownloadEpisodeTask instead: override )
# 5) task: upload file to S3 (without postprocessing)
# 6) task: update episode, audio + regenerate RSS
# 7) task: remove tmp file

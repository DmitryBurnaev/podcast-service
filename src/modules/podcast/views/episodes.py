import logging
from typing import Type

from marshmallow import Schema
from sqlalchemy import exists
from starlette import status
from starlette.responses import Response

from common.enums import FileType, SourceType, EpisodeStatus
from common.request import PRequest
from common.statuses import ResponseStatus
from common.utils import cut_string
from common.views import BaseHTTPEndpoint
from common.exceptions import MethodNotAllowedError, NotFoundError, InvalidRequestError
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
from modules.podcast.tasks import DownloadEpisodeTask, DownloadEpisodeImageTask, GenerateRSSTask

logger = logging.getLogger(__name__)


class EpisodeListCreateAPIView(BaseHTTPEndpoint):
    """List and Create (based on `EpisodeCreator` logic) API for episodes"""

    @property
    def schema_request(self) -> Type[Schema]:
        schema_map = {"get": EpisodeListRequestSchema, "post": EpisodeCreateSchema}
        return schema_map.get(self.request.method.lower())

    @property
    def schema_response(self) -> Type[Schema]:
        schema_map = {"get": EpisodeListResponseSchema, "post": EpisodeListSchema}
        return schema_map.get(self.request.method.lower())

    async def get(self, request: PRequest) -> Response:
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

    async def post(self, request: PRequest) -> Response:
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
    schema_response = EpisodeDetailsSchema
    db_model = Podcast

    async def get(self, request: PRequest) -> Response:
        podcast: Podcast = await self._get_object(request.path_params["podcast_id"])
        logger.info(
            "Fetching episode for uploaded file for podcast %(podcast_id)s | hash %(hash)s",
            request.path_params,
        )
        if episode := await self._get_episode(podcast.id, audio_hash=request.path_params["hash"]):
            return self._response(episode)

        raise NotFoundError(
            "Episode by requested hash not found",
            response_status=ResponseStatus.EXPECTED_NOT_FOUND,
        )

    async def post(self, request: PRequest) -> Response:
        podcast: Podcast = await self._get_object(request.path_params["podcast_id"])
        logger.info("Creating episode for uploaded file for podcast %s", podcast)

        cleaned_data = await self._validate(request)

        if episode := await self._get_episode(podcast.id, audio_hash=cleaned_data["hash"]):
            created = False
        else:
            episode = await self._create_episode(podcast.id, cleaned_data)
            created = True

        if podcast.download_automatically:
            await self._run_task(tasks.UploadedEpisodeTask, episode_id=episode.id)

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return self._response(episode, status_code=status_code)

    async def _get_episode(self, podcast_id: int, audio_hash: str) -> Episode | None:
        source_id = self._get_source_id(audio_hash)
        episode = await Episode.async_get(
            self.db_session,
            source_type=SourceType.UPLOAD,
            podcast_id=podcast_id,
            source_id=source_id,
        )
        if episode:
            logger.info("Episode with source_id (hash) '%s' exist. Return %s", source_id, episode)

        return episode

    async def _create_episode(self, podcast_id: int, cleaned_data: dict) -> Episode:
        metadata = cleaned_data.get("meta")
        audio_file, image_file = await self._create_files(cleaned_data)

        title, description = self._prepare_meta(cleaned_data)
        logger.info(
            "Creating episode with data: title: %s | description %s | metadata: %s.",
            title,
            description,
            cleaned_data.get("meta"),
        )
        episode = await Episode.async_create(
            self.db_session,
            title=title,
            source_id=self._get_source_id(cleaned_data["hash"]),
            source_type=SourceType.UPLOAD,
            podcast_id=podcast_id,
            audio_id=audio_file.id,
            image_id=image_file.id if image_file else None,
            owner_id=self.request.user.id,
            watch_url="",
            length=metadata["duration"],
            description=description,
            author=metadata.get("author", ""),
        )
        episode.audio = audio_file
        episode.image = image_file
        return episode

    async def _create_files(self, cleaned_data: dict) -> tuple[File, File | None]:
        metadata = cleaned_data.get("meta")
        audio_file = await File.create(
            self.db_session,
            FileType.AUDIO,
            available=False,
            owner_id=self.request.user.id,
            path=cleaned_data["path"],
            size=cleaned_data["size"],
            hash=cleaned_data["hash"],
            meta=metadata,
        )
        image_file = None
        if cover := cleaned_data.get("cover"):
            image_file = await File.async_get(
                self.db_session, hash=cover["hash"], owner_id=self.request.user.id
            )
            if not image_file:
                image_file = await File.create(
                    self.db_session,
                    FileType.IMAGE,
                    available=True,
                    owner_id=self.request.user.id,
                    path=cover["path"],
                    size=cover["size"],
                    hash=cover["hash"],
                )

        return audio_file, image_file

    @staticmethod
    def _get_source_id(audio_hash: str) -> str:
        return f"upl_{audio_hash[:11]}"

    @staticmethod
    def _prepare_meta(cleaned_data: dict) -> tuple[str, str]:
        metadata = cleaned_data["meta"]
        if not (title := metadata.get("title")):
            filename = cleaned_data["name"]
            title = filename.rpartition(".")[0] if "." in filename else filename

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

    async def get(self, request: PRequest) -> Response:
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        return self._response(episode)

    async def patch(self, request: PRequest) -> Response:
        episode_id = request.path_params["episode_id"]
        cleaned_data = await self._validate(request, partial_=True)
        episode = await self._get_object(episode_id)
        await episode.update(self.db_session, **cleaned_data)
        return self._response(episode)

    async def delete(self, request: PRequest) -> Response:
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)
        await episode.delete(self.db_session)
        DownloadEpisodeTask.cancel_task(episode_id=episode_id)
        DownloadEpisodeImageTask.cancel_task(episode_id=episode_id)
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

    async def put(self, request: PRequest) -> Response:
        episode_id = request.path_params["episode_id"]
        episode = await self._get_object(episode_id)

        logger.info("Start download process for '%s'", episode.watch_url)
        episode.status = Episode.Status.DOWNLOADING
        await episode.update(self.db_session, status=episode.status)
        task_class = self.perform_tasks_map.get(episode.source_type)
        await self._run_task(task_class, episode_id=episode.id)
        return self._response(episode)


class EpisodeCancelDownloading(BaseHTTPEndpoint):
    """  Allows to stop current downloaded episode """
    async def put(self, request: PRequest) -> Response:
        episode_id = request.path_params["episode_id"]
        episode: Episode = await Episode.async_get(self.db_session, id=episode_id)
        if not episode or episode.status != EpisodeStatus.DOWNLOADING:
            raise InvalidRequestError(f"Episode #{episode_id} not found or is not in progress now")

        DownloadEpisodeTask.cancel_task(episode_id=episode_id)
        DownloadEpisodeImageTask.cancel_task(episode_id=episode_id)
        return self._response(None, status_code=status.HTTP_204_NO_CONTENT)

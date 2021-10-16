import re
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from common.storage import StorageS3
from common.utils import get_logger
from common.exceptions import InvalidParameterError, S3UploadingError
from core import settings
from modules.podcast.models import Episode
from modules.podcast.utils import get_file_name
from modules.youtube.utils import get_youtube_info, get_video_id
from modules.youtube.exceptions import YoutubeFetchError

logger = get_logger(__name__)


class EpisodeCreator:
    """Allows to extract info from YouTube end create (if necessary) episode"""

    symbols_regex = re.compile("[&^<>*#]")
    http_link_regex = re.compile(
        "http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%-[0-9a-fA-F][0-9a-fA-F])+"
    )
    allowed_alternative_sources = [
        'music.yandex.ru'
    ]

    def __init__(self, db_session: AsyncSession, podcast_id: int, source_url: str, user_id: int):
        self.db_session = db_session
        self.podcast_id = podcast_id
        self.user_id = user_id
        self.source_url = source_url
        self.source_id = get_video_id(source_url)
        if not self.source_id:
            raise InvalidParameterError("Couldn't extract source_id from the source link")

    async def create(self) -> Episode:
        """
        Allows to create new or return exists episode for current podcast

        :raise: `modules.youtube.exceptions.YoutubeFetchError`
        :return: New <Episode> object
        """
        # TODO: inject cookie (in netscape format) from yandex
        same_episodes: Iterable[Episode] = await Episode.async_filter(
            self.db_session, source_id=self.source_id
        )
        episode_in_podcast, last_same_episode = None, None
        for episode in same_episodes:
            last_same_episode = last_same_episode or episode
            if episode.podcast_id == self.podcast_id:
                episode_in_podcast = episode
                break

        if episode_in_podcast:
            logger.info(
                f"Episode for video [{self.source_id}] already exists for current "
                f"podcast {self.podcast_id}. Retrieving {episode_in_podcast}..."
            )
            return episode_in_podcast

        episode_data = await self._get_episode_data(same_episode=last_same_episode)
        return await Episode.async_create(self.db_session, **episode_data)

    def _replace_special_symbols(self, value):
        res = self.http_link_regex.sub("[LINK]", value)
        return self.symbols_regex.sub("", res)

    async def _get_episode_data(self, same_episode: Episode) -> dict:
        """
        Allows to get information for new episode.
        This info can be given from same episode (episode which has same source_id)
        and part information - from YouTube.

        :return: dict with information for new episode
        """

        if same_episode:
            logger.info(f"Episode for video {self.source_id} already exists: {same_episode}.")
            same_episode_data = same_episode.to_dict()
        else:
            logger.info(f"New episode for video {self.source_id} will be created.")
            same_episode_data = {}

        extract_error, youtube_info = await get_youtube_info(self.source_url)

        if youtube_info:
            logger.info("Episode will be created from the YouTube video.")
            new_episode_data = {
                "source_id": self.source_id,
                "watch_url": youtube_info.watch_url,
                "title": self._replace_special_symbols(youtube_info.title),
                "description": self._replace_special_symbols(youtube_info.description),
                "image_url": youtube_info.thumbnail_url,
                "author": youtube_info.author,
                "length": youtube_info.length,
                "file_size": same_episode_data.get("file_size"),
                "file_name": same_episode_data.get("file_name") or get_file_name(self.source_id),
                "remote_url": same_episode_data.get("remote_url"),
            }

        elif same_episode:
            logger.info("Episode will be copied from other episode with same video.")
            same_episode_data.pop("id", None)
            new_episode_data = same_episode_data

        else:
            raise YoutubeFetchError(f"Extracting data for new Episode failed: {extract_error}")

        new_episode_data.update({"podcast_id": self.podcast_id, "created_by_id": self.user_id})
        return new_episode_data

    def _save_image(self, source_url: str):
        ...

        src_path = ""  # TODO: save tmp file here
        storage = StorageS3()
        result_url = storage.upload_file(
            src_path=src_path,
            dst_path=settings.S3_BUCKET_AUDIO_PATH,
        )
        if not result_url:
            raise S3UploadingError("Couldn't upload episode cover to S3 storage")

        return result_url

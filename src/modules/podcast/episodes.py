import re
from collections.abc import Iterable
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import FileType
from common.utils import get_logger
from modules.media.models import File
from modules.podcast.models import Episode, Cookie
from modules.providers.utils import SourceInfo
from modules.providers import utils as provider_utils
from modules.providers.exceptions import SourceFetchError

logger = get_logger(__name__)


class EpisodeCreator:
    """Allows extracting info from Source end create episode (if necessary)"""

    symbols_regex = re.compile("[&^<>*#]")
    http_link_regex = re.compile(
        "http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%-[0-9a-fA-F][0-9a-fA-F])+"
    )

    def __init__(self, db_session: AsyncSession, podcast_id: int, source_url: str, user_id: int):
        self.db_session: AsyncSession = db_session
        self.podcast_id: int = podcast_id
        self.user_id: int = user_id
        self.source_info: SourceInfo = provider_utils.extract_source_info(source_url)
        self.source_id: str = self.source_info.id

    async def create(self) -> Episode:
        """
        Allows to create new or return exists episode for current podcast

        :raise: `modules.providers.exceptions.SourceFetchError`
        :return: New <Episode> object
        """
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

    async def _get_episode_data(self, same_episode: Optional[Episode]) -> dict:
        """
        Allows getting information for new episode.
        This info can be given from same episode (episode which has same source_id)
        and part information - from ExternalSource (ex.: YouTube)

        :return: dict with information for the new episode
        """

        if same_episode:
            logger.info(f"Episode for video {self.source_id} already exists: {same_episode}.")
            same_episode_data = same_episode.to_dict()
        else:
            logger.info(f"New episode for source {self.source_id} will be created.")
            same_episode_data = {}

        cookie = await Cookie.async_get(
            self.db_session,
            source_type=self.source_info.type,
            owner_id=self.user_id,
        )
        self.source_info.cookie = cookie
        extract_error, source_info = await provider_utils.get_source_media_info(self.source_info)

        if same_episode:
            logger.info("Episode will be copied from other episode with same video.")
            same_episode_data.pop("id", None)
            new_episode_data = same_episode_data
            image_file = await File.copy(
                self.db_session,
                owner_id=self.user_id,
                file_id=same_episode_data['image_id'],
            )
            audio_file = await File.copy(
                self.db_session,
                owner_id=self.user_id,
                file_id=same_episode_data['audio_id']
            )

        elif source_info:
            logger.info("Episode will be created from the source.")
            image_file = await File.create(
                self.db_session,
                FileType.IMAGE,
                owner_id=self.user_id,
                source_url=source_info.thumbnail_url,
            )
            audio_file = None
            new_episode_data = {
                "source_id": self.source_id,
                "source_type": self.source_info.type,
                "watch_url": source_info.watch_url,
                "title": self._replace_special_symbols(source_info.title),
                "description": self._replace_special_symbols(source_info.description),
                "author": source_info.author,
                "length": source_info.length,
            }

        else:
            raise SourceFetchError(f"Extracting data for new Episode failed: {extract_error}")

        new_episode_data.update(
            {
                "podcast_id": self.podcast_id,
                "owner_id": self.user_id,
                "cookie_id": cookie.id if cookie else None,
                "image_id": image_file.id,
                "audio_id": audio_file.id if audio_file else None,
            }
        )
        return new_episode_data

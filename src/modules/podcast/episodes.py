import logging
import re
from collections import Iterable

from common.exceptions import YoutubeFetchError, InvalidParameterError
from common.utils import get_logger
from modules.podcast.models import Episode
from modules.podcast.utils import get_file_name
from modules.youtube.utils import get_youtube_info, get_video_id

logger = get_logger(__name__)


class EpisodeCreator:
    """ Allows to extract info from YouTube end create episode """

    symbols_regex = re.compile("[&^<>*#]")
    http_link_regex = re.compile(
        "http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%-[0-9a-fA-F][0-9a-fA-F]))+"
    )

    def __init__(self, podcast_id: int, youtube_link: str, user_id: int):
        self.podcast_id = podcast_id
        self.user_id = user_id
        self.youtube_link = youtube_link
        self.video_id = get_video_id(youtube_link)
        if not self.video_id:
            raise InvalidParameterError({"youtube_link": "Couldn't extract video_id from link"})

    async def create(self) -> Episode:

        same_episodes: Iterable[Episode] = await Episode.async_filter(source_id=self.video_id)
        episode_in_podcast, last_same_episode = None, None
        for episode in same_episodes:
            last_same_episode = last_same_episode or episode
            if episode.podcast_id == self.podcast_id:
                episode_in_podcast = episode
                break

        if episode_in_podcast:
            logger.info(
                f"Episode for video [{self.video_id}] already exists for current "
                f"podcast {self.podcast_id}. Retrieving {episode_in_podcast}..."
            )
            return episode_in_podcast

        episode_data = await self._get_episode_info(
            same_episode=last_same_episode,
            podcast_id=self.podcast_id,
            video_id=self.video_id,
            youtube_link=self.youtube_link,
        )

        return await Episode.create(**episode_data)

    def _replace_special_symbols(self, value):
        res = self.http_link_regex.sub("[LINK]", value)
        return self.symbols_regex.sub("", res)

    async def _get_episode_info(
        self, same_episode: Episode, podcast_id: int, video_id: str, youtube_link: str
    ) -> dict:
        """
        Allows to get information for new episode.
        This info can be given from same episode (episode which has same source_id)
        and part information - from YouTube.

        :return: dict with information for new episode
        """

        if same_episode:
            logger.info(
                f"Episode for video {video_id} already exists: {same_episode}. "
                f"Using for information about downloaded file."
            )
            same_episode_data = same_episode.to_dict(
                field_names=[
                    "source_id",
                    "watch_url",
                    "title",
                    "description",
                    "image_url",
                    "author",
                    "length",
                    "file_size",
                    "file_name",
                    "remote_url",
                ]
            )
        else:
            logger.info(f"New episode for video {video_id} will be created.")
            same_episode_data = {}

        youtube_info = await get_youtube_info(youtube_link)

        if youtube_info:
            new_episode_data = {
                "source_id": video_id,
                "watch_url": youtube_info.watch_url,
                "title": self._replace_special_symbols(youtube_info.title),
                "description": self._replace_special_symbols(youtube_info.description),
                "image_url": youtube_info.thumbnail_url,
                "author": youtube_info.author,
                "length": youtube_info.length,
                "file_size": same_episode_data.get("file_size"),
                "file_name": same_episode_data.get("file_name") or get_file_name(video_id),
                "remote_url": same_episode_data.get("remote_url"),
            }
            message = "Episode was successfully created from the YouTube video."
            logger.info(message)
            logger.debug("New episode data = %s", new_episode_data)
        elif same_episode:
            message = "Episode will be copied from other episode with same video."
            logger.info(message)
            new_episode_data = same_episode_data
        else:
            raise YoutubeFetchError

        new_episode_data.update({"podcast_id": podcast_id, "created_by_id": self.user_id})
        return new_episode_data

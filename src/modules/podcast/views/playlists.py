import asyncio
from functools import partial

import youtube_dl

from common.exceptions import InvalidParameterError
from common.utils import cut_string, get_logger
from common.views import BaseHTTPEndpoint
from modules.podcast.schemas import PlayListRequestSchema, PlayListResponseSchema

logger = get_logger(__name__)


class PlayListAPIView(BaseHTTPEndpoint):
    """Allows extracting info from each episode in requested playlist"""

    schema_request = PlayListRequestSchema
    schema_response = PlayListResponseSchema

    async def get(self, request):

        cleaned_data = await self._validate(request, location="query")
        playlist_url = cleaned_data.get("url")
        loop = asyncio.get_running_loop()

        # TODO: use GoogleAPI instead of this solution (probably, it will be much faster)
        with youtube_dl.YoutubeDL({"logger": logger, "noplaylist": False}) as ydl:
            extract_info = partial(ydl.extract_info, playlist_url, download=False)
            try:
                youtube_details = await loop.run_in_executor(None, extract_info)
            except youtube_dl.utils.DownloadError as err:
                raise InvalidParameterError(f"Couldn't extract playlist: {err}")

        yt_content_type = youtube_details.get("_type")
        if yt_content_type != "playlist":
            logger.warning("Unknown type of returned providers details: %s", yt_content_type)
            logger.debug("Returned info: {%s}", youtube_details)
            raise InvalidParameterError(
                details=f"It seems like incorrect playlist. {yt_content_type=}"
            )

        entries = [
            {
                "id": video["id"],
                "title": video["title"],
                "description": cut_string(video["description"], 200),
                "thumbnail_url": video["thumbnails"][0]["url"] if video.get("thumbnails") else "",
                "url": video["webpage_url"],
            }
            for video in youtube_details["entries"]
        ]
        res = {"id": youtube_details["id"], "title": youtube_details["title"], "entries": entries}
        return self._response(res)

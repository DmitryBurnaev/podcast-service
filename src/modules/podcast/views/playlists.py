# import asyncio
from functools import partial

import yt_dlp
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from common.enums import SourceType
from common.request import PRequest
from common.views import BaseHTTPEndpoint
from common.utils import cut_string, get_logger
from common.exceptions import InvalidRequestError
from modules.providers import utils
from modules.podcast.models import Cookie
from modules.podcast.schemas import PlayListRequestSchema, PlayListResponseSchema

logger = get_logger(__name__)


class PlayListAPIView(BaseHTTPEndpoint):
    """Allows extracting info from each episode in requested playlist"""

    schema_request = PlayListRequestSchema
    schema_response = PlayListResponseSchema

    async def get(self, request: PRequest) -> Response:

        cleaned_data = await self._validate(request, location="query")
        playlist_url = cleaned_data.get("url")
        # loop = asyncio.get_running_loop()
        source_info = utils.extract_source_info(playlist_url, playlist=True)

        params = {"logger": logger, "noplaylist": False}
        if cookie := await self._fetch_cookie(request, source_info.type):
            params["cookiefile"] = cookie.as_file()

        with yt_dlp.YoutubeDL(params) as ydl:
            extract_info = partial(ydl.extract_info, playlist_url, download=False)
            try:
                source_data = await run_in_threadpool(extract_info)
                # source_data = await loop.run_in_executor(None, extract_info)
            except yt_dlp.utils.DownloadError as exc:
                raise InvalidRequestError(f"Couldn't extract playlist: {exc}") from exc

        yt_content_type = source_data.get("_type")
        if yt_content_type != "playlist":
            logger.warning("Unknown type of returned providers details: %s", yt_content_type)
            logger.debug("Returned info: {%s}", source_data)
            raise InvalidRequestError(
                details=f"It seems like incorrect playlist. {yt_content_type=}"
            )

        entries = [
            {
                "id": video["id"],
                "title": video["title"],
                "description": self._prepare_description(source_info.type, video),
                "thumbnail_url": video["thumbnails"][0]["url"] if video.get("thumbnails") else "",
                "url": video["webpage_url"],
            }
            for video in source_data["entries"]
        ]
        res = {"id": source_data["id"], "title": source_data["title"], "entries": entries}
        return self._response(res)

    async def _fetch_cookie(self, request: PRequest, source_type: SourceType) -> Cookie | None:
        cookie = await Cookie.async_get(
            self.db_session,
            source_type=source_type,
            owner_id=request.user.id,
        )
        return cookie

    @staticmethod
    def _prepare_description(source_type: SourceType, data: dict) -> str:
        if source_type == SourceType.YOUTUBE:
            return cut_string(data["description"], 200)
        if source_type == SourceType.YANDEX:
            return (
                f'Playlist "{data["playlist"]}" '
                f'| Track #{data["playlist_index"]} of {data["n_entries"]}'
            )

        raise NotImplementedError(f"Unexpected source_type: {source_type}")

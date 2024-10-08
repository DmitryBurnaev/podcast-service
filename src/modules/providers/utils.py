import datetime
import os
import re
import uuid
import hashlib
import logging
import tempfile
import subprocess
import dataclasses
from pathlib import Path
from typing import NamedTuple
from functools import partial
from contextlib import suppress
from multiprocessing import Process

import yt_dlp
from starlette.concurrency import run_in_threadpool
from yt_dlp.utils import YoutubeDLError

from core import settings
from common.enums import SourceType, EpisodeStatus
from common.exceptions import InvalidRequestError, UserCancellationError
from modules.auth.hasher import get_random_hash
from modules.podcast.models import EpisodeChapter
from modules.providers.exceptions import FFMPegPreparationError, FFMPegParseError
from modules.podcast.utils import (
    get_file_size,
    episode_process_hook,
    post_processing_process_hook,
)

logger = logging.getLogger(__name__)


class SourceMediaInfo(NamedTuple):
    """Structure of extended information about media source"""

    watch_url: str
    source_id: str
    description: str
    thumbnail_url: str
    title: str
    author: str
    length: int
    chapters: list[EpisodeChapter]


@dataclasses.dataclass
class SourceConfig:
    type: SourceType
    regexp: str | None = None
    regexp_playlist: str | None = None
    need_postprocessing: bool = False
    need_downloading: bool = True
    proxy_url: str | None = None


@dataclasses.dataclass
class SourceInfo:
    id: str
    type: SourceType
    url: str | None = None
    cookie_path: Path | None = None
    proxy_url: str | None = None


SOURCE_CFG_MAP = {
    SourceType.YOUTUBE: SourceConfig(
        type=SourceType.YOUTUBE,
        regexp=(
            r"^https://(?:www\.)?"
            r"[(?:youtube\.com)|(?:youtu\.be)]+[(/watch\?v=|\/)|(/live/)]+"
            r"(?P<source_id>[0-9a-zA-Z-_]{11})"
        ),
        regexp_playlist=(
            r"^https://(?:www\.)?youtube\.com/playlist\?list=(?P<source_id>[0-9a-zA-Z-_]+)"
        ),
        need_postprocessing=True,
        proxy_url=settings.PROXY_YOUTUBE,
    ),
    SourceType.YANDEX: SourceConfig(
        type=SourceType.YANDEX,
        regexp=r"https?://music\.yandex\.ru\/[a-z\/0-9]+\/track\/(?P<source_id>[0-9]+)",
        regexp_playlist=r"^https://music\.yandex\.ru/album/(?P<source_id>[0-9a-zA-Z-_]+)",
    ),
    SourceType.UPLOAD: SourceConfig(
        type=SourceType.UPLOAD,
        need_downloading=False,
    ),
}

AUDIO_META_REGEXP = re.compile(r"(?P<meta>Metadata.+)?(?P<duration>Duration:\s?[\d:]+)", re.DOTALL)


def extract_source_info(source_url: str | None = None, playlist: bool = False) -> SourceInfo:
    """Extracts providers (source) info and finds source ID"""

    if not source_url:
        random_hash = get_random_hash(size=6)
        return SourceInfo(id=f"U-{random_hash}", type=SourceType.UPLOAD)

    for _, source_cfg in SOURCE_CFG_MAP.items():
        regexp = source_cfg.regexp if not playlist else source_cfg.regexp_playlist
        if match := (re.match(regexp, source_url) if source_cfg.regexp else None):
            if source_id := match.groupdict().get("source_id"):
                return SourceInfo(id=source_id, url=source_url, type=source_cfg.type)

            logger.error(
                "Couldn't extract source ID: Source link is not correct: %s | source_info: %s",
                source_url,
                source_cfg,
            )

    raise InvalidRequestError(f"Requested domain is not supported now {source_url}")


def download_process_hook(event: dict):
    """
    Allows handling processes of downloading episode's file.
    It is called by `yt_dlp.YoutubeDL`
    """
    total_bytes = event.get("total_bytes") or event.get("total_bytes_estimate", 0)
    episode_process_hook(
        status=EpisodeStatus.DL_EPISODE_DOWNLOADING,
        filename=event["filename"],
        total_bytes=total_bytes,
        processed_bytes=event.get("downloaded_bytes", total_bytes),
    )


async def download_audio(
    source_url: str,
    filename: str,
    cookie_path: Path | None,
    proxy_url: str | None = None,
) -> Path:
    """
    Download providers video and perform to audio (.mp3) file

    :param source_url: URL to providers video which are needed to download
    :param filename: autogenerated filename for episode
    :param cookie_path: path to cookie's file for accessing to protected source
    :param proxy_url: proxy DSN for downloading video (specified for each source's type_
    :return path to downloaded file
    """
    result_path = settings.TMP_AUDIO_PATH / filename
    params = {
        "format": "bestaudio/best",
        "outtmpl": str(result_path),
        "logger": logging.getLogger("yt_dlp.YoutubeDL"),
        "progress_hooks": [download_process_hook],
        "noprogress": True,
        "cookiefile": cookie_path,
    }
    if proxy_url:
        logger.info("YoutubeDL: Using proxy: %s", proxy_url)
        params["proxy"] = proxy_url

    with yt_dlp.YoutubeDL(params) as ydl:
        ydl.download([source_url])

    return result_path


async def get_source_media_info(source_info: SourceInfo) -> tuple[str, SourceMediaInfo | None]:
    """Allows extract info about providers video from Source (powered by yt_dlp)"""

    logger.info("Started fetching data for %s", source_info.url)
    params = {"logger": logger, "noplaylist": True, "cookiefile": source_info.cookie_path}
    if source_info.proxy_url:
        params["proxy"] = source_info.proxy_url
        logger.info("YoutubeDL: Using proxy: %s", source_info.proxy_url)

    try:
        with yt_dlp.YoutubeDL(params) as ydl:
            extract_info = partial(ydl.extract_info, source_info.url, download=False)
            source_details = await run_in_threadpool(extract_info)

    except YoutubeDLError as exc:
        logger.exception("ydl.extract_info failed: %s | Error: %r", source_info.url, exc)
        return str(exc), None

    youtube_info = SourceMediaInfo(
        title=source_details["title"],
        description=source_details.get("description") or source_details.get("title"),
        watch_url=source_details["webpage_url"],
        source_id=source_details["id"],
        thumbnail_url=source_details["thumbnail"],
        author=source_details.get("uploader") or source_details.get("artist"),
        length=source_details["duration"],
        chapters=chapters_processing(source_details.get("chapters")),
    )
    return "OK", youtube_info


def chapters_processing(input_chapters: list[dict] | None) -> list[EpisodeChapter]:
    """
    Allows to process input chapters data and adapt to internal chapter's format
    (for saving in DB and using in RSS generation)

    input:
        [{'end_time': 68.0, 'start_time': 15.0, 'title': 'Start application'}, ...]
    output:
        [EpisodeChapter(title='Start application', start='00:00:15', end='00:01:08'), ...]

    :param input_chapters: list of chapters data
    :return: list of chapters items
    """
    result_chapters: list[EpisodeChapter] = []
    if not input_chapters:
        return []

    def ftime(sec: str) -> str:
        result_delta: datetime.timedelta = datetime.timedelta(seconds=int(sec))
        mm, ss = divmod(result_delta.total_seconds(), 60)
        hh, mm = divmod(mm, 60)
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"  # 123sec -> '00:02:03'

    for input_chapter in input_chapters:
        try:
            chapter = EpisodeChapter(
                title=input_chapter["title"],
                start=ftime(input_chapter["start_time"]),
                end=ftime(input_chapter["end_time"]),
            )

        except (KeyError, ValueError) as exc:
            logger.error("Couldn't prepare episode's chapter: %s | err: %r", input_chapter, exc)

        else:
            result_chapters.append(chapter)

    return result_chapters


def ffmpeg_preparation(
    src_path: str | Path,
    ffmpeg_params: list[str] = None,
    call_process_hook: bool = True,
) -> None:
    """
    FFmpeg allows fixing problem with length of audio track
    (in metadata value for this is incorrect, but fact length is fully correct)
    """
    filename = os.path.basename(str(src_path))
    logger.info("Start FFMPEG preparations for %s === ", filename)
    total_bytes = get_file_size(src_path)
    if call_process_hook:
        episode_process_hook(
            status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
            filename=filename,
            total_bytes=total_bytes,
            processed_bytes=0,
        )

    tmp_path = settings.TMP_AUDIO_PATH / f"tmp_{filename}"

    logger.info("=== Start SUBPROCESS (filesize watching) for %s === ", filename)
    watcher_process = Process(
        target=post_processing_process_hook,
        kwargs={
            "filename": filename,
            "target_path": tmp_path,
            "total_bytes": total_bytes,
            "src_file_path": src_path,
        },
    )
    watcher_process.start()

    try:
        ffmpeg_params = ffmpeg_params or ["-vn", "-acodec", "libmp3lame", "-q:a", "5"]
        completed_proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, *ffmpeg_params, tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=settings.FFMPEG_TIMEOUT,
        )

    except Exception as exc:
        watcher_process.terminate()
        # pylint: disable=no-member
        if isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 255:
            raise UserCancellationError("Background FFMPEG processing was interrupted") from exc

        episode_process_hook(status=EpisodeStatus.ERROR, filename=filename)
        with suppress(IOError):
            os.remove(tmp_path)

        err_details = f"FFMPEG failed with errors: {exc}"
        if stdout := getattr(exc, "stdout", ""):
            err_details += f"\n{str(stdout, encoding='utf-8')}"

        watcher_process.terminate()
        raise FFMPegPreparationError(err_details) from exc

    watcher_process.terminate()
    logger.info(
        "FFMPEG success done preparation for file %s:\n%s",
        filename,
        str(completed_proc.stdout, encoding="utf-8"),
    )

    try:
        if not tmp_path.exists():
            raise IOError(f"Prepared file {tmp_path} wasn't created")

        os.remove(src_path)
        os.rename(tmp_path, src_path)

    except IOError as exc:
        episode_process_hook(status=EpisodeStatus.ERROR, filename=filename)
        raise FFMPegPreparationError(f"Failed to rename/remove tmp file: {exc}") from exc

    total_file_size = get_file_size(src_path)
    if call_process_hook:
        episode_process_hook(
            status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
            filename=filename,
            total_bytes=total_file_size,
            processed_bytes=total_file_size,
        )
    logger.info("FFMPEG Preparation for %s was done", filename)


class AudioMetaData(NamedTuple):
    title: str | None = None
    duration: int | None = None
    track: str | None = None
    album: str | None = None
    author: str | None = None


class CoverMetaData(NamedTuple):
    path: Path
    hash: str
    size: int


def execute_ffmpeg(command: list[str]) -> str:
    try:
        logger.debug("Executing FFMPEG: '%s'", " ".join(map(str, command)))
        completed_proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=settings.FFMPEG_TIMEOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        err_details = f"FFMPEG failed with errors: {exc}"
        if stdout := getattr(exc, "stdout", ""):
            err_details += f"\n{str(stdout, encoding='utf-8')}"

        raise FFMPegPreparationError(err_details) from exc

    return completed_proc.stdout.decode()


def audio_metadata(file_path: Path | str) -> AudioMetaData:
    """Calculates (via ffmpeg) length of audio track and returns number of seconds"""

    with tempfile.NamedTemporaryFile() as tmp_metadata_file:
        metadata_str = execute_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(file_path),
                "-f",
                "ffmetadata",
                tmp_metadata_file.name,
            ]
        )

    # ==== Extracting meta data ===
    find_results = AUDIO_META_REGEXP.search(metadata_str, re.DOTALL)
    if not find_results:
        raise FFMPegParseError(f"Found result: {metadata_str}")

    find_results = find_results.groupdict()
    duration = _human_time_to_sec(find_results.get("duration", "").replace("Duration:", ""))
    metadata = _raw_meta_to_dict((find_results.get("meta") or "").replace("Metadata:\n", ""))

    logger.debug(
        "FFMPEG success done extracting duration from the file %s:\nmeta: %s\nduration: %s",
        file_path,
        metadata,
        duration,
    )
    return AudioMetaData(
        title=metadata.get("title"),
        author=metadata.get("artist"),
        album=metadata.get("album"),
        track=metadata.get("track"),
        duration=duration,
    )


def get_file_hash(file_path: Path) -> str:
    file_content = file_path.read_bytes()
    return hashlib.sha256(file_content).hexdigest()[:32]


def audio_cover(audio_file_path: Path) -> CoverMetaData | None:
    """Extracts cover from audio file (if exists)"""

    try:
        cover_path = settings.TMP_IMAGE_PATH / f"tmp_cover_{uuid.uuid4().hex}.jpg"
        execute_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_file_path,
                "-an",
                "-an",
                "-c:v",
                "copy",
                cover_path,
            ]
        )
    except FFMPegPreparationError as exc:
        logger.warning("Couldn't extract cover from audio file: %r", exc)
        return None

    cover_hash = get_file_hash(cover_path)
    new_cover_path = settings.TMP_IMAGE_PATH / f"cover_{cover_hash}.jpg"
    os.rename(cover_path, new_cover_path)
    return CoverMetaData(path=new_cover_path, hash=cover_hash, size=get_file_size(new_cover_path))


def _raw_meta_to_dict(meta: str | None) -> dict:
    """
    Converts raw metadata from ffmpeg to dict values

    >>> _raw_meta_to_dict('    album           : TestAlbum\\n    artist          : Artist')
    {'album': 'TestAlbum', 'artist': 'Artist'}

    """
    result = {}
    for meta_str in meta.split("\n"):
        try:
            key, value = meta_str.split(":")
        except ValueError:
            continue

        result[key.strip()] = value.strip()

    return result


def _human_time_to_sec(time_str: str) -> int:
    """
    Converts human time like '01:01:20.23' to seconds count 3680

    >>> _human_time_to_sec('00:01:16.75')
    77
    >>> _human_time_to_sec('01:01:20.232443')
    3680

    """

    time_items = time_str.rstrip(",").split(":")
    res_time = 0
    for index, time_item in enumerate(reversed(time_items)):
        res_time += round(float(time_item), 0) * pow(60, index)

    return int(res_time)

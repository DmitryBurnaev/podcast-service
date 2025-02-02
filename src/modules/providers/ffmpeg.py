import os
import re
import uuid
import logging
import hashlib
import tempfile
import subprocess
from pathlib import Path
from typing import NamedTuple, TYPE_CHECKING
from contextlib import suppress
from multiprocessing import Process

from core import settings
from common.utils import cut_string
from common.enums import EpisodeStatus
from common.exceptions import UserCancellationError
from modules.podcast import utils as podcast_utils
from modules.providers.exceptions import FFMPegPreparationError, FFMPegParseError

if TYPE_CHECKING:
    from modules.podcast.models import EpisodeMetadata

logger = logging.getLogger(__name__)
AUDIO_META_REGEXP = re.compile(r"(?P<meta>Metadata.+)?(?P<duration>Duration:\s?[\d:]+)", re.DOTALL)


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
    total_bytes = podcast_utils.get_file_size(src_path)
    if call_process_hook:
        podcast_utils.episode_process_hook(
            status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
            filename=filename,
            total_bytes=total_bytes,
            processed_bytes=0,
        )

    tmp_path = settings.TMP_AUDIO_PATH / f"tmp_{filename}"

    logger.info("=== Start SUBPROCESS (filesize watching) for %s === ", filename)
    watcher_process = Process(
        target=podcast_utils.post_processing_process_hook,
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

        podcast_utils.episode_process_hook(status=EpisodeStatus.ERROR, filename=filename)
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
        podcast_utils.episode_process_hook(status=EpisodeStatus.ERROR, filename=filename)
        raise FFMPegPreparationError(f"Failed to rename/remove tmp file: {exc}") from exc

    total_file_size = podcast_utils.get_file_size(src_path)
    if call_process_hook:
        podcast_utils.episode_process_hook(
            status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
            filename=filename,
            total_bytes=total_file_size,
            processed_bytes=total_file_size,
        )
    logger.info("FFMPEG Preparation for %s was done", filename)


def execute_ffmpeg(command: list[str]) -> str:
    """Call ffmpeg's subprocess to execute given command"""

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


def ffmpeg_set_metadata(src_path: Path, metadata: "EpisodeMetadata") -> None:
    """
    Generates text-like metadata and apply to the target audio, placed on src_path

    # =====
    # Example input metadata
        (set via `ffmpeg -i file.mp3 -i metadata.txt -map_metadata 1 -codec copy output.mp3`)
    # =====
    ;FFMETADATA1
    title=bike\\shed
    artist=FFmpegPrep

    [CHAPTER]
    TIMEBASE=1/1000
    START=0
    #chapter ends at 0:01:00
    END=60000
    title=chapter #1

    # =====
    # Example metadata (got via ffmpeg -i file.mp3 -ffmetadata):
    # =====
    Chapter #0:0: start 0.000000, end 440.000000
      Metadata:
        title           : chapter-1
    Chapter #0:1: start 440.000000, end 4306.000000
      Metadata:
        title           : chapter-2
    Chapter #0:2: start 4306.000000, end 6195.000000
      Metadata:
        title           : chapter-3
    Chapter #0:3: start 6195.000000, end 7264.000000
      Metadata:
        title           : chapter-4
    Chapter #0:4: start 7264.000000, end 8661.000000
      Metadata:
        title           : chapter-5
    Chapter #0:5: start 8661.000000, end 11628.000000
      Metadata:
        title           : finish-chapter-6

    Stream #0:0: Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s
    """
    chapter_tpl = """
[CHAPTER]
TIMEBASE=1/1000
START={start}
END={end}
title={title}
    """
    metadata_tpl = """
;FFMETADATA1
genre=Podcast
album={podcast_name}
title={episode_title}
artist={episode_author}
{chapters_rendered}
    """.lstrip()

    logger.info(
        "Start setting metadata for the file %s | chapters: %i",
        src_path,
        len(metadata.episode_chapters),
    )
    tmp_audio_file = settings.TMP_AUDIO_PATH / f"tmp_{src_path.name}"
    chapters_rendered = ""
    for chapter in metadata.episode_chapters:
        chapters_rendered += chapter_tpl.rstrip().format(
            start=chapter.start * 1000,
            end=chapter.end * 1000,
            title=cut_string(chapter.title, max_length=settings.EPISODE_CHAPTERS_TITLE_LENGTH),
        )

    result_metadata = metadata_tpl.format(
        podcast_name=metadata.podcast_name,
        episode_title=metadata.episode_title,
        episode_author=metadata.episode_author or "",
        chapters_rendered=chapters_rendered,
    )

    logger.debug("Generated metadata for the file %s:\n%s", src_path, result_metadata)
    metadata_file_path = settings.TMP_META_PATH / f"episode_{metadata.episode_id}.txt"
    metadata_file_path.write_text(result_metadata)
    metadata_str = execute_ffmpeg(
        command=[
            "ffmpeg",
            "-y",
            "-i",
            str(src_path),
            "-i",
            metadata_file_path.absolute(),
            "-map_metadata",
            "1",
            "-codec",
            "copy",
            str(tmp_audio_file),
        ]
    )
    logger.debug("Generated metadata for the file %s:\n%s", src_path, metadata_str)
    if metadata.episode_title not in metadata_str:
        raise RuntimeError(f"Episode title '{metadata.episode_title}' not found in metadata")

    logger.info("Finished setting metadata for the file %s", tmp_audio_file)
    podcast_utils.delete_file(metadata_file_path)

    logger.debug("Moving updated file: %s -> %s", src_path, tmp_audio_file)
    podcast_utils.move_file(tmp_audio_file, src_path)
    logger.info("Metadata was set for the file %s", src_path)


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

    cover_hash = _get_file_hash(cover_path)
    new_cover_path = settings.TMP_IMAGE_PATH / f"cover_{cover_hash}.jpg"
    os.rename(cover_path, new_cover_path)
    return CoverMetaData(
        path=new_cover_path,
        hash=cover_hash,
        size=podcast_utils.get_file_size(new_cover_path),
    )


def _get_file_hash(file_path: Path) -> str:
    file_content = file_path.read_bytes()
    return hashlib.sha256(file_content).hexdigest()[:32]


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

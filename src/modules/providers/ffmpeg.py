import logging
import os
import re
import uuid
import hashlib
import tempfile
import subprocess
from pathlib import Path
from typing import NamedTuple
from contextlib import suppress
from multiprocessing import Process

from core import settings
from common.enums import EpisodeStatus
from common.exceptions import UserCancellationError
from modules.podcast.models import EpisodeChapter
from modules.podcast import utils as podcast_utils
from modules.providers.exceptions import FFMPegPreparationError, FFMPegParseError

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


def ffmpeg_set_metadata(
    src_path: str | Path, episode_title: str, episode_chapters: list[EpisodeChapter]
) -> None:
    """
    Generates text-like metadata and apply to the target audio, placed on src_path

    # =====
    # Example input metadata
        (set via `ffmpeg -i file.mp3 -i metadata.txt -map_metadata 1 -codec copy output.mp3`)
    # =====

    # ;FFMETADATA1
    # title=bike\\shed
    # ;this is a comment
    # artist=FFmpeg troll team
    # [CHAPTER]
    # TIMEBASE=1/1000
    # START=0
    # #chapter ends at 0:01:00
    # END=60000
    # title=chapter #1

    # =====
    # Example metadata (got via ffmpeg -i file.mp3 -ffmetadata):
    # =====
    # Chapter #0:0: start 0.000000, end 440.000000
    #   Metadata:
    #     title           : chapter-1
    # Chapter #0:1: start 440.000000, end 4306.000000
    #   Metadata:
    #     title           : chapter-2
    # Chapter #0:2: start 4306.000000, end 6195.000000
    #   Metadata:
    #     title           : chapter-3
    # Chapter #0:3: start 6195.000000, end 7264.000000
    #   Metadata:
    #     title           : chapter-4
    # Chapter #0:4: start 7264.000000, end 8661.000000
    #   Metadata:
    #     title           : chapter-5
    # Chapter #0:5: start 8661.000000, end 11628.000000
    #   Metadata:
    #     title           : finish-chapter-6
    #
    # Stream #0:0: Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s
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
title={title}

{chapters_rendered}
    """
    logger.info(
        "Start setting metadata for the file %s | chapters: %i", src_path, len(episode_chapters)
    )

    chapters_rendered = ""
    for chapter in episode_chapters:
        chapters_rendered += chapter_tpl.format(
            start=chapter.start * 1000, end=chapter.end * 1000, title=chapter.title
        )

    result_metadata = metadata_tpl.format(title=episode_title, chapters_rendered=chapters_rendered)

    logger.debug("Generated metadata for the file %s:\n%s", src_path, result_metadata)

    with tempfile.NamedTemporaryFile() as tmp_metadata_file:
        tmp_metadata_file.write(result_metadata.encode())
        tmp_metadata_file.flush()
        print(tmp_metadata_file.name)
        print(tmp_metadata_file.read())

        execute_ffmpeg(
            command=[
                "ffmpeg",
                "-y",
                "-i",
                src_path,
                "-i",
                tmp_metadata_file.name,
                "-map_metadata",
                "1",
                "-codec",
                "copy",
                src_path,
            ]
        )

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
    import json

    print(json.dumps(metadata, indent=4))

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


# ;FFMETADATA1
#     Writing frontend=StaxRip v1.7.0.6
#     encoder=Lavf59.27.100
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=0
#     END=921712455555
#     title=Opening Credits/Christmas Eve
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=921712455555
#     END=1228518955555
#     title="One More Sleep Till Christmas"
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=1228518955555
#     END=1771227788888
#     title="Marley & Marley"
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=1771227788888
#     END=2633422455555
#     title=The Ghost of Christmas Past
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=2633422455555
#     END=2910115533333
#     title=A Sad Goodbye
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=2910115533333
#     END=3068398666666
#     title=The Ghost of Christmas Present
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=3068398666666
#     END=3397519122222
#     title="It Feels Like Christmas"
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=3397519122222
#     END=3924378788888
#     title=Christmas at the Cratchits'
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=3924378788888
#     END=4485105622222
#     title=The Ghost of Christmas Yet to Come
#     [CHAPTER]
#     TIMEBASE=1/1000000000
#     START=4485105622222
#     END=5339042000000
#     title=A New Man/End Credits


# {
#         "chapters": [
#             {
#                 "id": 2759040398,
#                 "time_base": "1/1000000000",
#                 "start": 0,
#                 "start_time": "0.000000",
#                 "end": 921712455555,
#                 "end_time": "921.712456",
#                 "tags": {
#                     "title": "Opening Credits/Christmas Eve"
#                 }
#             },
#             {
#                 "id": 2861267123,
#                 "time_base": "1/1000000000",
#                 "start": 921712455555,
#                 "start_time": "921.712456",
#                 "end": 1228518955555,
#                 "end_time": "1228.518956",
#                 "tags": {
#                     "title": "\"One More Sleep Till Christmas\""
#                 }
#             },
#             {
#                 "id": 664919191,
#                 "time_base": "1/1000000000",
#                 "start": 1228518955555,
#                 "start_time": "1228.518956",
#                 "end": 1771227788888,
#                 "end_time": "1771.227789",
#                 "tags": {
#                     "title": "\"Marley & Marley\""
#                 }
#             },
#             {
#                 "id": 1926087814,
#                 "time_base": "1/1000000000",
#                 "start": 1771227788888,
#                 "start_time": "1771.227789",
#                 "end": 2633422455555,
#                 "end_time": "2633.422456",
#                 "tags": {
#                     "title": "The Ghost of Christmas Past"
#                 }
#             },
#             {
#                 "id": 826733475,
#                 "time_base": "1/1000000000",
#                 "start": 2633422455555,
#                 "start_time": "2633.422456",
#                 "end": 2910115533333,
#                 "end_time": "2910.115533",
#                 "tags": {
#                     "title": "A Sad Goodbye"
#                 }
#             },
#             {
#                 "id": 2854997915,
#                 "time_base": "1/1000000000",
#                 "start": 2910115533333,
#                 "start_time": "2910.115533",
#                 "end": 3068398666666,
#                 "end_time": "3068.398667",
#                 "tags": {
#                     "title": "The Ghost of Christmas Present"
#                 }
#             },
#             {
#                 "id": 2195307441,
#                 "time_base": "1/1000000000",
#                 "start": 3068398666666,
#                 "start_time": "3068.398667",
#                 "end": 3397519122222,
#                 "end_time": "3397.519122",
#                 "tags": {
#                     "title": "\"It Feels Like Christmas\""
#                 }
#             },
#             {
#                 "id": 3135875226,
#                 "time_base": "1/1000000000",
#                 "start": 3397519122222,
#                 "start_time": "3397.519122",
#                 "end": 3924378788888,
#                 "end_time": "3924.378789",
#                 "tags": {
#                     "title": "Christmas at the Cratchits'"
#                 }
#             },
#             {
#                 "id": 1030909628,
#                 "time_base": "1/1000000000",
#                 "start": 3924378788888,
#                 "start_time": "3924.378789",
#                 "end": 4485105622222,
#                 "end_time": "4485.105622",
#                 "tags": {
#                     "title": "The Ghost of Christmas Yet to Come"
#                 }
#             },
#             {
#                 "id": 1941534124,
#                 "time_base": "1/1000000000",
#                 "start": 4485105622222,
#                 "start_time": "4485.105622",
#                 "end": 5339042000000,
#                 "end_time": "5339.042000",
#                 "tags": {
#                     "title": "A New Man/End Credits"
#                 }
#             }
#         ]
#     }

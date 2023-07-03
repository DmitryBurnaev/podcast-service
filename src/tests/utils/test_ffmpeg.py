import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from core import settings
from common.enums import EpisodeStatus
from modules.podcast.utils import post_processing_process_hook, module_logger as podcast_logger
from modules.providers.exceptions import FFMPegPreparationError, FFMPegParseError
from modules.providers.utils import ffmpeg_preparation, audio_metadata, AudioMetaData, module_logger as providers_logger
from tests.api.test_base import BaseTestCase


class TestFFMPEG(BaseTestCase):
    def setup_method(self):
        self.filename = "episode_123.mp3"
        self.src_path = os.path.join(settings.TMP_AUDIO_PATH, self.filename)
        with open(self.src_path, "wb") as f:
            f.write(b"data")

        self.tmp_filename = os.path.join(settings.TMP_AUDIO_PATH, f"tmp_{self.filename}")
        with open(self.tmp_filename, "wb") as f:
            f.write(b"data")

    def assert_hooks_calls(
        self, mocked_process_hook, expected_calls: list[dict] = None, finish_call: dict = None
    ):
        expected_calls = expected_calls or [
            dict(
                status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=0,
                logger=providers_logger
            ),
            finish_call,
        ]
        actual_process_hook_calls = [call.kwargs for call in mocked_process_hook.call_args_list]
        assert actual_process_hook_calls == expected_calls

    @patch("subprocess.run")
    @patch("modules.providers.utils.episode_process_hook")
    def test_episode_prepare__ok(self, mocked_process_hook, mocked_run, mocked_process):
        mocked_run.return_value = CompletedProcess([], returncode=0, stdout=b"Success")
        ffmpeg_preparation(self.src_path)
        tmp_file = Path(self.tmp_filename)
        self.assert_called_with(
            mocked_run,
            [
                "ffmpeg",
                "-y",
                "-i",
                self.src_path,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-q:a",
                "5",
                tmp_file,
            ],
            check=True,
            timeout=settings.FFMPEG_TIMEOUT,
        )
        mocked_process.target_class.__init__.assert_called_with(
            mocked_process.target_obj,
            target=post_processing_process_hook,
            kwargs={"filename": self.filename, "target_path": tmp_file, "total_bytes": 4},
        )

        assert not os.path.exists(self.tmp_filename), f"File wasn't removed: {self.tmp_filename}"
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(
                status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=len(b"data"),
                logger=providers_logger,
            ),
        )

    @patch("subprocess.run")
    @patch("modules.providers.utils.episode_process_hook")
    def test_episode_prepare__ffmpeg_error__fail(self, mocked_process_hook, mocked_run):
        mocked_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"FFMPEG oops")
        with pytest.raises(FFMPegPreparationError) as exc:
            ffmpeg_preparation(self.src_path)

        assert not os.path.exists(self.tmp_filename), f"File wasn't removed: {self.tmp_filename}"
        assert exc.value.details == (
            "FFMPEG failed with errors: " "Command 'ffmpeg' returned non-zero exit status 1."
        )
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(
                status=EpisodeStatus.ERROR, filename=self.filename, logger=providers_logger,
            ),
        )

    @patch("subprocess.run")
    @patch("modules.providers.utils.episode_process_hook")
    def test_episode_prepare__io_error__fail(self, mocked_process_hook, mocked_run):
        mocked_run.return_value = CompletedProcess([], returncode=0, stdout=b"Success")
        os.remove(self.tmp_filename)

        with pytest.raises(FFMPegPreparationError) as exc:
            ffmpeg_preparation(self.src_path)

        assert exc.value.details == (
            f"Failed to rename/remove tmp file: Prepared file {self.tmp_filename} wasn't created"
        )
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(
                status=EpisodeStatus.ERROR,
                filename=self.filename,
                logger=providers_logger,
            ),
        )

    @patch("time.sleep", lambda x: None)
    @patch("modules.podcast.utils.get_file_size")
    @patch("modules.podcast.utils.episode_process_hook")
    def test_post_processing_process_hook__ok(self, mocked_process_hook, mocked_file_size):
        mocked_file_size.return_value = 100
        # call single time
        post_processing_process_hook(self.filename, target_path=self.tmp_filename, total_bytes=100)
        self.assert_hooks_calls(
            mocked_process_hook,
            expected_calls=[
                dict(
                    status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
                    filename=self.filename,
                    total_bytes=100,
                    processed_bytes=100,
                    logger=podcast_logger,
                )
            ],
        )

    @patch("subprocess.run")
    def test_extract_metadata__ok(self, mocked_run):
        ffmpeg_stdout = """
Input #0, mp3, from '01.AudioTrack.mp3':
  Metadata:
    album           : Test Album
    artist          : Test Artist
    album_artist    : Test Album Artist
    track           : 01
    genre           : Audiobook
    title           : Title #1
    date            : 2022-06-02 12:30
    id3v2_priv.XMP  : <?xpacket begin="\xef\xbb\xbf" id="W5M0Mp<rdf
  Duration: 00:18:22.91, start: 0.000000, bitrate: 196 kb/s
  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 192 kb/s
  Stream #0:1: Video: mjpeg (Progressive), yuvj444p(pc, bt470bg/unknown/unknown), 1000x1000, 90k tbr
    Metadata:
      comment         : Cover (front)
Output #0, ffmetadata, to 't.txt':
  Metadata:
    album           : Test Album
    artist          : Test Artist
    album_artist    : Test Album Artist
    track           : 01
    genre           : Audiobook
    title           : Title #1
    date            : 2022-06-02 12:30
    id3v2_priv.XMP  : <?xpacket begin="\xef\xbb\xbf" <rdf
    encoder         : Lavf59.16.100
Stream mapping:
Press [q] to stop, [?] for help
size=       7kB time=-577014:32:22.77 bitrate=N/A speed=N/A
video:0kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: unknown
        """

        mocked_run.return_value = CompletedProcess([], 0, stdout=ffmpeg_stdout.encode("utf-8"))
        result = audio_metadata(self.src_path)

        assert isinstance(result, AudioMetaData)
        assert result.author == "Test Artist"
        assert result.title == "Title #1"
        assert result.track == "01"
        assert result.album == "Test Album"
        assert result.duration == 1102

    @patch("subprocess.run")
    def test_extract_metadata__missed_some_data__ok(self, mocked_run):
        ffmpeg_stdout = """
Input #0, mp3, from '01.AudioTrack.mp3':
  Metadata:
    title           : Title #1
  Duration: 00:18:22.91, start: 0.000000, bitrate: 196 kb/s
            """

        mocked_run.return_value = CompletedProcess([], 0, stdout=ffmpeg_stdout.encode("utf-8"))
        result = audio_metadata(self.src_path)

        assert isinstance(result, AudioMetaData)
        assert result.title == "Title #1"
        assert result.duration == 1102
        assert result.author is None
        assert result.track is None
        assert result.album is None

    @patch("subprocess.run")
    def test_extract_metadata__missed_metadata_at_all__ok(self, mocked_run):
        ffmpeg_stdout = """
Input #0, mp3, from '01.AudioTrack.mp3':
  Duration: 00:18:22.91, start: 0.000000, bitrate: 196 kb/s
            """

        mocked_run.return_value = CompletedProcess([], 0, stdout=ffmpeg_stdout.encode("utf-8"))
        result = audio_metadata(self.src_path)

        assert isinstance(result, AudioMetaData)
        assert result.duration == 1102
        assert result.title is None
        assert result.author is None
        assert result.track is None
        assert result.album is None

    @patch("subprocess.run")
    def test_extract_metadata__missed_all_data__fail(self, mocked_run):
        ffmpeg_stdout = """
Input #0, mp3, from '01.AudioTrack.mp3':
            """
        mocked_run.return_value = CompletedProcess([], 0, stdout=ffmpeg_stdout.encode("utf-8"))

        with pytest.raises(FFMPegParseError) as exc:
            audio_metadata(self.src_path)

        assert "Found result" in exc.value.details

    @patch("subprocess.run")
    def test_extract_metadata__ffmpeg_error__fail(self, mocked_run):
        mocked_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"FFMPEG oops")
        with pytest.raises(FFMPegPreparationError) as exc:
            audio_metadata(self.src_path)

        assert exc.value.details == (
            "FFMPEG failed with errors: " "Command 'ffmpeg' returned non-zero exit status 1."
        )

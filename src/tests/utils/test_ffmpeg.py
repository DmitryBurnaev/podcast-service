import os
import subprocess
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from core import settings
from modules.podcast.models import EpisodeStatus
from modules.podcast.utils import post_processing_process_hook
from modules.youtube.exceptions import FFMPegPreparationError
from modules.youtube.utils import ffmpeg_preparation
from tests.api.test_base import BaseTestCase


class TestFFMPEG(BaseTestCase):
    def setup_method(self):
        self.filename = "episode_123.mp3"
        self.src_path = os.path.join(settings.TMP_AUDIO_PATH, self.filename)
        with open(self.src_path, "wb") as file:
            file.write(b"data")

        self.tmp_filename = os.path.join(settings.TMP_AUDIO_PATH, f"tmp_{self.filename}")
        with open(self.tmp_filename, "wb") as file:
            file.write(b"data")

    def assert_hooks_calls(
        self, mocked_process_hook, expected_calls: list[dict] = None, finish_call: dict = None
    ):
        expected_calls = expected_calls or [
            dict(
                status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=0,
            ),
            finish_call,
        ]
        actual_process_hook_calls = [call.kwargs for call in mocked_process_hook.call_args_list]
        assert actual_process_hook_calls == expected_calls

    @patch("subprocess.run")
    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__ok(self, mocked_process_hook, mocked_run, mocked_process):
        mocked_run.return_value = CompletedProcess([], returncode=0, stdout=b"Success")
        ffmpeg_preparation(self.filename)
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
                self.tmp_filename,
            ],
            check=True,
            timeout=settings.FFMPEG_TIMEOUT,
        )
        mocked_process.target_class.__init__.assert_called_with(
            mocked_process.target_obj,
            target=post_processing_process_hook,
            kwargs={"filename": self.filename, "target_path": self.tmp_filename, "total_bytes": 4},
        )

        assert not os.path.exists(self.tmp_filename), f"File wasn't removed: {self.tmp_filename}"
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(
                status=EpisodeStatus.DL_EPISODE_POSTPROCESSING,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=len(b"data"),
            ),
        )

    @patch("subprocess.run")
    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__ffmpeg_error__fail(self, mocked_process_hook, mocked_run):
        mocked_run.side_effect = subprocess.CalledProcessError(1, [], stderr=b"FFMPEG oops")
        with pytest.raises(FFMPegPreparationError) as err:
            ffmpeg_preparation(self.filename)

        assert not os.path.exists(self.tmp_filename), f"File wasn't removed: {self.tmp_filename}"
        assert err.value.details == (
            "FFMPEG failed with errors: " "Command '[]' returned non-zero exit status 1."
        )
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(status=EpisodeStatus.ERROR, filename=self.filename),
        )

    @patch("subprocess.run")
    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__io_error__fail(self, mocked_process_hook, mocked_run):
        mocked_run.return_value = CompletedProcess([], returncode=0, stdout=b"Success")
        os.remove(self.tmp_filename)

        with pytest.raises(FFMPegPreparationError) as err:
            ffmpeg_preparation(self.filename)

        assert err.value.details == (
            f"Failed to rename/remove tmp file: Prepared file {self.tmp_filename} wasn't created"
        )
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(status=EpisodeStatus.ERROR, filename=self.filename),
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
                )
            ],
        )

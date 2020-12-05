import os
from unittest.mock import patch

import pytest

from core import settings
from modules.podcast.utils import EpisodeStatuses
from modules.youtube.exceptions import FFMPegPreparationError
from modules.youtube.utils import ffmpeg_preparation


class TestFFMPEG:

    def setup_method(self):
        self.filename = "episode_123.mp3"
        self.src_path = os.path.join(settings.TMP_AUDIO_PATH, self.filename)
        with open(self.src_path, "wb") as file:
            file.write(b"data")

        self.tmp_filename = os.path.join(settings.TMP_AUDIO_PATH, f"tmp_{self.filename}")
        with open(self.tmp_filename, "wb") as file:
            file.write(b"data")

    def assert_hooks_calls(self, mocked_process_hook, finish_call: dict):
        expected_process_hook_calls = [
            dict(
                status=EpisodeStatuses.episode_postprocessing,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=0,
            ),
            finish_call,
        ]
        actual_process_hook_calls = [call.kwargs for call in mocked_process_hook.call_args_list]
        assert actual_process_hook_calls == expected_process_hook_calls

    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__ok(self, mocked_process_hook, mocked_popen):
        mocked_popen.communicate.return_value = "Success", None
        ffmpeg_preparation(self.filename)

        mocked_popen.target_class.__init__.assert_called_with(
            mocked_popen.target_obj,
            ["ffmpeg", "-i", self.src_path, "-strict", "-2", "-y", self.tmp_filename]
        )

        assert not os.path.exists(self.tmp_filename), f"TMP file wasn't removed: {self.tmp_filename}"
        mocked_popen.communicate.assert_called_with(timeout=settings.FFMPEG_TIMEOUT)
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(
                status=EpisodeStatuses.episode_postprocessing,
                filename=self.filename,
                total_bytes=len(b"data"),
                processed_bytes=len(b"data"),
            )
        )

    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__ffmpeg_error__fail(self, mocked_process_hook, mocked_popen):
        mocked_popen.communicate.return_value = None, "FFMPEG oops"
        with pytest.raises(FFMPegPreparationError) as err:
            ffmpeg_preparation(self.filename)

        assert not os.path.exists(self.tmp_filename), f"TMP file wasn't removed: {self.tmp_filename}"
        assert err.value.details == f"FFMPEG failed with errors: FFMPEG oops"
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(status=EpisodeStatuses.error, filename=self.filename)
        )

    @patch("modules.youtube.utils.episode_process_hook")
    def test_episode_prepare__io_error__fail(self, mocked_process_hook, mocked_popen):
        os.remove(self.tmp_filename)

        mocked_popen.communicate.return_value = "OK", None
        with pytest.raises(FFMPegPreparationError) as err:
            ffmpeg_preparation(self.filename)

        msg = f"No such file or directory: '{self.tmp_filename}' -> '{self.src_path}'"
        assert err.value.details == f"Failed to rename/remove tmp file: [Errno 2] {msg}"
        self.assert_hooks_calls(
            mocked_process_hook,
            finish_call=dict(status=EpisodeStatuses.error, filename=self.filename)
        )

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from newsflow.pipeline import validate_video


class PipelineVideoValidationTests(unittest.TestCase):
    def _run_validation(self, width, height, expected_short=False):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "render.mp4"
            audio = Path(directory) / "voice.mp3"
            video.write_bytes(b"x" * 100_001)
            audio.write_bytes(b"audio")
            probe = {
                "format": {"duration": "30"},
                "streams": [
                    {"codec_type": "video", "width": width, "height": height},
                    {"codec_type": "audio"},
                ],
            }
            responses = [
                SimpleNamespace(stdout=json.dumps(probe)),
                SimpleNamespace(stdout="30"),
            ]
            with patch("newsflow.pipeline.shutil.which", return_value="/usr/bin/ffprobe"), \
                 patch("newsflow.pipeline.subprocess.run", side_effect=responses):
                validate_video(video, audio, expected_short=expected_short)

    def test_main_video_must_be_landscape(self):
        with self.assertRaisesRegex(RuntimeError, "أفقياً"):
            self._run_validation(1080, 1920, expected_short=False)

    def test_main_video_accepts_landscape(self):
        self._run_validation(1920, 1080, expected_short=False)

    def test_short_video_accepts_portrait(self):
        self._run_validation(1080, 1920, expected_short=True)


if __name__ == "__main__":
    unittest.main()

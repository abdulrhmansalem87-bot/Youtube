import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from newsflow.pipeline import make_video, validate_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe not installed")
class VideoRenderSmokeTests(unittest.TestCase):
    def test_landscape_and_vertical_renders_have_audio_and_expected_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.mp3"
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=4",
                    "-codec:a", "libmp3lame", "-q:a", "4", str(audio),
                ],
                check=True, capture_output=True,
            )
            story = {
                "title": "التضخم الأمريكي يضغط على الأسواق",
                "summary": "ارتفع التضخم الأساسي في الولايات المتحدة خلال أكتوبر.",
                "source": "Reuters",
            }
            for short, expected in ((False, (1920, 1080)), (True, (1080, 1920))):
                output = root / ("short.mp4" if short else "long.mp4")
                make_video("اختبار WealthRadar", audio, output, short=short, stories=[story])
                validate_video(output, audio, expected_short=short)
                probe = subprocess.run(
                    [
                        shutil.which("ffprobe"), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height", "-of", "json", str(output),
                    ],
                    check=True, capture_output=True, text=True,
                )
                streams = json.loads(probe.stdout)["streams"]
                video = next(item for item in streams if item["codec_type"] == "video")
                self.assertEqual((video["width"], video["height"]), expected)
                self.assertTrue(any(item["codec_type"] == "audio" for item in streams))


if __name__ == "__main__":
    unittest.main()

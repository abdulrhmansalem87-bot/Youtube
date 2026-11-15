import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from newsflow.pipeline import make_video, validate_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe not installed")
class VideoRenderSmokeTests(unittest.TestCase):
    def test_landscape_portrait_long_form_and_shorts_renders_have_audio(self):
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
            cases = (
                (False, False, (1920, 1080), "landscape.mp4"),
                (False, True, (1080, 1920), "portrait-long.mp4"),
                (True, True, (1080, 1920), "short.mp4"),
            )
            def render_fixture_broll(cards, durations, source_audio, destination, portrait=False):
                width, height = (1080, 1920) if portrait else (1920, 1080)
                subprocess.run(
                    [
                        shutil.which("ffmpeg"), "-y", "-f", "lavfi",
                        "-i", f"testsrc=size={width}x{height}:rate=30",
                        "-i", str(source_audio), "-t", "4", "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(destination),
                    ],
                    check=True, capture_output=True,
                )
                return destination

            with patch("newsflow.pipeline.render_broll_video", side_effect=render_fixture_broll):
                for short, portrait, expected, filename in cases:
                    with self.subTest(short=short, portrait=portrait):
                        output = root / filename
                        make_video(
                            "اختبار WealthRadar", audio, output,
                            short=short, portrait=portrait, stories=[story],
                        )
                        validate_video(
                            output, audio, expected_short=short,
                            expected_portrait=portrait,
                        )
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

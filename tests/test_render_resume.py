import tempfile
import unittest
from pathlib import Path

from newsflow.rendering import render_card_image, render_video_resumable


class ResumableRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "voice.mp3"
        self.audio.write_bytes(b"audio-placeholder")
        self.output = self.root / "long.mp4"
        self.cache = self.root / "cache"
        self.cards = [
            {"heading": "الخبر الأول", "title": "الدولار يرتفع إلى أعلى مستوى في تسعة عشر شهراً", "body": "تغيرت توقعات أسعار الفائدة بعد بيانات التضخم الأمريكية."},
            {"heading": "الخبر الثاني", "title": "الذهب يتراجع مع قوة الدولار", "body": "تراجع السعر الفوري مع ارتفاع تكلفة الفرصة البديلة لحيازة الذهب."},
            {"heading": "الخبر الثالث", "title": "النفط يهبط مع مخاوف زيادة المعروض", "body": "تتابع الأسواق بيانات المخزونات والإنتاج والتطورات الجيوسياسية."},
        ]
        self.durations = [2.0, 2.0, 2.0]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def fake_frame(card, path, width, height, index, total, short):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(card["title"], encoding="utf-8")

    @staticmethod
    def fake_validate(path, duration, width, height, ffprobe):
        return path.is_file() and path.stat().st_size > 0

    @staticmethod
    def fake_mux(segments, audio, output, ffmpeg):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final-video")

    def render(self, segment_renderer, muxer=None, cards=None):
        return render_video_resumable(
            cards or self.cards,
            self.durations,
            self.audio,
            self.output,
            1920,
            1080,
            self.cache,
            commit_sha="test-commit",
            frame_renderer=self.fake_frame,
            segment_renderer=segment_renderer,
            segment_validator=self.fake_validate,
            muxer=muxer or self.fake_mux,
        )

    def test_late_scene_failure_resumes_without_rebuilding_successful_scenes(self):
        calls = []
        fail_late = {"value": True}

        def render_segment(frame, output, duration, width, height, ffmpeg):
            calls.append(output.name)
            if output.name == "segment-002.mp4" and fail_late["value"]:
                raise RuntimeError("simulated late scene failure")
            output.write_bytes(b"segment-" + output.name.encode())

        with self.assertRaisesRegex(RuntimeError, "simulated late"):
            self.render(render_segment)
        self.assertEqual(calls, ["segment-000.mp4", "segment-001.mp4", "segment-002.mp4"])
        self.assertTrue((self.cache / "segments" / "segment-000.mp4").is_file())
        self.assertTrue((self.cache / "segments" / "segment-001.mp4").is_file())

        calls.clear()
        fail_late["value"] = False
        self.render(render_segment)
        self.assertEqual(calls, ["segment-002.mp4"])
        self.assertTrue(self.output.is_file())

    def test_changed_scene_content_invalidates_only_its_cached_segment(self):
        calls = []

        def render_segment(frame, output, duration, width, height, ffmpeg):
            calls.append(output.name)
            output.write_bytes(b"segment-" + output.name.encode())

        self.render(render_segment)
        calls.clear()
        changed = [dict(card) for card in self.cards]
        changed[1]["title"] = "عنوان جديد يغيّر بصمة المشهد ويجبر إعادة إنتاجه"
        self.render(render_segment, cards=changed)
        self.assertEqual(calls, ["segment-001.mp4"])

    def test_mux_failure_preserves_segments_for_retry(self):
        calls = []

        def render_segment(frame, output, duration, width, height, ffmpeg):
            calls.append(output.name)
            output.write_bytes(b"segment-" + output.name.encode())

        def failing_mux(segments, audio, output, ffmpeg):
            raise RuntimeError("simulated mux failure")

        with self.assertRaisesRegex(RuntimeError, "simulated mux"):
            self.render(render_segment, muxer=failing_mux)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all((self.cache / "segments" / f"segment-{i:03d}.mp4").is_file() for i in range(3)))

        calls.clear()
        self.render(render_segment)
        self.assertEqual(calls, [])
        self.assertTrue(self.output.is_file())

    def test_arabic_layout_fits_landscape_and_portrait_safe_regions(self):
        card = {
            "heading": "الخبر الأول، أسواق المال",
            "title": "الدولار يرتفع إلى أعلى مستوى في تسعة عشر شهراً مع ترقب قرارات الفائدة",
            "body": "تتابع الأسواق أثر بيانات التضخم الأمريكية على توقعات الفائدة والعملات والذهب، مع تحركات جديدة في عوائد السندات.",
        }
        for width, height in ((1920, 1080), (1080, 1920)):
            with self.subTest(size=(width, height)):
                output = self.root / f"preview-{width}x{height}.png"
                layout = render_card_image(card, output, width, height, 0, 3, short=(width < height))
                self.assertTrue(output.is_file())
                self.assertLess(layout["headline_region"][1], layout["body_region"][0])
                self.assertGreaterEqual(layout["headline_lines"], 1)
                self.assertLessEqual(layout["headline_lines"], 4)
                self.assertGreaterEqual(layout["body_lines"], 1)
                self.assertLessEqual(layout["body_lines"], 5)


if __name__ == "__main__":
    unittest.main()

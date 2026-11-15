import unittest
import tempfile
from unittest.mock import patch
from io import BytesIO
import urllib.error
from pathlib import Path
from PIL import Image, features

from newsflow.broll import MAX_SCENE_SECONDS, PEXELS_API, clean_visual_text, require_api_key, split_scene_durations, _english_query, _font_for_text, _overlay, _select_distinct_candidates, _download


class BrollPlanningTests(unittest.TestCase):
    def test_uses_current_official_pexels_video_search_endpoint(self):
        self.assertEqual(PEXELS_API, "https://api.pexels.com/v1/videos/search")

    def test_long_audio_is_split_into_short_moving_shots(self):
        plan = split_scene_durations([12.0, 7.0, 2.0])
        self.assertTrue(all(seconds <= MAX_SCENE_SECONDS for _, seconds in plan))
        self.assertEqual(sum(seconds for _, seconds in plan), 21.0)
        self.assertEqual([index for index, _ in plan].count(0), 5)
        self.assertEqual([index for index, _ in plan].count(1), 3)

    def test_scene_split_preserves_source_card_order(self):
        plan = split_scene_durations([5.0, 3.0])
        self.assertEqual([index for index, _ in plan], [0, 0, 1, 1])

    def test_long_fractional_scenes_do_not_accumulate_rounding_overflow(self):
        for duration in (182.38164302254532, 232.501, 317.5):
            with self.subTest(duration=duration):
                plan = split_scene_durations([duration])
                self.assertTrue(all(seconds <= MAX_SCENE_SECONDS for _, seconds in plan))
                self.assertAlmostEqual(sum(seconds for _, seconds in plan), duration, places=3)

    def test_invalid_scene_durations_are_rejected(self):
        for values in ([], [0], [-1], [float("nan")]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    split_scene_durations(values)

    def test_mixed_arabic_latin_caption_uses_font_with_latin_glyphs(self):
        self.assertTrue(_font_for_text("واشترك في WealthRadar", True).endswith("DejaVuSans-Bold.ttf"))

    def test_visual_text_removes_invisible_directional_and_control_marks(self):
        self.assertEqual(clean_visual_text("إنفيديا\u2066 80%\u2069"), "إنفيديا 80%")
        self.assertEqual(clean_visual_text("  خبر\u200f   مالي  "), "خبر مالي")

    def test_broll_queries_match_specific_story_subjects(self):
        self.assertEqual(_english_query({"title": "إنفيديا والذكاء الاصطناعي", "body": ""}),
                         "semiconductor chip manufacturing data center")
        self.assertEqual(_english_query({"title": "باينانس واختراق العملات المشفرة", "body": ""}),
                         "cryptocurrency cybersecurity bitcoin")
        self.assertEqual(_english_query({"title": "الاستحواذ على شركة بناء السفن ماير فيرفت", "body": ""}),
                         "shipbuilding shipyard industrial")

    @unittest.skipUnless(features.check("raqm"), "Arabic RAQM shaping is unavailable")
    def test_overlay_caption_changes_between_short_shots(self):
        card = {"captions": ["حركة الأسواق اليوم", "ما أثر الخبر على الأسعار؟", "راقب الأرقام قبل القرار"]}
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.png"
            second = Path(directory) / "second.png"
            _overlay(card, first, 1920, 1080, caption_index=0)
            _overlay(card, second, 1920, 1080, caption_index=1)
            self.assertNotEqual(first.read_bytes(), second.read_bytes())

    @unittest.skipUnless(features.check("raqm"), "Arabic RAQM shaping is unavailable")
    def test_caption_only_panel_is_compact_in_portrait_layout(self):
        card = {"captions": ["حركة الأسواق اليوم"]}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "portrait.png"
            _overlay(card, target, 1080, 1920)
            image = Image.open(target).convert("RGBA")
            # The old panel began at 68% of the image height; caption-only
            # overlays now start at 82% and leave more licensed footage visible.
            self.assertEqual(image.getpixel((540, 1500))[3], 0)
            self.assertGreater(image.getpixel((540, 1700))[3], 200)

    def test_broll_selects_a_distinct_pexels_source_for_each_scene(self):
        candidates = [
            {"id": 1, "url": "one"},
            {"id": 1, "url": "duplicate"},
            {"id": 2, "url": "two"},
            {"id": 3, "url": "three"},
        ]
        selected, used = _select_distinct_candidates(candidates, 3)
        self.assertEqual([item["id"] for item in selected], [1, 2, 3])
        self.assertEqual(len(used), 3)

    def test_broll_does_not_reuse_sources_from_previous_cards(self):
        candidates = [{"id": 1}, {"id": 2}, {"id": 3}]
        selected, used = _select_distinct_candidates(candidates, 2, {"1"})
        self.assertEqual([item["id"] for item in selected], [2, 3])
        self.assertEqual(used, {"1", "2", "3"})

    def test_broll_fails_closed_when_pexels_repeats_the_same_clip(self):
        with self.assertRaisesRegex(RuntimeError, "لقطات مختلفة"):
            _select_distinct_candidates([{"id": 1}, {"id": 1}], 2)

    def test_missing_pexels_key_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "PEXELS_API_KEY"):
            require_api_key("")

    def test_download_retries_transient_network_failure_and_caches_clip(self):
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        payload = b'x' * 25000
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'clip.mp4'
            cache = root / 'cache'
            with patch.dict('os.environ', {'NEWSFLOW_BROLL_CACHE_DIR': str(cache)}):
                with patch('newsflow.broll.urllib.request.urlopen', side_effect=[urllib.error.URLError('temporary'), Response(payload)]) as opened, patch('newsflow.broll.time.sleep'):
                    _download('https://cdn.example/clip.mp4', target)
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(target.read_bytes(), payload)
                target.unlink()
                with patch('newsflow.broll.urllib.request.urlopen') as opened:
                    _download('https://cdn.example/clip.mp4', target)
                    opened.assert_not_called()
                self.assertEqual(target.read_bytes(), payload)

    def test_download_rejects_tiny_or_empty_clip(self):
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict('os.environ', {'NEWSFLOW_BROLL_CACHE_DIR': str(root / 'cache')}):
                with patch('newsflow.broll.urllib.request.urlopen', side_effect=[Response(b'bad'), Response(b'bad'), Response(b'bad')]), patch('newsflow.broll.time.sleep'):
                    with self.assertRaisesRegex(RuntimeError, 'ثلاث محاولات'):
                        _download('https://cdn.example/bad.mp4', root / 'bad.mp4')


if __name__ == "__main__":
    unittest.main()

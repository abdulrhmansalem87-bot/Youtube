import unittest
import shutil
import subprocess
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
    def test_portrait_overlay_is_a_flush_gradient_band_with_clear_midscreen(self):
        card = {"captions": ["حركة الأسواق اليوم"], "headline": "عنوان عربي واضح للخبر", "key_number": "4.3%"}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "portrait.png"
            _overlay(card, target, 1080, 1920)
            image = Image.open(target).convert("RGBA")
            for y in (500, 800, 1000):
                self.assertEqual(image.getpixel((540, y))[3], 0)      # footage stays untouched mid-screen
            # Band is flush to the screen edges and darkest at the bottom.
            self.assertGreater(image.getpixel((0, 1910))[3], 200)
            self.assertGreater(image.getpixel((1079, 1910))[3], 200)
            self.assertLess(image.getpixel((20, 1150))[3], image.getpixel((20, 1450))[3])
            self.assertLessEqual(image.getpixel((20, 1150))[3], 120)   # soft fade, not a hard edge
            # Channel bug top-left is a solid gold plate; stat chip top-right stays translucent.
            self.assertEqual(image.getpixel((2, 110))[3], 255)
            self.assertEqual(image.getpixel((2, 110))[:3], (212, 175, 98))
            self.assertTrue(100 <= image.getpixel((1077, 110))[3] <= 200)

    @unittest.skipUnless(features.check("raqm"), "Arabic RAQM shaping is unavailable")
    def test_headline_strap_is_fixed_for_the_whole_story(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b, c = (Path(directory) / n for n in ("a.png", "b.png", "c.png"))
            ar = {"captions": ["نص", "نص", "نص"], "headline": "عنوان عربي واضح للخبر", "key_number": "+1.8%"}
            _overlay(ar, a, 1080, 1920, caption_index=0)
            _overlay(ar, b, 1080, 1920, caption_index=3)
            en = {"captions": ["نص", "نص"], "headline": "US economy grew faster than first estimated - NTD News"}
            _overlay(en, c, 1080, 1920, caption_index=0)
            ia, ib, ic = (Image.open(x).convert("RGBA") for x in (a, b, c))

            def band_top(image):
                return next(y for y in range(400, 1900) if image.getpixel((20, y))[3] > 20)
            self.assertEqual(band_top(ia), band_top(ib))  # strap stays put on every shot of the story
            self.assertLess(band_top(ia), band_top(ic))   # English headline is never drawn: no strap, shorter band
            strap_y = next(y for y in range(1000, 1900) if ia.getpixel((20, y))[:4] == (212, 175, 98, 255))
            self.assertEqual(ib.getpixel((20, strap_y))[:4], (212, 175, 98, 255))
            self.assertNotEqual(ic.getpixel((20, strap_y))[:4], (212, 175, 98, 255))
            for image in (ia, ib, ic):
                self.assertGreater(image.getpixel((540, 1900))[3], 200)  # same flush bottom every shot
            self.assertGreater(ia.getpixel((1077, 110))[3], 100)  # stat chip on the first shot
            self.assertEqual(ib.getpixel((1077, 110))[3], 0)      # and gone later

    def test_scene_pacing_targets_two_seconds_and_never_exceeds_two_and_a_half(self):
        from newsflow.broll import MIN_SCENE_SECONDS, TARGET_SCENE_SECONDS
        for total in (2.0, 2.6, 4.4, 7.0, 12.0, 19.7, 45.0):
            shots = [seconds for _, seconds in split_scene_durations([total])]
            self.assertAlmostEqual(sum(shots), total, places=3)
            self.assertLessEqual(max(shots), MAX_SCENE_SECONDS + 0.001)
            if total >= 4:
                self.assertGreaterEqual(min(shots), MIN_SCENE_SECONDS - 0.2, (total, shots))
                self.assertLessEqual(sum(shots) / len(shots), 2.5)
        shots = [seconds for _, seconds in split_scene_durations([10.0])]
        self.assertEqual(len(shots), 5)  # about 2 s per shot

    def test_every_shot_gets_a_different_gentle_motion(self):
        from newsflow.broll import MOTION_STYLES, shot_filter, shot_motion_filter
        self.assertGreaterEqual(len(set(MOTION_STYLES)), 5)
        chains = [shot_filter(i, 2.2, 1080, 1920) for i in range(8)]
        self.assertTrue(all("zoom" not in c or "scale=w=" in c for c in chains))
        self.assertGreaterEqual(len({shot_motion_filter(s, 1080, 1920, 2.2) for s in MOTION_STYLES}), 5)
        for chain in chains:
            self.assertIn("tpad=stop_mode=clone", chain)  # short clips are held, never short-changed
            self.assertTrue(chain.endswith("setsar=1,format=yuv420p"))
        self.assertIn("hflip", shot_filter(0, 2.2, 1080, 1920, round_index=1))
        with self.assertRaises(ValueError):
            shot_motion_filter("spin", 1080, 1920, 2.2)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is unavailable")
    def test_motion_chain_renders_concatenates_and_actually_moves(self):
        from newsflow.broll import shot_filter
        durations = [2.2, 2.0, 2.4, 2.2]
        with tempfile.TemporaryDirectory() as directory:
            src, out = Path(directory) / "src.mp4", Path(directory) / "out.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=640x360:rate=30:duration=3", "-pix_fmt", "yuv420p", str(src)], check=True)
            command, graph = ["ffmpeg", "-y", "-loglevel", "error"], []
            for i, seconds in enumerate(durations):
                command += ["-t", f"{seconds + 0.5:.3f}", "-i", str(src)]
                graph.append(f"[{i}:v]{shot_filter(i, seconds, 360, 640, i // 2)}[v{i}]")
            graph.append("".join(f"[v{i}]" for i in range(len(durations))) + f"concat=n={len(durations)}:v=1:a=0[o]")
            command += ["-filter_complex", ";".join(graph), "-map", "[o]", "-r", "30", "-pix_fmt", "yuv420p", str(out)]
            subprocess.run(command, check=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(out)], capture_output=True, text=True, check=True)
            self.assertAlmostEqual(float(probe.stdout), sum(durations), delta=0.15)

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


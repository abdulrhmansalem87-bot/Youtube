import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SHORT = ROOT / "bookflow" / "examples" / "sample_short.json"
LONG = ROOT / "bookflow" / "examples" / "sample_long.json"
sys.path.insert(0, str(ROOT))
from scripts.bookflow_validate import validate
from scripts.bookflow_render import beats_for_duration, make_frame, motif_kind, render

class BookFlowContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(SHORT.read_text(encoding="utf-8"))

    def test_short_sample_passes_cli(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bookflow_validate.py"), str(SHORT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[BOOKFLOW_VALID]", result.stdout)

    def test_episode_one_companion_short_passes(self):
        short = ROOT / "bookflow" / "episodes" / "episode-01-companion-short.json"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bookflow_validate.py"), str(short)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("duration=48s", result.stdout)

    def test_episode_one_plan_is_exactly_five_minutes(self):
        episode = ROOT / "bookflow" / "episodes" / "episode-01-psychology-of-money.json"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bookflow_validate.py"), str(episode)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("duration=300s", result.stdout)

    def test_five_minute_long_sample_passes(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bookflow_validate.py"), str(LONG)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("duration=300s", result.stdout)

    def test_audio_is_forbidden(self):
        self.plan["audio"] = {"enabled": True, "mode": "voiceover"}
        self.assertTrue(any("audio" in e for e in validate(self.plan)))

    def test_short_scene_count_is_enforced(self):
        self.plan["scenes"] = self.plan["scenes"][:5]
        self.plan["duration_seconds"] = 40
        self.assertTrue(any("requires 6-8 scenes" in e for e in validate(self.plan)))

    def test_hook_and_cta_are_required(self):
        self.plan["scenes"][0]["role"] = "intro"
        self.assertTrue(any("first scene role" in e for e in validate(self.plan)))
        self.plan["scenes"][0]["role"] = "hook"
        self.plan["scenes"][-1]["role"] = "ending"
        self.assertTrue(any("last scene role" in e for e in validate(self.plan)))

    def test_longer_than_five_minutes_is_required(self):
        plan = json.loads(LONG.read_text(encoding="utf-8"))
        plan["scenes"][0]["duration_seconds"] = 14
        plan["duration_seconds"] = 299
        self.assertTrue(any("at least 300 seconds" in e for e in validate(plan)))

    def test_direct_quotes_are_short_and_attributed(self):
        self.plan["scenes"][0]["direct_quote"] = "word " * 26
        self.assertTrue(any("exceeds 25 words" in e for e in validate(self.plan)))

    def test_book_reference_is_required(self):
        self.plan["book_reference"] = {"title": "Only a title"}
        self.assertTrue(any("book_reference" in e for e in validate(self.plan)))

    def test_visual_changes_stay_within_three_seconds(self):
        self.assertEqual(beats_for_duration(8), 3)
        self.assertEqual(beats_for_duration(15), 5)
        self.assertEqual(beats_for_duration(6), 2)

    def test_scene_language_selects_specific_visual_motifs(self):
        self.assertEqual(motif_kind("gas pump and janitor"), "worker")
        self.assertEqual(motif_kind("luxury mansion and finance executive"), "executive")
        self.assertEqual(motif_kind("hospital and library donation"), "hospital")
        self.assertEqual(motif_kind("home foreclosure document"), "foreclosure")
        self.assertEqual(motif_kind("calendar pages and coins accumulate"), "time")
        self.assertEqual(motif_kind("investment growth chart"), "growth")

    def test_three_beats_are_visually_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / f"beat-{i}.png" for i in range(3)]
            for i, path in enumerate(paths):
                make_frame(self.plan["scenes"][0], 0, 6, i, 540, 960, path)
            images = [Image.open(path).convert("RGB") for path in paths]
            self.assertTrue(all(image.size == (540, 960) for image in images))
            self.assertIsNotNone(ImageChops.difference(images[0], images[1]).getbbox())
            self.assertIsNotNone(ImageChops.difference(images[1], images[2]).getbbox())

    def test_renderer_is_isolated_and_silent(self):
        source = (ROOT / "scripts" / "bookflow_render.py").read_text(encoding="utf-8")
        self.assertNotIn("newsflow", source.lower())
        self.plan["audio"] = {"enabled": True, "mode": "voiceover"}
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "bad.json"
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            with self.assertRaises(ValueError):
                render(plan_path, Path(tmp) / "out.mp4", Path(tmp) / "cache")

if __name__ == "__main__":
    unittest.main()

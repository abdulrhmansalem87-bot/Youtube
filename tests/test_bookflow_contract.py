import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "bookflow" / "examples" / "sample_short.json"
sys.path.insert(0, str(ROOT))
from scripts.bookflow_validate import validate

class BookFlowContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(SAMPLE.read_text(encoding="utf-8"))

    def test_sample_plan_passes_cli(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bookflow_validate.py"), str(SAMPLE)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[BOOKFLOW_VALID]", result.stdout)

    def test_audio_is_forbidden(self):
        self.plan["audio"] = {"enabled": True, "mode": "voiceover"}
        self.assertTrue(any("audio" in e for e in validate(self.plan)))

    def test_short_scene_count_is_enforced(self):
        self.plan["scenes"] = self.plan["scenes"][:5]
        self.plan["duration_seconds"] = 40
        self.assertTrue(any("requires 6-8 scenes" in e for e in validate(self.plan)))

    def test_long_direct_quotes_are_rejected(self):
        self.plan["scenes"][0]["direct_quote"] = "word " * 26
        self.assertTrue(any("exceeds 25 words" in e for e in validate(self.plan)))

    def test_book_reference_is_required(self):
        self.plan["book_reference"] = {"title": "Only a title"}
        self.assertTrue(any("book_reference" in e for e in validate(self.plan)))

if __name__ == "__main__":
    unittest.main()

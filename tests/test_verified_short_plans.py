import json
import unittest
from pathlib import Path

from wealthradar_shorts.pipeline import load_plan, validate_plan

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "wealthradar" / "shorts-batch.verified-2026-11-13.json"


class VerifiedShortPlanTests(unittest.TestCase):
    def test_verified_manifest_has_two_distinct_short_plans(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        plans = data["plans"]
        self.assertEqual(len(plans), 2)
        self.assertEqual(len({item["id"] for item in plans}), 2)
        self.assertEqual(len({item["path"] for item in plans}), 2)

    def test_each_verified_short_passes_the_real_cli_validator(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in data["plans"]:
            with self.subTest(plan=item["id"]):
                plan = load_plan(ROOT / item["path"])
                self.assertEqual(validate_plan(plan), [])


if __name__ == "__main__":
    unittest.main()

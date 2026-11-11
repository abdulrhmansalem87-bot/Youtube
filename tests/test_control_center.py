import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ControlCenterTests(unittest.TestCase):
    def test_dashboard_module_compiles(self):
        source = Path("scripts/build_control_center.py")
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(source)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_batch_manifest_has_independent_plan_ids(self):
        import json
        data = json.loads(Path("wealthradar/shorts-batch.example.json").read_text(encoding="utf-8"))
        plans = data["plans"]
        self.assertTrue(plans)
        ids = [item["id"] for item in plans]
        self.assertEqual(len(ids), len(set(ids)))
        for item in plans:
            self.assertTrue(Path(item["path"]).is_file())


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_control_center.py"


class ControlCenterTests(unittest.TestCase):
    def test_dashboard_module_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_batch_manifest_has_unique_plan_ids_and_existing_paths(self):
        data = json.loads(
            (ROOT / "wealthradar" / "shorts-batch.example.json").read_text(encoding="utf-8")
        )
        plans = data["plans"]
        self.assertTrue(plans)
        ids = [item["id"] for item in plans]
        self.assertEqual(len(ids), len(set(ids)))
        for item in plans:
            self.assertTrue((ROOT / item["path"]).is_file())

    def test_dashboard_builds_html_and_summary_from_mocked_actions_data(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            env = {
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_TOKEN": "test-token-must-never-appear-in-output",
                "DASHBOARD_OUTPUT": str(temp / "dashboard"),
                "GITHUB_STEP_SUMMARY": str(temp / "summary.md"),
            }
            with patch.dict(os.environ, env):
                spec = importlib.util.spec_from_file_location(
                    "wealthradar_control_center_under_test", SCRIPT
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                payload = {
                    "workflow_runs": [
                        {
                            "id": 101,
                            "name": "NewsFlow pipeline",
                            "status": "completed",
                            "conclusion": "success",
                            "created_at": "2026-11-12T07:00:00Z",
                            "html_url": "https://github.com/owner/repo/actions/runs/101",
                        },
                        {
                            "id": 102,
                            "name": "WealthRadar Shorts Batch",
                            "status": "completed",
                            "conclusion": "failure",
                            "created_at": "2026-11-12T07:10:00Z",
                            "html_url": "https://github.com/owner/repo/actions/runs/102",
                        },
                        {
                            "id": 103,
                            "name": "Unrelated workflow",
                            "status": "completed",
                            "conclusion": "success",
                            "created_at": "2026-11-12T07:20:00Z",
                            "html_url": "https://github.com/owner/repo/actions/runs/103",
                        },
                    ]
                }

                def fake_api(path):
                    if path == "/repos/owner/repo/actions/runs?per_page=30":
                        return payload
                    if path.endswith("/runs/101/jobs?per_page=100"):
                        return {"jobs": [{"name": "build <script>alert(1)</script>", "conclusion": "success"}]}
                    if path.endswith("/runs/102/jobs?per_page=100"):
                        return {"jobs": [{"name": "short-b", "conclusion": "failure"}]}
                    raise AssertionError(f"Unexpected API request: {path}")

                module.api = fake_api
                module.main()

            html = (temp / "dashboard" / "index.html").read_text(encoding="utf-8")
            summary = (temp / "summary.md").read_text(encoding="utf-8")
            self.assertIn("NewsFlow pipeline", html)
            self.assertIn("WealthRadar Shorts Batch", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("test-token-must-never-appear-in-output", html)
            self.assertNotIn("Unrelated workflow", html)
            self.assertIn("| 1 | 1 | 0 | 0 |", summary)
            self.assertIn("Video ID", summary) if "Video ID" in summary else self.assertIn("لا يثبت النشر", summary)


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BATCH_WORKFLOW = ROOT / ".github" / "workflows" / "wealthradar-shorts-batch.yml"
DASHBOARD_WORKFLOW = ROOT / ".github" / "workflows" / "wealthradar-control-center.yml"
SMOKE_MANIFEST = ROOT / "wealthradar" / "shorts-batch.smoke.json"


class ShortsBatchWorkflowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = yaml.load(BATCH_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        cls.dashboard = yaml.load(DASHBOARD_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def prepare_script(self):
        steps = self.batch["jobs"]["prepare"]["steps"]
        step = next(item for item in steps if item.get("id") == "matrix")
        script = step["run"]
        lines = script.splitlines()
        if lines and lines[0].strip() == "python - <<'PY'":
            if lines[-1].strip() != "PY":
                raise AssertionError("Batch prepare heredoc is not properly closed.")
            script = "\n".join(lines[1:-1])
        return script

    def test_matrix_keeps_sibling_jobs_independent_and_artifacts_unique(self):
        produce = self.batch["jobs"]["produce"]
        strategy = produce["strategy"]
        self.assertEqual(strategy["fail-fast"], "false")
        self.assertEqual(strategy["max-parallel"], "3")

        steps = produce["steps"]
        record = next(item for item in steps if item.get("name") == "Write per-Short result record")
        artifact = next(item for item in steps if item.get("uses") == "actions/upload-artifact@v4")
        self.assertEqual(record.get("if"), "always()")
        self.assertIn("steps.validate.outcome", record["env"]["VALIDATION_OUTCOME"])
        self.assertIn("steps.render.outcome", record["env"]["RENDER_OUTCOME"])
        self.assertIn("steps.upload.outcome", record["env"]["UPLOAD_OUTCOME"])
        self.assertIn("result.json", record["run"])
        self.assertLess(steps.index(record), steps.index(artifact))
        self.assertEqual(artifact.get("if"), "always()")
        name = artifact["with"]["name"]
        self.assertIn("${{ matrix.id }}", name)
        self.assertIn("${{ github.run_number }}", name)
        self.assertIn("output/wealthradar/", artifact["with"]["path"])
        self.assertEqual(artifact["with"]["if-no-files-found"], "error")

        upload = next(item for item in steps if item.get("name") == "Upload this Short privately")
        self.assertIn("success()", upload["if"])
        self.assertIn("inputs.upload_private", upload["if"])
        self.assertIn("inputs.editorial_approved", upload["if"])
        self.assertIn("--upload-private", upload["run"])
        self.assertNotIn("public", upload["run"].lower())

    def test_prepare_step_emits_two_distinct_matrix_entries(self):
        output = None
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github_output"
            env = os.environ.copy()
            env["BATCH_PATH"] = "wealthradar/shorts-batch.smoke.json"
            env["GITHUB_OUTPUT"] = str(output)
            result = subprocess.run(
                [sys.executable, "-c", self.prepare_script()],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            line = output.read_text(encoding="utf-8").strip()
            self.assertTrue(line.startswith("value="), line)
            matrix = json.loads(line[len("value="):])
            plans = matrix["include"]
            self.assertEqual(len(plans), 2)
            self.assertEqual(len({item["id"] for item in plans}), 2)
            self.assertEqual(len({item["path"] for item in plans}), 2)

    def test_each_smoke_plan_passes_the_real_cli_validation(self):
        manifest = json.loads(SMOKE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["plans"]), 2)
        for item in manifest["plans"]:
            with self.subTest(plan=item["id"]):
                result = subprocess.run(
                    [
                        sys.executable, "-m", "wealthradar_shorts",
                        "--plan", item["path"], "--validate-only",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_prepare_rejects_duplicate_ids_and_path_traversal(self):
        script = self.prepare_script()
        cases = [
            {"plans": [
                {"id": "same", "path": "tests/fixtures/shorts/short-a.json"},
                {"id": "same", "path": "tests/fixtures/shorts/short-b.json"},
            ]},
            {"plans": [{"id": "escape", "path": "../outside.json"}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    manifest = Path(directory) / "bad.json"
                    output = Path(directory) / "github_output"
                    manifest.write_text(json.dumps(payload), encoding="utf-8")
                    env = os.environ.copy()
                    env["BATCH_PATH"] = str(manifest)
                    env["GITHUB_OUTPUT"] = str(output)
                    result = subprocess.run(
                        [sys.executable, "-c", script],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())

    def test_dashboard_artifact_is_required_and_retained(self):
        steps = self.dashboard["jobs"]["dashboard"]["steps"]
        build = next(item for item in steps if item.get("name") == "Build dashboard and GitHub run summary")
        self.assertNotIn("GITHUB_STEP_SUMMARY", build.get("env", {}))
        artifact = next(item for item in steps if item.get("uses") == "actions/upload-artifact@v4")
        self.assertEqual(artifact["with"]["path"], "control-center/")
        self.assertEqual(artifact["with"]["if-no-files-found"], "error")
        self.assertEqual(artifact["with"]["retention-days"], "14")
        self.assertIn("workflow_run", self.dashboard["on"])
        self.assertIn("schedule", self.dashboard["on"])


if __name__ == "__main__":
    unittest.main()

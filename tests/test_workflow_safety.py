import unittest
from pathlib import Path


class WorkflowSafetyTests(unittest.TestCase):
    def test_scheduled_runs_cannot_upload_and_privacy_defaults_private(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        approved_private_dispatch = "github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && 'true' || 'false'"
        self.assertEqual(workflow.count(approved_private_dispatch), 2)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow)
        self.assertIn('NEWSFLOW_UPLOAD_SINGLE_LONG: "true"', workflow)
        self.assertNotIn("github.event_name == 'schedule' && 'true'", workflow)
        pipeline = (Path(__file__).resolve().parents[1] / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn('if status != "private":', pipeline)
        self.assertIn('os.getenv("YOUTUBE_PRIVACY_STATUS", "private")', pipeline)
        self.assertNotIn('privacy_override=os.getenv("YOUTUBE_PRIVACY_STATUS", "public")', pipeline)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from newsflow.pipeline import resolve_upload_privacy


class WorkflowSafetyTests(unittest.TestCase):
    def test_youtube_upload_privacy_is_private_only(self):
        self.assertEqual(resolve_upload_privacy("private"), "private")
        with self.assertRaisesRegex(ValueError, "restricted to PRIVATE"):
            resolve_upload_privacy("unlisted")
        with self.assertRaisesRegex(ValueError, "restricted to PRIVATE"):
            resolve_upload_privacy("public")

    def test_scheduled_runs_cannot_upload_and_privacy_defaults_private(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        approved_private_dispatch = "github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && 'true' || 'false'"
        self.assertEqual(workflow.count(approved_private_dispatch), 2)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow)
        self.assertIn('NEWSFLOW_UPLOAD_SINGLE_LONG: "false"', workflow)
        self.assertNotIn("github.event_name == 'schedule' && 'true'", workflow)


if __name__ == "__main__":
    unittest.main()

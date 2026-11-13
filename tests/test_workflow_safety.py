import unittest
from pathlib import Path

from newsflow.pipeline import resolve_upload_privacy, verify_target_channel


class WorkflowSafetyTests(unittest.TestCase):
    def test_target_channel_must_match_wealthradar(self):
        class Request:
            def execute(self):
                return {"items": [{"id": "UC123", "snippet": {"title": "WealthRadar"}}]}
        class Channels:
            def list(self, **kwargs):
                self.kwargs = kwargs
                return Request()
        class Service:
            def __init__(self):
                self.channel_service = Channels()
            def channels(self):
                return self.channel_service

        service = Service()
        self.assertEqual(verify_target_channel(service), "UC123")
        self.assertEqual(service.channel_service.kwargs["mine"], True)

    def test_target_channel_mismatch_fails_closed(self):
        class Request:
            def execute(self):
                return {"items": [{"id": "UC999", "snippet": {"title": "Other Channel"}}]}
        class Service:
            def channels(self):
                return type("Channels", (), {"list": lambda self, **kwargs: Request()})()
        with self.assertRaisesRegex(RuntimeError, "تعذر تأكيد قناة WealthRadar"):
            verify_target_channel(Service())

    def test_channel_read_permission_failure_blocks_upload(self):
        class Request:
            def execute(self):
                raise RuntimeError("403 insufficientPermissions")
        class Service:
            def channels(self):
                return type("Channels", (), {"list": lambda self, **kwargs: Request()})()
        with self.assertRaisesRegex(RuntimeError, "لن يتم رفع أي فيديو"):
            verify_target_channel(Service())

    def test_youtube_upload_privacy_is_private_only(self):
        self.assertEqual(resolve_upload_privacy("private"), "private")
        with self.assertRaisesRegex(ValueError, "restricted to PRIVATE"):
            resolve_upload_privacy("unlisted")
        with self.assertRaisesRegex(ValueError, "restricted to PRIVATE"):
            resolve_upload_privacy("public")

    def test_newsflow_shorts_are_always_uploaded_private(self):
        pipeline = (Path(__file__).resolve().parents[1] / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn('privacy_override="private", credentials=auth_credentials', pipeline)
        self.assertNotIn('privacy_override=os.getenv("YOUTUBE_PRIVACY_STATUS", "public")', pipeline)

    def test_scheduled_runs_cannot_upload_and_privacy_defaults_private(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        editorial_approval = "NEWSFLOW_EDITORIAL_APPROVED: ${{ github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && 'true' || 'false' }}"
        visual_upload_approval = "YOUTUBE_UPLOAD_ENABLED: ${{ github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && inputs.visual_qa_approved && 'true' || 'false' }}"
        self.assertIn(editorial_approval, workflow)
        self.assertIn(visual_upload_approval, workflow)
        self.assertIn("visual_qa_approved:", workflow)
        self.assertIn("newsflow-pr-{0}", workflow)
        self.assertIn("newsflow-production", workflow)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow)
        self.assertIn('NEWSFLOW_UPLOAD_SINGLE_LONG: "false"', workflow)
        self.assertNotIn("github.event_name == 'schedule' && 'true'", workflow)


if __name__ == "__main__":
    unittest.main()

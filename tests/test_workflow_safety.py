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

    def test_scheduled_runs_render_and_stage_private_for_owner_review(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        editorial_approval = "NEWSFLOW_EDITORIAL_APPROVED: ${{ github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && 'true' || 'false' }}"
        visual_upload_approval = "YOUTUBE_UPLOAD_ENABLED: ${{ github.event_name == 'schedule' && 'true' || (github.event_name == 'workflow_dispatch' && inputs.private_test && inputs.editorial_approved && inputs.visual_qa_approved && 'true') || 'false' }}"
        self.assertIn(editorial_approval, workflow)
        self.assertIn(visual_upload_approval, workflow)
        self.assertIn("NEWSFLOW_PRIVATE_STAGING: ${{ github.event_name == 'schedule' && 'true' || 'false' }}", workflow)
        self.assertIn("visual_qa_approved:", workflow)
        self.assertIn("newsflow-pr-{0}", workflow)
        self.assertIn("newsflow-production", workflow)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow)
        self.assertIn('default: true', workflow)
        self.assertIn("python -m newsflow --dry-run", workflow)
        self.assertIn("python -m newsflow --private-test", workflow)
        self.assertIn("python -m newsflow --private-staging", workflow)
        self.assertIn('NEWSFLOW_UPLOAD_SINGLE_LONG: "false"', workflow)
        for cron in (
            '- cron: "0 13 * * *"', '- cron: "0 17 * * *"', '- cron: "0 20 * * *"',
            '- cron: "0 12 * * *"', '- cron: "0 16 * * *"', '- cron: "0 19 * * *"',
        ):
            self.assertIn(cron, workflow)
        self.assertIn("id: cairo_schedule", workflow)
        self.assertIn('python -m newsflow.schedule "$EVENT_SCHEDULE"', workflow)
        self.assertIn("steps.cairo_schedule.outputs.run == 'true'", workflow)
        self.assertIn("steps.cairo_schedule.outputs.lookback_hours", workflow)
        self.assertIn("NEWSFLOW_STRICT_FRESHNESS:", workflow)
        self.assertIn("FISH_AUDIO_API_KEY: ${{ secrets.FISH_AUDIO_API_KEY }}", workflow)
        self.assertIn("FISH_AUDIO_REFERENCE_ID: ${{ secrets.FISH_AUDIO_REFERENCE_ID }}", workflow)
        # Scheduled production is limited to PRIVATE owner-review staging.
        self.assertIn("github.event_name == 'schedule'", visual_upload_approval)
        pipeline = (Path(__file__).resolve().parents[1] / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn('privacy_override="private"', pipeline)
        self.assertIn('inputs.private_test', visual_upload_approval)
        self.assertIn('inputs.editorial_approved', visual_upload_approval)
        self.assertIn('inputs.visual_qa_approved', visual_upload_approval)

    def test_shorts_workflow_uses_the_proven_fish_audio_pipeline(self):
        import yaml

        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "wealthradar-shorts.yml"
        )
        workflow = yaml.load(
            workflow_path.read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        self.assertIn("workflow_dispatch", workflow["on"])
        self.assertNotIn("schedule", workflow["on"])
        steps = workflow["jobs"]["produce"]["steps"]
        render = next(
            step for step in steps
            if step.get("name") == "Render one Short with the cloned WealthRadar voice and upload privately"
        )
        self.assertEqual(render["run"], "python -m newsflow --private-staging --shorts-only --max-stories 1")
        self.assertEqual(render["env"]["FISH_AUDIO_MODEL"], "s2.1-pro-free")
        self.assertEqual(render["env"]["YOUTUBE_PRIVACY_STATUS"], "private")
        self.assertEqual(render["env"]["NEWSFLOW_PRIVATE_STAGING"], "true")
        self.assertEqual(render["env"]["YOUTUBE_UPLOAD_ENABLED"], "true")
        self.assertIn("secrets.FISH_AUDIO_API_KEY", render["env"]["FISH_AUDIO_API_KEY"])
        self.assertIn("secrets.FISH_AUDIO_REFERENCE_ID", render["env"]["FISH_AUDIO_REFERENCE_ID"])
        self.assertIn("shorts-only", render["run"])

    def test_newsflow_shorts_only_is_private_and_does_not_render_long_video(self):
        pipeline = (
            Path(__file__).resolve().parents[1]
            / "newsflow" / "pipeline.py"
        ).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--shorts-only"', pipeline)
        self.assertIn('if args.shorts_only and not args.private_staging:', pipeline)
        self.assertIn('if args.shorts_only:', pipeline)
        self.assertIn('privacy_override="private"', pipeline)
        self.assertIn('[SHORT_READY]', pipeline)



if __name__ == "__main__":
    unittest.main()

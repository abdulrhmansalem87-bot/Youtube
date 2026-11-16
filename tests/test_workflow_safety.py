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

    def test_scheduled_runs_upload_only_private_review_drafts(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("YOUTUBE_UPLOAD_ENABLED: ${{ (github.event_name == 'schedule'", workflow)
        self.assertIn("NEWSFLOW_PRIVATE_STAGING: ${{ (github.event_name == 'schedule'", workflow)
        self.assertIn("NEWSFLOW_EDITORIAL_APPROVED:", workflow)
        self.assertIn("visual_qa_approved:", workflow)
        self.assertIn("newsflow-pr-{0}", workflow)
        self.assertIn("newsflow-schedule", workflow)
        self.assertIn(
            "contains(github.event.head_commit.message, '[private-stage]') && 'newsflow-schedule'",
            workflow,
        )
        self.assertIn("newsflow-manual", workflow)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow)
        self.assertIn('default: true', workflow)
        self.assertIn("python -m newsflow --dry-run", workflow)
        self.assertIn("python -m newsflow --private-test", workflow)
        self.assertIn("python -m newsflow --private-staging", workflow)
        self.assertIn("[private-stage]", workflow)
        self.assertIn("github.event_name == 'schedule' && steps.cairo_schedule.outputs.run == 'true'", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
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
        self.assertIn("EVENT_SCHEDULE:", workflow)
        self.assertIn("Report Cairo schedule decision", workflow)
        self.assertIn("Restore recent scheduled story history", workflow)
        self.assertIn("Save recent scheduled story history", workflow)
        self.assertIn("Validate story history before cache save", workflow)
        self.assertIn("id: history_cache_validation", workflow)
        self.assertIn("steps.history_cache_validation.outcome == 'success'", workflow)
        self.assertIn("retention_days=30", workflow)
        self.assertIn("NEWSFLOW_DEDUPE_HISTORY_ENABLED:", workflow)
        self.assertIn("NEWSFLOW_RECORD_DRAFT_HISTORY:", workflow)
        self.assertIn("NEWSFLOW_HISTORY_FILE: output/history/used_stories.json", workflow)
        self.assertIn("wealthradar-story-history-${{ runner.os }}-v1-", workflow)
        self.assertIn("render and upload long + Shorts as PRIVATE owner-review drafts; never public automatically", workflow)
        self.assertIn("30-day history cache", workflow)
        self.assertIn("github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("cancel-in-progress:", workflow)
        self.assertIn(
            "if: always() && ((github.event_name == 'schedule' && steps.cairo_schedule.outputs.run == 'true')",
            workflow,
        )

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
        self.assertEqual(render["env"]["NEWSFLOW_FACT_CHECK_ENABLED"], "true")
        self.assertIn("secrets.OPENAI_API_KEY", render["env"]["OPENAI_API_KEY"])
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

    def test_workflows_use_current_node24_github_actions_releases(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for filename in ("newsflow.yml", "wealthradar-shorts.yml"):
            workflow = (root / filename).read_text(encoding="utf-8")
            self.assertIn("actions/checkout@v7.0.1", workflow)
            self.assertIn("actions/setup-python@v7.1.0", workflow)
            self.assertIn("actions/upload-artifact@v7.0.2", workflow)
            self.assertNotIn("actions/checkout@v4", workflow)
            self.assertNotIn("actions/setup-python@v5", workflow)
            self.assertNotIn("actions/upload-artifact@v4", workflow)
        main_workflow = (root / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("actions/cache/restore@v6.1.0", main_workflow)
        self.assertIn("actions/cache/save@v6.1.0", main_workflow)
        self.assertNotIn("actions/cache/restore@v4", main_workflow)
        self.assertNotIn("actions/cache/save@v4", main_workflow)


if __name__ == "__main__":
    unittest.main()

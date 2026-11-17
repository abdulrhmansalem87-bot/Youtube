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

    def test_fact_check_prefers_groq_tavily_when_both_secrets_are_configured(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn(
            "NEWSFLOW_FACT_CHECK_PROVIDER: ${{ vars.NEWSFLOW_FACT_CHECK_PROVIDER || (secrets.GROQ_API_KEY != '' && secrets.TAVILY_API_KEY != '' && 'groq_tavily') || 'openai' }}",
            workflow,
        )
    def test_scheduled_and_tagged_push_runs_are_validation_only(self):
        import yaml

        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "newsflow.yml"
        )
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["owner_approved"]["default"], "false")
        self.assertEqual(inputs["render_only"]["default"], "false")

        steps = workflow["jobs"]["build"]["steps"]
        run_step = next(item for item in steps if item.get("name") == "Run NewsFlow")
        env = run_step["env"]
        self.assertEqual(env["NEWSFLOW_PRIVATE_STAGING"], "false")
        self.assertIn("inputs.owner_approved", env["NEWSFLOW_OWNER_APPROVED"])
        self.assertIn("workflow_dispatch", env["NEWSFLOW_OWNER_APPROVED"])
        self.assertEqual(env["NEWSFLOW_EDITORIAL_APPROVED"], "false")
        self.assertNotIn("FISH_AUDIO_API_KEY", env)
        self.assertNotIn("FISH_AUDIO_REFERENCE_ID", env)

        for name in (
            "YOUTUBE_UPLOAD_ENABLED", "YOUTUBE_CLIENT_ID",
            "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
        ):
            with self.subTest(environment=name):
                self.assertIn("workflow_dispatch", env[name])
                self.assertIn("inputs.owner_approved", env[name])
                self.assertIn("inputs.visual_qa_approved", env[name])
                self.assertNotIn("schedule", env[name])
                self.assertNotIn("[private-stage]", env[name])

        self.assertIn("inputs.owner_approved", env["PEXELS_API_KEY"])
        self.assertNotIn("schedule", env["PEXELS_API_KEY"])
        run = run_step["run"]
        self.assertIn("[SCHEDULED_VALIDATION_ONLY]", run)
        self.assertIn("python -m newsflow --dry-run", run)
        self.assertNotIn("python -m newsflow --private-staging", run)
        self.assertIn("python -m newsflow --render-only", run)
        self.assertIn("python -m newsflow --private-test", run)

        report = next(item for item in steps if item.get("name") == "Report Cairo schedule decision")
        self.assertIn("collect sources, run independent fact-check", report["run"])
        self.assertIn("never render or upload", report["run"])

        for step_name in (
            "Restore resumable scene cache",
            "Report restored scene cache",
            "Restore reusable licensed B-roll downloads",
            "Report B-roll cache",
            "Save reusable licensed B-roll downloads",
            "Save resumable scene cache",
            "Capture actual rendered video frames for phone QA",
        ):
            step = next(item for item in steps if item.get("name") == step_name)
            condition = step["if"]
            self.assertIn("workflow_dispatch", condition)
            self.assertIn("inputs.owner_approved", condition)
            self.assertNotIn("schedule", condition)
            self.assertNotIn("[private-stage]", condition)

        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', workflow_text)
        self.assertIn('id: cairo_schedule', workflow_text)
        self.assertIn('python -m newsflow.schedule "$EVENT_SCHEDULE"', workflow_text)
        self.assertIn("wealthradar-story-history-", workflow_text)

    def test_shorts_workflow_requires_owner_approval_and_disables_synthetic_voice(self):
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
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["owner_approved"]["default"], "false")
        self.assertEqual(inputs["visual_qa_approved"]["default"], "false")
        produce = workflow["jobs"]["produce"]
        self.assertIn("inputs.owner_approved", produce["if"])
        self.assertIn("inputs.visual_qa_approved", produce["if"])
        steps = produce["steps"]
        render = next(
            step for step in steps
            if step.get("name") == "Run one owner-approved PRIVATE Short"
        )
        self.assertEqual(render["run"], "python -m newsflow --private-staging --shorts-only --max-stories 1")
        self.assertEqual(render["env"]["NEWSFLOW_OWNER_APPROVED"], "true")
        self.assertEqual(render["env"]["NEWSFLOW_VISUAL_QA_APPROVED"], "true")
        self.assertEqual(render["env"]["YOUTUBE_PRIVACY_STATUS"], "private")
        self.assertEqual(render["env"]["YOUTUBE_UPLOAD_ENABLED"], "true")
        self.assertNotIn("FISH_AUDIO_API_KEY", render["env"])
        self.assertNotIn("FISH_AUDIO_REFERENCE_ID", render["env"])

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

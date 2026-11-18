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
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        steps = workflow["jobs"]["build"]["steps"]
        run_step = next(item for item in steps if item.get("name") == "Run NewsFlow")
        env = run_step["env"]

        # Scheduled and tagged runs are validation-only; only an explicit manual
        # owner dispatch may render and upload PRIVATE review drafts.
        self.assertIn("workflow_dispatch", env["NEWSFLOW_PRIVATE_STAGING"])
        self.assertIn("inputs.private_test", env["NEWSFLOW_PRIVATE_STAGING"])
        self.assertNotIn("inputs.dry_run", env["NEWSFLOW_PRIVATE_STAGING"])
        self.assertNotIn("dry_run", workflow["on"]["workflow_dispatch"]["inputs"])
        self.assertNotIn("visual_qa_approved", workflow["on"]["workflow_dispatch"]["inputs"])
        self.assertNotIn("schedule", env["NEWSFLOW_PRIVATE_STAGING"])
        self.assertNotIn("[private-stage]", env["NEWSFLOW_PRIVATE_STAGING"])
        self.assertEqual(env["YOUTUBE_PRIVACY_STATUS"], "private")
        self.assertIn("I am the channel owner", workflow["on"]["workflow_dispatch"]["inputs"]["private_test"]["description"])
        self.assertIn("main video + companion Shorts", workflow["on"]["workflow_dispatch"]["inputs"]["private_test"]["description"])

        # Media and YouTube credentials are exposed only to this manual private test.
        for name in (
            "YOUTUBE_UPLOAD_ENABLED", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
            "YOUTUBE_REFRESH_TOKEN", "FISH_AUDIO_API_KEY", "FISH_AUDIO_REFERENCE_ID",
            "PEXELS_API_KEY",
        ):
            with self.subTest(environment=name):
                self.assertIn("workflow_dispatch", env[name])
                self.assertIn("inputs.private_test", env[name])
                self.assertNotIn("inputs.dry_run", env[name])
                self.assertNotIn("visual_qa_approved", env[name])
                self.assertNotIn("schedule", env[name])
                self.assertNotIn("[private-stage]", env[name])

        for name in ("GROQ_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY"):
            self.assertIn("schedule", env[name])
            self.assertNotIn("[private-stage]", env[name])

        run = run_step["run"]
        self.assertIn("github.event_name", run)
        scheduled_branch = run.split("elif", 1)[0]
        self.assertIn("python -m newsflow --dry-run", scheduled_branch)
        self.assertNotIn("--private-staging", scheduled_branch)
        self.assertIn("python -m newsflow --private-staging", run)
        self.assertNotIn("python -m newsflow --private-test", run)
        self.assertIn('"${{ inputs.private_test }}" = "true"', run)
        self.assertNotIn("visual_qa_approved", run)
        self.assertNotIn("inputs.dry_run", run)

        report = next(item for item in steps if item.get("name") == "Report Cairo schedule decision")
        self.assertIn("collect sources, run independent fact-check", report["run"])
        self.assertIn("never render or upload", report["run"])

        for step_name in (
            "Restore reusable licensed B-roll downloads",
            "Report B-roll cache",
            "Save reusable licensed B-roll downloads",
            "Capture actual rendered video frames for phone QA",
        ):
            step = next(item for item in steps if item.get("name") == step_name)
            condition = step["if"]
            self.assertIn("workflow_dispatch", condition)
            self.assertIn("inputs.private_test", condition)
            self.assertNotIn("visual_qa_approved", condition)
            self.assertNotIn("schedule", condition)
            self.assertNotIn("[private-stage]", condition)

        self.assertIn("id: cairo_schedule", workflow_path.read_text(encoding="utf-8"))
        self.assertIn('NEWSFLOW_UPLOAD_SINGLE_LONG: "false"', workflow_path.read_text(encoding="utf-8"))

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
        for filename in ("newsflow.yml", "wealthradar-shorts.yml", "quality.yml"):
            workflow = (root / filename).read_text(encoding="utf-8")
            self.assertIn("actions/checkout@v7.0.1", workflow)
            self.assertIn("actions/setup-python@v7.1.0", workflow)
            self.assertNotIn("actions/checkout@v4", workflow)
            self.assertNotIn("actions/setup-python@v5", workflow)
            if filename != "quality.yml":
                self.assertIn("actions/upload-artifact@v7.0.2", workflow)
                self.assertNotIn("actions/upload-artifact@v4", workflow)
        main_workflow = (root / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("actions/cache/restore@v6.1.0", main_workflow)
        self.assertIn("actions/cache/save@v6.1.0", main_workflow)
        self.assertNotIn("actions/cache/restore@v4", main_workflow)
        self.assertNotIn("actions/cache/save@v4", main_workflow)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MobileRenderContractTests(unittest.TestCase):
    def test_main_video_is_landscape_and_shorts_remain_vertical(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn(
            'main_portrait = os.getenv("NEWSFLOW_MAIN_VIDEO_PORTRAIT", "false").lower() == "true"',
            source,
        )
        self.assertIn(
            "make_video(video_title, audio, long_video, short=False, portrait=main_portrait, stories=bulletin_stories)",
            source,
        )
        self.assertIn(
            "validate_video(long_video, audio, expected_portrait=main_portrait)",
            source,
        )
        self.assertIn("validate_audio_duration", source)
        self.assertIn(
            "make_video(short_title, short_audio, short_video, short=True, stories=[story])",
            source,
        )
        self.assertIn(
            "validate_video(short_video, short_audio, expected_short=True)",
            source,
        )
        self.assertIn("NEWSFLOW_VISUAL_QA_APPROVED", source)

        workflow = (ROOT / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn('NEWSFLOW_MAIN_VIDEO_PORTRAIT: "false"', workflow)
        self.assertIn(
            "NEWSFLOW_MAX_STORIES: ${{ github.event_name == 'pull_request' && '1' || '4' }}",
            workflow,
        )
        self.assertIn("visual_qa_approved", workflow)
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("actions/cache/save@v4", workflow)
        preview = (ROOT / "scripts" / "render_mobile_preview.py").read_text(encoding="utf-8")
        self.assertIn("phone-comparison.png", preview)
        self.assertIn("for short in output/bulletin/shorts/short-*.mp4", workflow)
        self.assertIn('output/mobile-qa/$short_name', workflow)

    def test_mobile_renderer_branch_keeps_verified_private_upload_gate(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("upload_review_blockers(", source)
        self.assertIn("private_staging=args.private_staging", source)
        self.assertIn("if args.private_test and upload_blockers:", source)
        self.assertIn("if args.private_staging:", source)
        self.assertNotIn("الرفع التلقائي Private staging معطل", source)
        self.assertIn('privacy_override="private"', source)
        private_test = source.split("if args.private_test:", 2)[-1]
        self.assertIn("if upload_enabled:", private_test)
        self.assertIn('privacy_override="private"', private_test)


if __name__ == "__main__":
    unittest.main()

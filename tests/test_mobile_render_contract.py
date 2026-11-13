import unittest
from pathlib import Path

from newsflow.pipeline import make_opening_hook
from newsflow.rendering import _clean_visual_text

ROOT = Path(__file__).resolve().parents[1]


class MobileRenderContractTests(unittest.TestCase):
    def test_main_video_defaults_to_portrait_and_shorts_remain_vertical(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("main_portrait = os.getenv(\"NEWSFLOW_MAIN_VIDEO_PORTRAIT\", \"true\").lower() == \"true\"", source)
        self.assertIn("make_video(video_title, audio, long_video, short=False, portrait=main_portrait, stories=stories)", source)
        self.assertIn("validate_video(long_video, audio, expected_portrait=main_portrait)", source)
        self.assertIn("duration <= 180", source)
        self.assertIn("make_video(short_title, short_audio, short_video, short=True, stories=[story])", source)
        self.assertIn("validate_video(short_video, short_audio, expected_short=True)", source)
        self.assertIn("NEWSFLOW_VISUAL_QA_APPROVED", source)
        workflow = (ROOT / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("visual_qa_approved", workflow)
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("actions/cache/save@v4", workflow)
        self.assertIn("phone-comparison.png", (ROOT / "scripts" / "render_mobile_preview.py").read_text(encoding="utf-8"))
        self.assertIn("for short in output/bulletin/shorts/short-*.mp4", workflow)
        self.assertIn("NEWSFLOW_REQUIRE_EDITORIAL_PACKAGE", workflow)

    def test_opening_hook_fits_phone_card_and_ellipsis_has_no_missing_glyph(self):
        hook = make_opening_hook([{
            "title": "غولدمان ساكس يحذر من مخاطر هبوط أسعار النحاس عن توقعاته لعام 2027",
        }])
        self.assertLessEqual(len(hook), 88)
        self.assertNotIn("؟ ولماذا يهمك الخبر", hook)
        self.assertNotIn("…", hook)
        self.assertIn("...", _clean_visual_text("عنوان طويل…"))

    def test_production_requires_curated_daily_package(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("NEWSFLOW_REQUIRE_EDITORIAL_PACKAGE", source)
        self.assertIn("NEWSFLOW_EDITORIAL_PACKAGE", workflow)
        self.assertIn("content/$TODAY/wealthradar-daily-package.json", workflow)

    def test_mobile_renderer_branch_keeps_verified_private_upload_gate(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("upload_review_blockers(editorial_report, editorial_approved)", source)
        self.assertIn('os.getenv("YOUTUBE_PRIVACY_STATUS", "private")', source)
        private_test = source.split("if args.private_test:", 2)[-1]
        self.assertIn("if upload_enabled:", private_test)
        self.assertIn('privacy_override="private"', private_test)


if __name__ == "__main__":
    unittest.main()

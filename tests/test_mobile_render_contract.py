import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MobileRenderContractTests(unittest.TestCase):
    def test_main_video_is_landscape_and_shorts_remain_vertical(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("make_video(video_title, audio, long_video, short=False, portrait=False, stories=stories)", source)
        self.assertIn("validate_video(long_video, audio, expected_portrait=False)", source)
        self.assertIn("make_video(short_title, short_audio, short_video, short=True, stories=[story])", source)
        self.assertIn("validate_video(short_video, short_audio, expected_short=True)", source)

    def test_mobile_renderer_branch_keeps_verified_private_upload_gate(self):
        source = (ROOT / "newsflow" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("upload_review_blockers(editorial_report, editorial_approved)", source)
        self.assertIn('os.getenv("YOUTUBE_PRIVACY_STATUS", "private")', source)
        private_test = source.split("if args.private_test:", 2)[-1]
        self.assertIn("if upload_enabled:", private_test)
        self.assertIn('privacy_override="private"', private_test)


if __name__ == "__main__":
    unittest.main()

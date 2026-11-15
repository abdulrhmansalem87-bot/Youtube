import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from newsflow.editorial import upload_review_blockers
from newsflow.pipeline import main


def valid_report():
    return {
        "status": "needs_human_review",
        "accepted_count": 2,
        "warning_count": 0,
        "warnings": [],
        "fact_checking": "verified",
        "voice_source": "owner_recording",
        "presenter_source": "owner_video",
        "broll_source": "licensed_video",
    }


class UploadReviewGateTests(unittest.TestCase):
    def test_allows_upload_only_after_verified_review_and_approval(self):
        self.assertEqual(upload_review_blockers(valid_report(), True), [])

    def test_blocks_tts_missing_presenter_and_missing_licensed_broll(self):
        cases = [
            ("voice_source", "tts", "التعليق الصوتي ليس تسجيلاً أصلياً لصاحب القناة"),
            ("presenter_source", "none", "فيديو المقدم الأصلي غير مدمج في النسخة"),
            ("broll_source", "none", "لقطات B-roll مرخصة غير مدمجة في النسخة"),
        ]
        for field, value, expected in cases:
            with self.subTest(field=field):
                report = valid_report()
                report[field] = value
                self.assertIn(expected, upload_review_blockers(report, True))
                self.assertIn(expected, upload_review_blockers(report, False, private_staging=True))

    def test_newsflow_marks_current_tts_and_text_card_provenance(self):
        story = {
            "id": "test-story",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "link": "https://example.com/story",
            "published": "2026-11-15T10:00:00Z",
            "summary": "ملخص اقتصادي مكتمل يوضح أثر القرار على أسعار الفائدة والتمويل والأسواق.",
            "source": "مصدر اقتصادي",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                "NEWSFLOW_OUTPUT_DIR": directory,
                "NEWSFLOW_HISTORY_FILE": str(Path(directory) / "history.json"),
                "NEWSFLOW_DEDUPE_HISTORY_ENABLED": "false",
                "NEWSFLOW_RECORD_DRAFT_HISTORY": "false",
                "NEWSFLOW_PRIVATE_STAGING": "false",
                "YOUTUBE_UPLOAD_ENABLED": "false",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "false",
            }, clear=False):
                with patch.object(sys, "argv", ["newsflow", "--dry-run"]):
                    with patch("newsflow.pipeline.collect", return_value=([story], [])):
                        main()
            report = json.loads((Path(directory) / "editorial_review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["voice_source"], "tts")
            self.assertEqual(report["presenter_source"], "none")
            self.assertEqual(report["broll_source"], "none")
            blockers = upload_review_blockers(report, True, private_staging=True)
            self.assertTrue(any("تسجيلاً أصلياً" in item for item in blockers))
            self.assertTrue(any("المقدم الأصلي" in item for item in blockers))
            self.assertTrue(any("B-roll" in item for item in blockers))

    def test_blocks_when_fact_checking_was_not_performed_for_approved_upload(self):
        report = valid_report()
        report["fact_checking"] = "not_performed"
        self.assertIn(
            "التحقق المستقل من الوقائع لم يكتمل",
            upload_review_blockers(report, True),
        )

    def test_private_staging_does_not_bypass_independent_fact_checking(self):
        report = valid_report()
        report["fact_checking"] = "not_performed"
        self.assertIn(
            "التحقق المستقل من الوقائع لم يكتمل",
            upload_review_blockers(report, False, private_staging=True),
        )
        report["fact_checking"] = "verified"
        self.assertEqual(upload_review_blockers(report, False, private_staging=True), [])
        report["warning_count"] = 1
        report["warnings"] = [{"title": "خبر", "warnings": ["ملخص غير مكتمل"]}]
        self.assertIn("توجد تحذيرات تحريرية غير محسومة",
                      upload_review_blockers(report, False, private_staging=True))

    def test_private_staging_requires_upload_switch_before_oauth(self):
        with patch.dict(os.environ, {
            "YOUTUBE_UPLOAD_ENABLED": "false",
            "NEWSFLOW_PRIVATE_STAGING": "true",
        }, clear=False):
            with patch.object(sys, "argv", ["newsflow", "--private-staging"]):
                with patch("newsflow.pipeline.validate_youtube_auth") as auth:
                    with self.assertRaises(SystemExit) as raised:
                        main()
        self.assertEqual(raised.exception.code, 2)
        auth.assert_not_called()

    def test_cli_refuses_full_render_without_private_test(self):
        with patch.object(sys, "argv", ["newsflow"]):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)

    def test_private_test_requires_manual_editorial_and_visual_approval_before_oauth(self):
        cases = [
            {
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "true",
                "NEWSFLOW_PRIVATE_STAGING": "false",
            },
            {
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "true",
                "NEWSFLOW_VISUAL_QA_APPROVED": "false",
                "NEWSFLOW_PRIVATE_STAGING": "false",
            },
            {
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "true",
                "NEWSFLOW_VISUAL_QA_APPROVED": "true",
                "NEWSFLOW_PRIVATE_STAGING": "true",
            },
        ]
        for values in cases:
            with self.subTest(values=values):
                with patch.dict(os.environ, values, clear=False):
                    with patch.object(sys, "argv", ["newsflow", "--private-test"]):
                        with patch("newsflow.pipeline.validate_youtube_auth") as auth:
                            with self.assertRaises(SystemExit) as raised:
                                main()
                self.assertEqual(raised.exception.code, 2)
                auth.assert_not_called()

    def test_blocks_any_unresolved_editorial_warning(self):
        report = valid_report()
        report["warning_count"] = 1
        report["warnings"] = [{"title": "خبر", "warnings": ["ملخص مبتور"]}]
        self.assertIn(
            "توجد تحذيرات تحريرية غير محسومة",
            upload_review_blockers(report, True),
        )

    def test_blocks_missing_explicit_editorial_approval(self):
        self.assertIn(
            "المراجعة التحريرية لم تحصل على موافقة صريحة",
            upload_review_blockers(valid_report(), False),
        )

    def test_blocks_empty_or_invalid_review_report(self):
        report = valid_report()
        report["accepted_count"] = 0
        report["status"] = "blocked"
        blockers = upload_review_blockers(report, True)
        self.assertIn("لا توجد أخبار مقبولة", blockers)
        self.assertIn("تقرير المراجعة ليس في حالة قابلة للمراجعة", blockers)


if __name__ == "__main__":
    unittest.main()

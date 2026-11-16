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
        "status": "ready_for_production",
        "accepted_count": 2,
        "warning_count": 0,
        "warnings": [],
        "fact_checking": "verified",
        "voice_source": "owner_voice_clone",
        "presenter_source": "none",
        "broll_source": "licensed_video",
    }


class UploadReviewGateTests(unittest.TestCase):
    def test_allows_upload_after_automated_verification_without_human_approval(self):
        self.assertEqual(upload_review_blockers(valid_report(), False), [])

    def test_non_owner_voice_blocks_but_an_on_camera_presenter_is_optional(self):
        report = valid_report()
        report["voice_source"] = "generic_tts"
        self.assertTrue(
            any("مصدر التعليق الصوتي" in item for item in upload_review_blockers(report, True))
        )
        report["voice_source"] = "owner_voice_clone"
        report["presenter_source"] = "none"
        self.assertEqual(upload_review_blockers(report, True), [])

    def test_licensed_broll_is_checked_after_rendering(self):
        report = valid_report()
        report["broll_source"] = "none"
        self.assertNotIn(
            "لقطات B-roll مرخصة غير مدمجة في النسخة",
            upload_review_blockers(report, False, private_staging=True, require_broll=False),
        )
        self.assertIn(
            "لقطات B-roll مرخصة غير مدمجة في النسخة",
            upload_review_blockers(report, False, private_staging=True, require_broll=True),
        )

    def test_newsflow_marks_tts_and_pending_broll_provenance_before_render(self):
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
                "OPENAI_API_KEY": "",
            }, clear=False):
                with patch.object(sys, "argv", ["newsflow", "--dry-run"]):
                    with patch("newsflow.pipeline.collect", return_value=([story], [])), \
                         patch("newsflow.pipeline.collect_source_evidence", return_value=[{
                             "story_id": "test-story", "source_url": story["link"],
                             "status": "readable", "evidence_level": "article_text",
                             "article_text": "نص أصلي تجريبي" * 80, "extracted_chars": 1200,
                             "warnings": [],
                         }]):
                        main()
            report = json.loads((Path(directory) / "editorial_review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["voice_source"], "tts")
            self.assertEqual(report["presenter_source"], "none")
            self.assertEqual(report["broll_source"], "none")
            self.assertEqual(report["source_evidence_summary"]["readable"], 1)
            self.assertEqual(report["source_evidence"][0]["status"], "readable")
            self.assertFalse((Path(directory) / "test-story" / "script.txt").exists())
            self.assertFalse((Path(directory) / "bulletin" / "script.txt").exists())
            evidence_file = Path(directory) / "source-evidence" / "test-story.json"
            self.assertTrue(evidence_file.is_file())
            saved_evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_evidence["evidence_level"], "article_text")
            blockers = upload_review_blockers(report, True, private_staging=True)
            self.assertTrue(any("مصدر التعليق الصوتي" in item for item in blockers))
            self.assertFalse(any("المقدم الأصلي" in item for item in blockers))
            self.assertTrue(any("B-roll" in item for item in blockers))

    def test_blocks_when_fact_checking_was_not_performed_for_approved_upload(self):
        report = valid_report()
        report["fact_checking"] = "not_performed"
        self.assertIn(
            "التحقق المستقل من الوقائع لم يكتمل؛ أوقفنا إنتاج الصوت والفيديو",
            upload_review_blockers(report, True),
        )

    def test_private_staging_is_only_a_private_review_and_not_publication(self):
        report = valid_report()
        report["fact_checking"] = "not_performed"
        report["voice_source"] = "owner_voice_clone"
        report["presenter_source"] = "none"
        self.assertIn(
            "التحقق المستقل من الوقائع لم يكتمل؛ أوقفنا إنتاج الصوت والفيديو",
            upload_review_blockers(report, False, private_staging=True),
        )
        report["fact_checking"] = "verified"
        self.assertEqual(upload_review_blockers(report, False, private_staging=True), [])
        report["warning_count"] = 1
        report["warnings"] = [{"title": "خبر", "warnings": ["ملخص غير مكتمل"]}]
        self.assertIn(
            "توجد تحذيرات تحريرية غير محسومة",
            upload_review_blockers(report, False, private_staging=True),
        )
        report["warning_count"] = 0
        report["warnings"] = []
        report["accepted_count"] = 0
        self.assertIn(
            "لا توجد أخبار مقبولة",
            upload_review_blockers(report, False, private_staging=True),
        )

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

    def test_render_only_refuses_to_run_with_youtube_upload_enabled_before_oauth(self):
        with patch.dict(os.environ, {
            "PEXELS_API_KEY": "test-key",
            "YOUTUBE_UPLOAD_ENABLED": "true",
            "NEWSFLOW_PRIVATE_STAGING": "false",
        }, clear=False):
            with patch.object(sys, "argv", ["newsflow", "--render-only"]):
                with patch("newsflow.pipeline.validate_youtube_auth") as auth:
                    with self.assertRaises(SystemExit) as raised:
                        main()
        self.assertEqual(raised.exception.code, 2)
        auth.assert_not_called()

    def test_render_only_requires_pexels_before_collecting_stories(self):
        with patch.dict(os.environ, {
            "PEXELS_API_KEY": "",
            "YOUTUBE_UPLOAD_ENABLED": "false",
            "NEWSFLOW_PRIVATE_STAGING": "false",
        }, clear=False):
            with patch.object(sys, "argv", ["newsflow", "--render-only"]):
                with patch("newsflow.pipeline.collect") as collect:
                    with self.assertRaises(SystemExit) as raised:
                        main()
        self.assertEqual(raised.exception.code, 2)
        collect.assert_not_called()

    def test_cli_refuses_full_render_without_private_test(self):
        with patch.object(sys, "argv", ["newsflow"]):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)

    def test_private_test_requires_visual_qa_but_not_editorial_approval(self):
        invalid_cases = [
            {
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "false",
                "NEWSFLOW_PRIVATE_STAGING": "false",
            },
            {
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "true",
                "NEWSFLOW_PRIVATE_STAGING": "true",
            },
        ]
        for values in invalid_cases:
            with self.subTest(values=values):
                with patch.dict(os.environ, values, clear=False):
                    with patch.object(sys, "argv", ["newsflow", "--private-test"]):
                        with patch("newsflow.pipeline.validate_youtube_auth") as auth:
                            with self.assertRaises(SystemExit) as raised:
                                main()
                self.assertEqual(raised.exception.code, 2)
                auth.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            values = {
                "NEWSFLOW_OUTPUT_DIR": directory,
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "true",
                "NEWSFLOW_PRIVATE_STAGING": "false",
                "OPENAI_API_KEY": "",
            }
            with patch.dict(os.environ, values, clear=False):
                with patch.object(sys, "argv", ["newsflow", "--private-test"]):
                    with patch("newsflow.pipeline.collect", return_value=([], [])):
                        with patch("newsflow.pipeline.validate_youtube_auth") as auth:
                            main()
            auth.assert_not_called()

    def test_blocks_any_unresolved_editorial_warning(self):
        report = valid_report()
        report["warning_count"] = 1
        report["warnings"] = [{"title": "خبر", "warnings": ["ملخص مبتور"]}]
        self.assertIn(
            "توجد تحذيرات تحريرية غير محسومة",
            upload_review_blockers(report, True),
        )

    def test_human_editorial_approval_is_not_a_production_requirement(self):
        self.assertEqual(upload_review_blockers(valid_report(), False), [])

    def test_blocks_empty_or_invalid_review_report(self):
        report = valid_report()
        report["accepted_count"] = 0
        report["status"] = "blocked"
        blockers = upload_review_blockers(report, True)
        self.assertIn("لا توجد أخبار مقبولة", blockers)
        self.assertIn("تقرير التحقق الآلي ليس في حالة جاهزة للإنتاج", blockers)

    def test_private_staging_blocks_unverified_story_before_oauth_or_media_generation(self):
        story = {
            "id": "unverified-story",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "link": "https://example.com/story",
            "published": "2026-11-15T10:00:00Z",
            "summary": "ملخص اقتصادي مكتمل يوضح أثر القرار على أسعار الفائدة والتمويل والأسواق.",
            "source": "مصدر اقتصادي",
        }
        with tempfile.TemporaryDirectory() as directory:
            values = {
                "NEWSFLOW_OUTPUT_DIR": directory,
                "NEWSFLOW_HISTORY_FILE": str(Path(directory) / "history.json"),
                "NEWSFLOW_DEDUPE_HISTORY_ENABLED": "false",
                "NEWSFLOW_RECORD_DRAFT_HISTORY": "false",
                "NEWSFLOW_PRIVATE_STAGING": "true",
                "YOUTUBE_UPLOAD_ENABLED": "true",
                "NEWSFLOW_EDITORIAL_APPROVED": "false",
                "NEWSFLOW_VISUAL_QA_APPROVED": "false",
                "FISH_AUDIO_REFERENCE_ID": "owner-voice-reference",
                "OPENAI_API_KEY": "",
            }
            with patch.dict(os.environ, values, clear=False):
                with patch.object(sys, "argv", ["newsflow", "--private-staging"]):
                    with patch("newsflow.pipeline.collect", return_value=([story], [])), \
                         patch("newsflow.pipeline.collect_source_evidence", return_value=[{
                             "story_id": "unverified-story", "source_url": story["link"],
                             "status": "readable", "evidence_level": "article_text",
                             "article_text": "نص أصلي تجريبي" * 80, "extracted_chars": 1200,
                             "warnings": [],
                         }]), \
                         patch("newsflow.pipeline.validate_youtube_auth") as auth, \
                         patch("newsflow.pipeline.make_audio") as audio, \
                         patch("newsflow.pipeline.make_video") as video:
                        with self.assertRaisesRegex(RuntimeError, "before OAuth/audio/render"):
                            main()
            auth.assert_not_called()
            audio.assert_not_called()
            video.assert_not_called()
            report = json.loads(
                (Path(directory) / "editorial_review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["fact_checking"], "not_performed")


if __name__ == "__main__":
    unittest.main()

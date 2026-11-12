import unittest

from newsflow.editorial import upload_review_blockers


def verified_report():
    return {
        "status": "needs_human_review",
        "accepted_count": 2,
        "warning_count": 0,
        "warnings": [],
        "fact_checking": "verified",
    }


class UploadReviewGateTests(unittest.TestCase):
    def test_allows_upload_only_after_verified_review_and_approval(self):
        self.assertEqual(upload_review_blockers(verified_report(), True), [])

    def test_blocks_when_fact_checking_was_not_performed(self):
        report = verified_report()
        report["fact_checking"] = "not_performed"
        self.assertIn("التحقق المستقل من الوقائع لم يكتمل", upload_review_blockers(report, True))

    def test_blocks_any_unresolved_editorial_warning(self):
        report = verified_report()
        report["warning_count"] = 1
        report["warnings"] = [{"title": "خبر", "warnings": ["ملخص مبتور"]}]
        self.assertIn("توجد تحذيرات تحريرية غير محسومة", upload_review_blockers(report, True))

    def test_blocks_missing_explicit_editorial_approval(self):
        self.assertIn(
            "المراجعة التحريرية لم تحصل على موافقة صريحة",
            upload_review_blockers(verified_report(), False),
        )


if __name__ == "__main__":
    unittest.main()

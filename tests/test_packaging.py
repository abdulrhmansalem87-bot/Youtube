import os
import tempfile
import unittest
from unittest import mock

from newsflow import hook_rule
from newsflow.pipeline import upload_status_body
from newsflow.scriptwriter import validate_story_plan
from wealthradar_audit import hook, packaging


class HookRuleTests(unittest.TestCase):
    def test_result_first_passes(self):
        self.assertEqual(hook_rule.hook_problems("100 ألف جنيه في 2021 بتشتري النهارده بأقل من نص قيمتها", True), [])

    def test_greeting_and_intro_rejected(self):
        for line in ("أهلا بيكم في قناتنا، النهارده 55 في المية", "قبل ما نبدأ اشتركوا", "السلام عليكم 100 ألف"):
            self.assertTrue(hook_rule.hook_problems(line), line)

    def test_long_hook_and_missing_number_rejected(self):
        self.assertTrue(hook_rule.hook_problems(" ".join(["كلمة"] * 30)))
        self.assertTrue(hook_rule.hook_problems("الفلوس بتضيع من غير ما تحس", require_number=True))

    def test_script_writer_rejects_greeting_hook(self):
        story = {"title": "t", "summary": "الاقتصاد نما 4.3 في المئة في الربع الثالث"}
        plan = {"headline_ar": "نمو الاقتصاد الأمريكي في الربع الثالث", "narration_ar": "نما الاقتصاد الأمريكي بنسبة 4.3 في المئة في الربع الثالث.",
                "why_it_matters_ar": "هذا يؤثر على أسعار الفائدة والأسواق العالمية بشكل مباشر.",
                "short_hook_ar": "أهلا بيكم النهارده هنتكلم عن نمو الاقتصاد 4.3 في المئة",
                "short_body_ar": "نما الاقتصاد الأمريكي 4.3 في المئة في الربع الثالث بحسب البيانات."}
        self.assertIsNone(validate_story_plan(plan, story))
        plan["short_hook_ar"] = "4.3 في المئة، هذا هو نمو الاقتصاد الأمريكي في الربع الثالث."
        self.assertIsNotNone(validate_story_plan(plan, story))


class PackagingTests(unittest.TestCase):
    def test_title_checks(self):
        self.assertEqual(packaging.title_problems("100 ألف جنيه في 2021، بقوا كام دلوقتي؟"), [])
        self.assertTrue(packaging.title_problems("فلوس فلوس فلوس فلوس"))
        self.assertTrue(packaging.title_problems("ا" * 101))
        self.assertTrue(packaging.title_problems("عنوان", "#a #b #c #d"))

    def test_checklist_and_scorecard_carry_the_rules(self):
        text = packaging.launch_checklist({"question_ar": "سؤال"})
        for needle in ("average view duration", "Test & Compare", "containsSyntheticMedia", "Altered content", "PRIVATE"):
            self.assertIn(needle, text)
        header = packaging.scorecard_csv().strip().split(",")
        self.assertIn("avg_view_duration_s", header)
        self.assertIn("retention_at_30s_pct", header)

    def test_package_writes_checklist_and_scorecard(self):
        with tempfile.TemporaryDirectory() as d:
            hook.prepare_episode(d)
            self.assertTrue(os.path.isfile(os.path.join(d, "launch_checklist.md")))
            self.assertTrue(os.path.isfile(os.path.join(d, "scorecard.csv")))


class UploadDisclosureTests(unittest.TestCase):
    def test_synthetic_disclosure_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEWSFLOW_DECLARE_SYNTHETIC", None)
            body = upload_status_body("private")
        self.assertTrue(body["containsSyntheticMedia"])
        self.assertEqual(body["privacyStatus"], "private")
        self.assertIs(body["selfDeclaredMadeForKids"], False)

    def test_can_be_switched_off_explicitly(self):
        with mock.patch.dict(os.environ, {"NEWSFLOW_DECLARE_SYNTHETIC": "false"}):
            self.assertNotIn("containsSyntheticMedia", upload_status_body("private"))


if __name__ == "__main__":
    unittest.main()

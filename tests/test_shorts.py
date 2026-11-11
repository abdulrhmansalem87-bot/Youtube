import unittest

from newsflow.pipeline import make_script, make_short_script


class ShortScriptTests(unittest.TestCase):
    def test_short_is_story_specific_and_has_channel_branding(self):
        story = {
            "title": "البنك المركزي يثبت أسعار الفائدة",
            "summary": "قرر البنك تثبيت أسعار الفائدة مع استمرار متابعة التضخم وتطورات الأسواق.",
            "source": "وكالة الأنباء",
        }
        script = make_short_script(story)
        self.assertIn(story["title"], script)
        self.assertIn(story["summary"], script)
        self.assertIn("WealthRadar", script)
        self.assertIn("ليست توصية استثمارية", script)

    def test_main_script_uses_requested_channel_opening(self):
        script = make_script([{
            "title": "التضخم الأمريكي يضغط على الأسواق",
            "summary": "ارتفع التضخم الأساسي في الولايات المتحدة خلال أكتوبر.",
            "source": "Reuters",
        }])
        self.assertIn("أهلاً بكم في أهم الأخبار", script)

    def test_short_uses_safe_fallback_when_summary_missing(self):
        script = make_short_script({"title": "تطور اقتصادي جديد", "source": "المصدر"})
        self.assertIn("مراجعة المصدر الأصلي", script)
        self.assertIn("WealthRadar", script)


if __name__ == "__main__":
    unittest.main()

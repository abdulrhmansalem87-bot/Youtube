import unittest

from newsflow.pipeline import build_video_cards, make_script, make_short_script


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

    def test_video_cards_build_a_real_opening_hook_without_undefined_names(self):
        cards = build_video_cards([{
            "title": "النفط يرتفع مع مخاوف الشحن في هرمز",
            "summary": "ارتفعت الأسعار مع استمرار مخاطر الملاحة.",
            "source": "رويترز",
        }])
        self.assertIn("النفط يرتفع", cards[0][1])
        self.assertIn("WealthRadar", cards[-1][2])

    def test_long_script_uses_required_channel_opening_and_closing(self):
        script = make_script([{
            "title": "مؤشر الأسهم يرتفع",
            "summary": "صعد المؤشر مع تحسن التداولات.",
            "source": "رويترز",
        }])
        self.assertIn("أهلاً بكم في أهم الأخبار", script)
        self.assertIn("اشتركوا في WealthRadar", script)
        self.assertIn("تفعيل زر الجرس", script)

    def test_short_uses_safe_fallback_when_summary_missing(self):
        script = make_short_script({"title": "تطور اقتصادي جديد", "source": "المصدر"})
        self.assertIn("مراجعة المصدر الأصلي", script)
        self.assertIn("WealthRadar", script)


if __name__ == "__main__":
    unittest.main()

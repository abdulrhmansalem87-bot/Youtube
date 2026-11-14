import unittest

from newsflow.pipeline import (
    build_short_youtube_metadata, make_script, make_short_script,
)


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
        self.assertTrue(script.startswith("الخبر ده ممكن يفرق في فهمك لفلوسك:"))
        self.assertNotIn("أهلاً بكم", script)
        self.assertIn("WealthRadar", script)
        self.assertIn("مش توصية استثمارية", script)
        self.assertIn("اكتب رأيك", script)
        self.assertIn("ابعت الفيديو", script)
        self.assertIn("اشترك في WealthRadar", script)
        self.assertLessEqual(len(script), 620)

    def test_long_source_summary_is_compacted_for_short_duration(self):
        story = {
            "title": "البنك المركزي يثبت أسعار الفائدة",
            "summary": "قرر البنك تثبيت أسعار الفائدة مع استمرار متابعة التضخم وتطورات الأسواق. " * 12,
            "source": "وكالة الأنباء",
        }
        script = make_short_script(story)
        self.assertLessEqual(len(script), 620)
        self.assertIn("تابع المصدر والرقم الرسمي", script)

    def test_main_script_uses_requested_channel_opening(self):
        script = make_script([{
            "title": "التضخم الأمريكي يضغط على الأسواق",
            "summary": "ارتفع التضخم الأساسي في الولايات المتحدة خلال أكتوبر.",
            "source": "Reuters",
        }])
        self.assertTrue(script.startswith("أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar"))

    def test_short_rejects_incomplete_summary(self):
        with self.assertRaises(ValueError):
            make_short_script({"title": "تطور اقتصادي جديد", "summary": "ملخص قصير"})

    def test_short_metadata_has_exactly_four_required_hashtags_and_source(self):
        story = {
            "title": "الذهب يتراجع مع ارتفاع الدولار",
            "summary": "تراجع الذهب مع ارتفاع الدولار وتوقعات أسعار الفائدة الأمريكية.",
            "source": "Reuters",
            "link": "https://www.reuters.com/example",
        }
        title, description, tags = build_short_youtube_metadata(story, "نص الفيديو")
        hashtags = [part for part in description.split() if part.startswith("#")]
        self.assertIn("#shorts", hashtags)
        self.assertIn("#WealthRadar", hashtags)
        self.assertEqual(len(hashtags), 4)
        self.assertIn("1. Reuters:", description)
        self.assertIn("#الذهب", description)
        self.assertIn("بدعمك بنتطور سوا خطوة بخطوة", description)
        self.assertLessEqual(len(title), 100)
        self.assertIn("WealthRadar", title)


if __name__ == "__main__":
    unittest.main()

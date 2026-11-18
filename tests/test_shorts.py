import unittest

from newsflow.pipeline import (
    build_short_youtube_metadata, make_script, make_short_script,
)


class ShortScriptTests(unittest.TestCase):
    def test_short_is_story_specific_without_spoken_channel_branding(self):
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
        self.assertNotIn("WealthRadar", script)
        self.assertIn("مش توصية استثمارية", script)
        self.assertIn("اكتب رأيك", script)
        self.assertIn("ابعت الفيديو", script)
        self.assertNotIn("اشترك في", script)

    def test_main_script_uses_clear_arabic_opening_without_brand_name(self):
        script = make_script([{
            "title": "التضخم الأمريكي يضغط على الأسواق",
            "summary": "ارتفع التضخم الأساسي في الولايات المتحدة خلال أكتوبر.",
            "source": "Reuters",
        }])
        self.assertTrue(script.startswith("التضخم الأمريكي يضغط على الأسواق."))
        self.assertNotIn("WealthRadar", script)

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
        self.assertIn("نحرص على تقديم المعلومة بوضوح", description)
        self.assertNotIn("هفوة بسيطة في الصوت", description)
        self.assertLessEqual(len(title), 100)
        self.assertNotIn("WealthRadar", title)


if __name__ == "__main__":
    unittest.main()

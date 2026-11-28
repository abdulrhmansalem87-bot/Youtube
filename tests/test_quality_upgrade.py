import os
import unittest
from unittest.mock import patch

from newsflow.pipeline import (
    build_short_youtube_metadata,
    build_youtube_metadata,
    make_script,
    make_short_script,
    original_link,
    prepare_tts_text,
    topic_hashtags,
    validate_youtube_metadata,
)
from newsflow.scriptwriter import is_arabic_text, numbers_in, validate_story_plan

SOURCE = {
    "id": "gdp1",
    "title": "US economy grew faster than first estimated in third quarter",
    "summary": "GDP grew at a 4.3% annual rate in the third quarter, up from 3.8% in the first estimate, the Commerce Department said.",
    "source": "Reuters",
    "link": "https://news.google.com/rss/articles/abc",
    "source_url": "https://www.reuters.com/markets/us/gdp-q3/",
}
PLAN = {
    "headline_ar": "الاقتصاد الأمريكي ينمو أسرع من التقدير الأول",
    "key_number_ar": "4.3%",
    "narration_ar": "ارتفع الناتج المحلي الإجمالي الأمريكي بنسبة 4.3 في المئة في الربع الثالث، مقابل 3.8 في المئة في التقدير الأول.",
    "why_it_matters_ar": "قد يعني ذلك أن خفض أسعار الفائدة سيتأخر، وهذا يؤثر على تكلفة القروض.",
    "short_hook_ar": "4.3 في المئة، هذا هو نمو الاقتصاد الأمريكي في الربع الثالث.",
    "short_body_ar": "وكان التقدير الأول 3.8 في المئة فقط، بحسب وزارة التجارة الأمريكية، وهذا أقوى من توقعات كثيرين.",
    "hashtags": ["الناتج_المحلي", "الفائدة"],
}


class ScriptwriterTests(unittest.TestCase):
    def test_valid_plan_is_accepted(self):
        self.assertIsNotNone(validate_story_plan(dict(PLAN), SOURCE))

    def test_invented_number_drops_the_plan(self):
        bad = dict(PLAN, narration_ar=PLAN["narration_ar"] + " وسيصل إلى 7.9 في المئة العام القادم.")
        self.assertIsNone(validate_story_plan(bad, SOURCE))

    def test_english_text_in_plan_drops_the_plan(self):
        bad = dict(PLAN, headline_ar="US economy grows faster than expected today")
        self.assertIsNone(validate_story_plan(bad, SOURCE))

    def test_arabic_indic_digits_are_normalised(self):
        self.assertIn("4.3", numbers_in("٤٫٣ في المئة"))
        self.assertTrue(is_arabic_text("نمو الاقتصاد"))
        self.assertFalse(is_arabic_text("Economy grew"))


class PlannedOutputTests(unittest.TestCase):
    def setUp(self):
        self.story = dict(SOURCE, plan=validate_story_plan(dict(PLAN), SOURCE))

    def test_planned_script_has_numbers_and_viewer_line_without_filler(self):
        script = make_script([self.story, dict(self.story, id="x2")])
        self.assertIn("4.3 في المئة", script)
        self.assertIn("ماذا يعني هذا لك؟", script)
        self.assertNotIn("كيف نقرأ الصورة؟", script)
        self.assertEqual(script.count("روابط المصادر الأصلية"), 1)

    def test_short_opens_with_the_key_number(self):
        self.assertTrue(make_short_script(self.story).startswith("4.3"))

    def test_metadata_is_arabic_uses_original_link_and_topic_hashtags(self):
        title, description, tags = build_youtube_metadata([self.story], "")
        self.assertTrue(is_arabic_text(title, 0.8))
        self.assertIn("reuters.com/markets/us/gdp-q3", description)
        self.assertNotIn("news.google.com", description)
        self.assertNotIn("نسخة مراجعة", description)
        hashtags = description.splitlines()[-1].split()
        self.assertIn("#الناتج_المحلي", hashtags)
        self.assertTrue(validate_youtube_metadata(title, description))
        s_title, s_desc, _ = build_short_youtube_metadata(self.story, "")
        self.assertTrue(is_arabic_text(s_title.replace("| #Shorts", ""), 0.8))
        self.assertTrue(validate_youtube_metadata(s_title, s_desc, short=True))

    def test_english_title_never_becomes_the_video_title(self):
        title, _, _ = build_youtube_metadata([dict(SOURCE)], "")
        self.assertTrue(is_arabic_text(title, 0.8))

    def test_private_notice_is_opt_in(self):
        from newsflow.pipeline import add_private_review_notice
        description = "نص https://a.example/x\n\n#WealthRadar #أ #ب #ج"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEWSFLOW_PRIVATE_REVIEW_NOTICE", None)
            self.assertNotIn("نسخة مراجعة", add_private_review_notice(description))

    def test_helpers(self):
        self.assertEqual(original_link({"link": "https://news.google.com/x"}), "https://news.google.com/x")
        self.assertEqual(original_link(SOURCE), SOURCE["source_url"])
        self.assertEqual(topic_hashtags([{"title": "Gold and the dollar", "summary": ""}], 2), ["الذهب", "الدولار"])
        self.assertIn("في المئة", prepare_tts_text("نمو 4.3% اليوم"))


if __name__ == "__main__":
    unittest.main()

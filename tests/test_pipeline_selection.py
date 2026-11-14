import unittest

from newsflow.pipeline import clamp_max_stories, make_script, select_stories, source_display_name, validate_audio_duration


class PipelineSelectionTests(unittest.TestCase):
    def test_bulletin_is_capped_at_four_stories(self):
        self.assertEqual(clamp_max_stories(4), 4)
        self.assertEqual(clamp_max_stories(8), 4)
        self.assertEqual(clamp_max_stories(9), 4)
        self.assertEqual(clamp_max_stories(0), 1)

    def test_eight_candidates_select_only_four_relevant_stories(self):
        stories = []
        sources = ["CNBC", "BBC", "IMF"]
        for index in range(8):
            stories.append({
                "id": str(index),
                "title": f"التضخم والأسواق المالية الخبر رقم {index}",
                "summary": "تطور اقتصادي ومالي يؤثر على الأسواق والمستثمرين.",
                "source": sources[index % len(sources)],
                "category": "أسواق المال",
            })
        selected, rejected = select_stories(stories, 8)
        self.assertEqual(len(selected), 4)
        self.assertEqual([item["id"] for item in selected], ["0", "1", "2", "3"])
        self.assertEqual(rejected, [])

    def test_actual_egypt_gold_headline_deduplicates_other_local_gold_prices(self):
        stories = [
            {
                "id": "gold-egypt",
                "title": "ارتفاع سعر الذهب في مصر.. جنيه الذهب يسجل 49200 جنيهاً",
                "summary": "ارتفع سعر الذهب في مصر خلال التعاملات الصباحية.",
                "source": "CNBC عربية - أسواق المال",
                "category": "أسواق المال",
            },
            {
                "id": "gold-uae",
                "title": "سعر الذهب اليوم في الإمارات الأربعاء 11 نوفمبر 2026",
                "summary": "تحديث أسعار الذهب في الإمارات خلال تعاملات اليوم.",
                "source": "CNBC عربية - أسواق المال",
                "category": "أسواق المال",
            },
            {
                "id": "ports",
                "title": "أرباح موانئ أبوظبي ترتفع 64% في الربع الثالث",
                "summary": "أعلنت المجموعة نتائج مالية فصلية جديدة.",
                "source": "CNBC عربية - أخبار الشركات",
                "category": "شركات",
            },
        ]
        selected, rejected = select_stories(stories, 4)
        self.assertEqual([item["id"] for item in selected], ["gold-egypt", "ports"])
        self.assertEqual(rejected, [])

    def test_single_story_bulletin_contains_substantive_context_for_long_form_audio(self):
        script = make_script([{
            "title": "وكالة الطاقة: تسارع سحب النفط من احتياطي الطوارئ",
            "summary": "قالت الوكالة إن السحب من الاحتياطي مستمر حتى فبراير 2027.",
            "source": "الجزيرة",
        }])
        self.assertGreaterEqual(len(script.split()), 300)
        self.assertIn("التمييز بين التوقعات والتحقق الفعلي", script)
        self.assertIn("لا نبني قراراً مالياً على عنوان منفرد", script)

    def test_companion_episode_keeps_deeper_details_from_the_same_story(self):
        later_detail = "تفصيل جوهري من المصدر بعد الجزء المختصر"
        story = {
            "title": "تطور مالي محدد",
            "summary": "مقدمة الخبر. " + ("تفاصيل وتحليلات موثقة. " * 35) + later_detail,
            "source": "الجزيرة",
        }
        script = make_script([story])
        self.assertIn(later_detail, script)
        self.assertEqual(script.count("الخبر 1:"), 1)
        self.assertNotIn("الخبر 2:", script)
        self.assertGreaterEqual(len(script.split()), 300)

    def test_source_names_are_rendered_in_arabic(self):
        self.assertEqual(source_display_name("Al Jazeera"), "الجزيرة")
        self.assertEqual(
            source_display_name("CNBC عربية - أسواق المال"),
            "سي إن بي سي عربية - أسواق المال",
        )

    def test_daily_local_gold_price_updates_are_deduplicated(self):
        stories = [
            {
                "id": "gold-egypt",
                "title": "سعر الذهب اليوم في مصر يسجل ارتفاعاً",
                "summary": "تحديث يومي لأسعار الذهب في السوق المصرية.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "gold-uae",
                "title": "أسعار الذهب اليوم في الإمارات",
                "summary": "تحديث يومي لأسعار الذهب في السوق الإماراتية.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "gold-jordan",
                "title": "أسعار الذهب اليوم في الأردن",
                "summary": "تحديث يومي لأسعار الذهب في السوق الأردنية.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "oil-earnings",
                "title": "أرباح شركات النفط ترتفع خلال الربع الثالث",
                "summary": "نتائج مالية جديدة لشركات الطاقة.",
                "source": "Al Jazeera",
                "category": "اقتصاد",
            },
        ]
        selected, rejected = select_stories(stories, 4)
        self.assertEqual([item["id"] for item in selected], ["gold-egypt", "oil-earnings"])
        self.assertEqual(rejected, [])


class AudioDurationTests(unittest.TestCase):
    def test_main_episode_stays_within_four_to_eight_minutes(self):
        for duration in (240, 300, 360, 480):
            with self.subTest(duration=duration):
                self.assertEqual(validate_audio_duration(duration), float(duration))

    def test_private_smoke_test_may_be_short_but_never_over_five_minutes(self):
        for duration in (45, 150, 180, 210, 300):
            with self.subTest(duration=duration):
                self.assertEqual(validate_audio_duration(duration, private_test=True), float(duration))

    def test_rejects_main_bulletins_outside_target_duration(self):
        for duration in (0, -1, 45, 150, 180, 181, 239, 481, float("nan"), "not-a-duration"):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(RuntimeError, "مدة"):
                    validate_audio_duration(duration)

    def test_private_smoke_test_rejects_invalid_or_overlong_audio(self):
        for duration in (0, -1, 301, 480, float("nan"), "not-a-duration"):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(RuntimeError, "مدة"):
                    validate_audio_duration(duration, private_test=True)


if __name__ == "__main__":
    unittest.main()

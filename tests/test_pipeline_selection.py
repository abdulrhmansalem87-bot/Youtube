import unittest

from newsflow.pipeline import clamp_max_stories, select_stories, source_display_name, validate_audio_duration


class PipelineSelectionTests(unittest.TestCase):
    def test_bulletin_is_capped_at_eight_stories(self):
        self.assertEqual(clamp_max_stories(8), 8)
        self.assertEqual(clamp_max_stories(9), 8)
        self.assertEqual(clamp_max_stories(0), 1)

    def test_eight_relevant_stories_can_be_selected(self):
        stories = []
        sources = ["CNBC", "BBC", "IMF"]
        for index in range(8):
            stories.append({
                "id": str(index),
                "title": f"التضخم والأسواق المالية الخبر رقم {index}",
                "summary": "تطور اقتصادي ومالي مؤكد يؤثر على الأسواق والمستثمرين.",
                "source": sources[index % len(sources)],
                "category": "أسواق المال",
            })
        selected, rejected = select_stories(stories, 8)
        self.assertEqual(len(selected), 8)
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
    def test_duration_follows_content_without_fixed_window(self):
        for duration in (45, 150, 210, 300, 480):
            with self.subTest(duration=duration):
                self.assertEqual(validate_audio_duration(duration), float(duration))

    def test_rejects_only_invalid_or_nonpositive_durations(self):
        for duration in (0, -1, float("nan"), "not-a-duration"):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(RuntimeError, "مدة التعليق الصوتي غير صالحة"):
                    validate_audio_duration(duration)


if __name__ == "__main__":
    unittest.main()

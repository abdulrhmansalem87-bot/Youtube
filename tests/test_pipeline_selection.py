import unittest

from newsflow.pipeline import clamp_max_stories, select_stories


class PipelineSelectionTests(unittest.TestCase):
    def test_bulletin_is_capped_at_four_stories(self):
        self.assertEqual(clamp_max_stories(8), 4)
        self.assertEqual(clamp_max_stories(4), 4)
        self.assertEqual(clamp_max_stories(0), 1)

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


if __name__ == "__main__":
    unittest.main()

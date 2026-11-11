import unittest

from newsflow.editorial import review_stories


class EditorialReviewTests(unittest.TestCase):
    def test_accepts_financial_story(self):
        report = review_stories([{
            "id": "1",
            "title": "التضخم الأمريكي يضغط على الأسواق",
            "summary": "ارتفع مؤشر أسعار المستهلكين مع ترقب قرارات الفائدة والأسواق.",
            "link": "https://example.com/economy",
            "source": "مصدر اقتصادي",
            "category": "أسواق المال",
            "published": "2026-11-10",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 0)
        self.assertEqual(report["status"], "needs_human_review")

    def test_rejects_sports_story(self):
        report = review_stories([{
            "id": "2",
            "title": "ليفربول يفوز في مباراة مثيرة",
            "summary": "سجل الفريق هدف الفوز في الدقائق الأخيرة.",
            "link": "https://example.com/sport",
            "source": "مصدر رياضي",
            "category": "عام",
            "published": "2026-11-10",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertEqual(report["status"], "blocked")


    def test_rejects_generic_company_story_without_financial_angle(self):
        report = review_stories([{
            "id": "4",
            "title": "شركة تعلن مبادرة مجتمعية جديدة",
            "summary": "أطلقت الشركة مبادرة لدعم الأنشطة المجتمعية والتعليمية.",
            "link": "https://example.com/community",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-10",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_rejects_lifestyle_gold_metaphor(self):
        report = review_stories([{
            "id": "5",
            "title": '"ذهب الصحراء".. 5 فوائد مذهلة لزيت التين الشوكي',
            "summary": "يحتوي زيت بذور التين الشوكي على مضادات الأكسدة والأحماض الدهنية التي قد تساعد في ترطيب البشرة.",
            "link": "https://example.com/lifestyle",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_rejects_geopolitical_story_with_only_vague_economic_mention(self):
        report = review_stories([{
            "id": "6",
            "title": "تصريحات سياسية بشأن احتمال عملية عسكرية",
            "summary": "قال المسؤول إن الألم الاقتصادي يتزايد مع استمرار المفاوضات.",
            "link": "https://example.com/politics",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_accepts_gold_price_story(self):
        report = review_stories([{
            "id": "7",
            "title": "أسعار الذهب ترتفع في التعاملات الآسيوية",
            "summary": "صعدت أونصة الذهب مع تراجع الدولار.",
            "link": "https://example.com/gold",
            "source": "مصدر مالي",
            "category": "أسواق المال",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 1)

    def test_flags_short_summary_for_human_review(self):
        report = review_stories([{
            "id": "3",
            "title": "البنك المركزي يعلن قرار الفائدة",
            "summary": "قرار جديد للفائدة.",
            "link": "https://example.com/banks",
            "source": "مصدر مالي",
            "category": "اقتصاد",
            "published": "2026-11-10",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["warning_count"], 1)
        self.assertTrue(report["human_approval_required"])


if __name__ == "__main__":
    unittest.main()

import unittest

from newsflow.editorial import review_stories
from newsflow.pipeline import make_script, clean_narration


class EditorialReviewTests(unittest.TestCase):
    def test_clean_narration_removes_english_parenthetical_aliases(self):
        cleaned = clean_narration("سيمنز إنرجي (Siemens Energy) تعلن نتائجها، مع دعم من صندوق النقد (IMF).")
        self.assertNotIn("Siemens Energy", cleaned)
        self.assertIn("(IMF)", cleaned)

    def test_bulletin_uses_required_opening_and_closing(self):
        script = make_script([{
            "title": "أرباح الشركة ترتفع خلال الربع الثالث",
            "summary": "ارتفعت الأرباح والإيرادات مقارنة بالفترة نفسها من العام الماضي.",
            "source": "مصدر مالي",
        }])
        self.assertIn("أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar", script)
        self.assertTrue(script.endswith("ولا تنسوا الاشتراك في WealthRadar وتفعيل زر الجرس."))
        self.assertNotIn("إيه اللي حصل", script)

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

    def test_flags_truncated_rss_summary_for_human_review(self):
        for suffix in ("...", "…"):
            with self.subTest(suffix=suffix):
                report = review_stories([{
                    "id": "truncated",
                    "title": "أرباح الشركة ترتفع خلال الربع الثالث",
                    "summary": "أظهرت النتائج المالية ارتفاع الأرباح والإيرادات مقارنة بالفترة نفسها من العام الماضي" + suffix,
                    "link": "https://example.com/results",
                    "source": "مصدر مالي",
                    "category": "أسواق المال",
                    "published": "2026-11-11",
                }])
                self.assertEqual(report["accepted_count"], 1)
                self.assertEqual(report["warning_count"], 1)
                self.assertIn("مبتور", report["warnings"][0]["warnings"][0])
                self.assertTrue(report["human_approval_required"])


    def test_rejects_political_story_with_incidental_cost_reference(self):
        report = review_stories([{
            "id": "5",
            "title": "روبيو يتحدث عن مسار المفاوضات مع إيران",
            "summary": "تطرقت التغطية إلى تكلفة التصعيد والإنفاق العسكري.",
            "link": "https://example.com/politics",
            "source": "مصدر عام",
            "category": "اقتصاد وأسواق",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_rejects_defamation_lawsuit_with_large_dollar_amount_as_nonfinancial(self):
        report = review_stories([{
            "id": "defamation",
            "title": 'القضاء الفيدرالي يسمح بالمضي قدماً في دعوى تشهير رفعها ترامب ضد "بي بي سي" بقيمة 10 مليارات دولار',
            "summary": "المحكمة ترفض الجزء الآخر من الدعوى الذي زعم فيه انتهاك قانون في ولاية فلوريدا.",
            "link": "https://example.com/legal/defamation",
            "source": "BBC Arabic",
            "category": "اقتصاد وأسواق",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertIn("دعوى غير مالية", report["rejected"][0]["reasons"][0])

    def test_clean_narration_normalizes_ascii_quotes_and_persian_cheh(self):
        cleaned = clean_narration('شركة "إي إف چي" تعلن نتائجها')
        self.assertNotIn('"', cleaned)
        self.assertIn("إي إف جي", cleaned)
        self.assertNotIn("چ", cleaned)

    def test_rejects_political_commentary_with_incidental_market_reference(self):
        report = review_stories([{
            "id": "politics",
            "title": "صحافة روسية: هزيمة ترمب تنذر بصراع سياسي وأزمة اقتصادية",
            "summary": "تتناول مواقع روسية خسارة الجمهوريين السيطرة على الكونغرس، ومخاوف من اضطراب أسهم الذكاء الاصطناعي وأزمة مالية عالمية.",
            "link": "https://example.com/politics/trump-defeat",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_accepts_political_story_with_direct_financial_policy(self):
        report = review_stories([{
            "id": "budget",
            "title": "الكونغرس يقر ميزانية بقيمة تريليوني دولار",
            "summary": "يتضمن القرار تمويلاً عاماً وتعديلات على الإنفاق الحكومي.",
            "link": "https://example.com/politics/budget",
            "source": "مصدر عام",
            "category": "سياسة",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 0)


    def test_rejects_sports_story_with_incidental_market_reference(self):
        report = review_stories([{
            "id": "6",
            "title": "فان دايك يفتح الباب أمام الرحيل عن ليفربول",
            "summary": "يتحدث التقرير عن القيمة السوقية للنادي وتفاعل الجماهير.",
            "link": "https://example.com/football",
            "source": "مصدر رياضي",
            "category": "عام",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_accepts_financial_summary_from_explicit_market_category(self):
        report = review_stories([{
            "id": "7",
            "title": "شركة تعلن نتائجها الفصلية الجديدة",
            "summary": "ارتفعت الأرباح والإيرادات مقارنة بالفترة نفسها من العام الماضي.",
            "link": "https://example.com/results",
            "source": "مصدر مالي",
            "category": "أسواق المال",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 0)

    def test_rejects_figurative_gold_in_nonfinancial_title(self):
        report = review_stories([{
            "id": "8",
            "title": "ذهب الصحراء.. فوائد زيت التين الشوكي",
            "summary": "يتناول التقرير الاستخدامات التقليدية لزيت التين الشوكي.",
            "link": "https://example.com/lifestyle",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)


if __name__ == "__main__":
    unittest.main()

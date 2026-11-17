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
        self.assertTrue(script.startswith("أهلاً بكم. إليكم أهم الأخبار الاقتصادية والمالية"))
        self.assertNotIn("WealthRadar", script)
        self.assertNotIn("ولا تنسوا الاشتراك في WealthRadar", script)
        self.assertIn("تابعوا التحديثات القادمة", script)
        self.assertNotIn("إيه اللي حصل", script)
        self.assertIn("كيف نقرأ الصورة؟", script)
        self.assertEqual(script.count("روابط المصادر في وصف الفيديو"), 1)
        self.assertNotIn("تابعوا رابط المصدر في وصف الفيديو للتفاصيل", script)


    def test_rejects_power_grid_outage_without_financial_market_impact(self):
        report = review_stories([{
            "id": "energy-grid",
            "title": "لا كهرباء ولا ماء ولا تدفئة بعد استهداف شبكة الطاقة",
            "summary": "يعاني السكان من انقطاع الكهرباء والمياه والتدفئة بعد الضربات، وتعمل فرق الطوارئ على إصلاح الشبكة.",
            "link": "https://example.com/energy-grid",
            "source": "مصدر عام",
            "category": "عام",
            "published": "2026-11-13",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertIn("دون أثر مالي مباشر", report["rejected"][0]["reasons"][0])

    def test_accepts_energy_infrastructure_story_with_direct_price_impact(self):
        report = review_stories([{
            "id": "energy-prices",
            "title": "استهداف منشآت الطاقة يرفع أسعار النفط",
            "summary": "ارتفعت أسعار النفط وتكاليف الشحن والتأمين مع تزايد مخاطر الإمدادات.",
            "link": "https://example.com/energy-prices",
            "source": "مصدر اقتصادي",
            "category": "أسواق المال",
            "published": "2026-11-13",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 0)

    def test_rejects_security_story_that_uses_oil_without_market_impact(self):
        report = review_stories([{
            "id": "oil-smuggling-security",
            "title": "اتهامات بتهريب النفط تعيد الملفات الأمنية إلى الواجهة",
            "summary": "تتمتع المنطقة بحساسية أمنية خاصة وتشير تقارير إلى نفوذ جماعات مسلحة داخلها.",
            "link": "https://example.com/oil-security",
            "source": "مصدر إخباري",
            "category": "اقتصاد وأسواق",
            "published": "2026-11-14",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertIn("أمني أو جنائي", report["rejected"][0]["reasons"][0])

    def test_accepts_security_story_when_summary_proves_direct_oil_market_impact(self):
        report = review_stories([{
            "id": "oil-smuggling-market",
            "title": "اتهامات بتهريب النفط تثير مخاوف بشأن السوق",
            "summary": "تتعلق القضية بصادرات النفط والإيرادات الحكومية وتكاليف الشحن والتأمين في السوق.",
            "link": "https://example.com/oil-market",
            "source": "مصدر اقتصادي",
            "category": "اقتصاد وأسواق",
            "published": "2026-11-14",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 0)

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
        self.assertEqual(report["status"], "ready_for_fact_check")
        self.assertFalse(report["human_approval_required"])

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

    def test_accepts_short_rss_summary_for_original_source_extraction(self):
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
        self.assertEqual(report["rejected_count"], 0)
        self.assertEqual(report["status"], "ready_for_fact_check")
        self.assertFalse(report["human_approval_required"])

    def test_accepts_incomplete_summary_from_financial_category_for_source_recheck(self):
        report = review_stories([{
            "id": "financial-category-short",
            "title": "شركة تعلن نتائجها الفصلية",
            "summary": "خبر مختصر...",
            "link": "https://example.com/results",
            "source": "مصدر مالي",
            "category": "أسواق المال",
            "published": "2026-11-11",
        }])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["status"], "ready_for_fact_check")

    def test_accepts_truncated_rss_summary_pending_original_article_fact_check(self):
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
                self.assertEqual(report["rejected_count"], 0)
                self.assertEqual(report["status"], "ready_for_fact_check")
                self.assertFalse(report["human_approval_required"])

    def test_rejects_story_without_publication_date(self):
        report = review_stories([{
            "id": "undated",
            "title": "أرباح الشركة ترتفع خلال الربع الثالث",
            "summary": "أظهرت النتائج المالية ارتفاع الأرباح والإيرادات مقارنة بالفترة نفسها من العام الماضي.",
            "link": "https://example.com/results",
            "source": "مصدر مالي",
            "category": "أسواق المال",
            "published": "",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertIn("تاريخ النشر", report["rejected"][0]["reasons"][0])


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


    def test_accepts_influencer_technology_story_with_market_impact(self):
        report = review_stories([{
            "id": "ai-chips",
            "title": "Jensen Huang discusses AI chip demand",
            "summary": "Rising demand is driving investment, orders and data-center capacity.",
            "link": "https://example.com/ai-chips",
            "source": "Google News - Jensen Huang",
            "category": "شخصيات مؤثرة",
            "published": "2026-11-16",
        }])
        self.assertEqual(report["accepted_count"], 1)

    def test_rejects_influencer_personal_story_without_market_impact(self):
        report = review_stories([{
            "id": "personal",
            "title": "Elon Musk shares a personal announcement",
            "summary": "The post discusses a private celebration and family news.",
            "link": "https://example.com/personal",
            "source": "Google News - Elon Musk",
            "category": "شخصيات مؤثرة",
            "published": "2026-11-16",
        }])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)

    def test_rejects_technology_story_without_business_or_market_context(self):
        report = review_stories([{
            "id": "tech-hype",
            "title": "A new AI model is released",
            "summary": "The model introduces new features for casual users.",
            "link": "https://example.com/model",
            "source": "BBC News - Technology",
            "category": "تكنولوجيا",
            "published": "2026-11-16",
        }])
        self.assertEqual(report["accepted_count"], 0)


if __name__ == "__main__":
    unittest.main()

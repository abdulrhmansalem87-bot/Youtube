import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from newsflow.pipeline import clamp_max_stories, collect, make_script, select_stories, source_display_name, validate_audio_duration


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
                "link": "https://publisher.example/story-str(index)",
                "published": "2026-11-16",
                "title": f"التضخم والأسواق المالية الخبر رقم {index}",
                "summary": "تطور اقتصادي ومالي يؤثر على الأسواق والمستثمرين.",
                "source": sources[index % len(sources)],
                "category": "أسواق المال",
            })
        selected, rejected = select_stories(stories, 8)
        self.assertEqual(len(selected), 4)
        self.assertEqual([item["id"] for item in selected], ["0", "1", "2", "3"])
        self.assertEqual(rejected, [])

    def test_incomplete_rss_summary_is_kept_for_original_source_recovery(self):
        stories = [
            {
                "id": "incomplete",
                "title": "ارتفاع أسعار الفائدة في الأسواق",
                "link": "https://publisher.example/incomplete",
                "published": "2026-11-16",
                "summary": "ملخص قصير",
                "source": "CNBC",
                "category": "أسواق المال",
            },
            {
                "id": "complete",
                "title": "تطورات أسعار الفائدة في الأسواق المالية",
                "link": "https://publisher.example/complete",
                "published": "2026-11-16",
                "summary": "أعلنت الجهة تفاصيل جديدة بشأن أسعار الفائدة وتأثير القرار على التمويل والأسواق.",
                "source": "BBC",
                "category": "أسواق المال",
            },
        ]
        selected, rejected = select_stories(stories, 1)
        self.assertEqual([item["id"] for item in selected], ["incomplete"])
        self.assertEqual(rejected, [])

    def test_actual_egypt_gold_headline_deduplicates_other_local_gold_prices(self):
        stories = [
            {
                "id": "gold-egypt",
                "link": "https://publisher.example/gold-egypt",
                "published": "2026-11-16",
                "title": "ارتفاع سعر الذهب في مصر.. جنيه الذهب يسجل 49200 جنيهاً",
                "summary": "ارتفع سعر الذهب في مصر خلال التعاملات الصباحية.",
                "source": "CNBC عربية - أسواق المال",
                "category": "أسواق المال",
            },
            {
                "id": "gold-uae",
                "link": "https://publisher.example/gold-uae",
                "published": "2026-11-16",
                "title": "سعر الذهب اليوم في الإمارات الأربعاء 11 نوفمبر 2026",
                "summary": "تحديث أسعار الذهب في الإمارات خلال تعاملات اليوم.",
                "source": "CNBC عربية - أسواق المال",
                "category": "أسواق المال",
            },
            {
                "id": "ports",
                "link": "https://publisher.example/ports",
                "published": "2026-11-16",
                "title": "أرباح موانئ أبوظبي ترتفع 64% في الربع الثالث",
                "summary": "أعلنت المجموعة نتائج مالية فصلية جديدة مع تفاصيل عن الإيرادات والأرباح واتجاهات النشاط خلال الربع الثالث.",
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
                "link": "https://publisher.example/gold-egypt",
                "published": "2026-11-16",
                "title": "سعر الذهب اليوم في مصر يسجل ارتفاعاً",
                "summary": "تحديث يومي لأسعار الذهب في السوق المصرية خلال التعاملات مع توضيح حركة الأسعار.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "gold-uae",
                "link": "https://publisher.example/gold-uae",
                "published": "2026-11-16",
                "title": "أسعار الذهب اليوم في الإمارات",
                "summary": "تحديث يومي لأسعار الذهب في السوق الإماراتية خلال التعاملات مع توضيح حركة الأسعار.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "gold-jordan",
                "link": "https://publisher.example/gold-jordan",
                "published": "2026-11-16",
                "title": "أسعار الذهب اليوم في الأردن",
                "summary": "تحديث يومي لأسعار الذهب في السوق الأردنية خلال التعاملات مع توضيح حركة الأسعار.",
                "source": "CNBC عربية",
                "category": "أسواق المال",
            },
            {
                "id": "oil-earnings",
                "link": "https://publisher.example/oil-earnings",
                "published": "2026-11-16",
                "title": "أرباح شركات النفط ترتفع خلال الربع الثالث",
                "summary": "نتائج مالية جديدة لشركات الطاقة مع تفاصيل الإيرادات والأرباح والتغيرات في النشاط.",
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


class TrendPriorityTests(unittest.TestCase):
    def test_trend_matched_news_is_prioritized_without_promoting_trend_as_news(self):
        stories = [
            {
                "id": "ordinary", "link": "https://publisher.example/ordinary",
                "published": "2026-11-16", "published_ts": 200,
                "title": "تطورات أسعار الفائدة في الأسواق المالية",
                "summary": "تؤثر أسعار الفائدة على التمويل والاستثمار.",
                "source": "Publisher A", "category": "أسواق المال",
            },
            {
                "id": "trending", "link": "https://publisher.example/trending",
                "published": "2026-11-15", "published_ts": 100,
                "title": "Nvidia AI chips demand rises",
                "summary": "Chip orders and data-center investment increase.",
                "source": "Publisher B", "category": "شخصيات مؤثرة",
                "trend_score": 1.0,
            },
        ]
        selected, rejected = select_stories(stories, 1)
        self.assertEqual([item["id"] for item in selected], ["trending"])
        self.assertEqual(rejected, [])


class TrendCollectionIntegrationTests(unittest.TestCase):
    def test_google_trends_feed_is_signal_only_and_matches_news_story(self):
        now = datetime.now(timezone.utc)
        published = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        published_struct = now.utctimetuple()
        sources = [
            {"name": "Google Trends - Egypt", "url": "https://trends.example/rss", "category": "ترند مصر"},
            {"name": "Google News - Jensen Huang", "url": "https://news.example/rss", "category": "شخصيات مؤثرة"},
        ]
        trend_entry = {
            "title": "Nvidia AI chips",
            "link": "https://trends.example/search",
            "summary": "Trending query",
        }
        news_entry = {
            "title": "Nvidia AI chips demand rises",
            "link": "https://publisher.example/nvidia",
            "summary": "Rising chip orders are driving investment and data-center capacity.",
            "published": published,
            "published_parsed": published_struct,
        }

        def fake_parse(url):
            return SimpleNamespace(entries=[trend_entry] if "trends.example" in url else [news_entry])

        with patch("newsflow.pipeline.config", return_value={"sources": sources}), \
             patch("newsflow.pipeline.feedparser.parse", side_effect=fake_parse), \
             patch.dict("os.environ", {"NEWSFLOW_LOOKBACK_HOURS": "72", "NEWSFLOW_STRICT_FRESHNESS": "true"}):
            stories, rejected = collect(1)

        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["title"], news_entry["title"])
        self.assertEqual(stories[0]["trend_matches"][0]["query"], "Nvidia AI chips")
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()

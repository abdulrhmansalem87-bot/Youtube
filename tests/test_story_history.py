import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from newsflow.history import (
    canonical_story_link,
    filter_recent_repeats,
    load_story_history,
    record_story_history,
)


class StoryHistoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc)
        self.story = {
            "id": "story-1",
            "link": "https://example.com/news/1?utm_source=feed",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "summary": "قرار اقتصادي يغيّر توقعات أسعار الفائدة ويؤثر في تكلفة التمويل والاقتراض.",
            "source": "مصدر اقتصادي",
        }

    def test_canonical_link_removes_tracking_query(self):
        self.assertEqual(
            canonical_story_link("https://example.com/a?utm_source=x&ref=home&id=4#top"),
            "https://example.com/a?id=4",
        )

    def test_recent_story_is_rejected_by_same_canonical_link(self):
        history = [{
            **self.story,
            "link": "https://example.com/news/1?utm_medium=rss",
            "prepared_at": (self.now - timedelta(hours=2)).isoformat(),
        }]
        current = [{**self.story, "link": "https://example.com/news/1?utm_campaign=push"}]
        accepted, rejected = filter_recent_repeats(current, history, now=self.now)
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("خبر مكرر", rejected[0]["reasons"][0])

    def test_near_identical_arabic_headline_is_rejected(self):
        history = [{
            **self.story,
            "prepared_at": (self.now - timedelta(hours=1)).isoformat(),
        }]
        current = [{
            **self.story,
            "id": "different-id",
            "link": "https://another-source.example/article",
            "title": "البنك المركزي يعلن قرار جديد بشأن اسعار الفائدة",
        }]
        accepted, rejected = filter_recent_repeats(current, history, now=self.now)
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)

    def test_near_duplicate_same_publisher_same_day_is_rejected_within_batch(self):
        first = {
            "id": "fed-rate-1",
            "link": "https://cnnbusinessarabic.com/finance-markets/1152738",
            "title": "عاجل: رئيسة الاحتياطي الفيدرالي في كليفلاند بيث هاماك: أؤيد رفع أسعار الفائدة بشكل متتابع للمساعدة في خفض التضخم",
            "summary": "تصريحات بيث هاماك عن رفع أسعار الفائدة لمواجهة التضخم.",
            "source": "CNBC عربية - أسواق المال",
            "published": "Mon, 16 Nov 2026 14:00:00 +0200",
        }
        duplicate = {
            "id": "fed-rate-2",
            "link": "https://cnnbusinessarabic.com/finance-markets/1152740",
            "title": "رئيسة فيدرالي كليفلاند تؤيد رفع الفائدة بشكل متتابع لخفض التضخم",
            "summary": "بيث هاماك تؤيد رفع الفائدة تدريجياً لخفض التضخم.",
            "source": "CNBC عربية - أسواق المال",
            "published": "Mon, 16 Nov 2026 14:02:00 +0200",
        }
        accepted, rejected = filter_recent_repeats([first, duplicate], [], now=self.now)
        self.assertEqual([item["id"] for item in accepted], ["fed-rate-1"])
        self.assertEqual([item["id"] for item in rejected], ["fed-rate-2"])
        self.assertEqual(rejected[0]["duplicate_of_id"], "fed-rate-1")
        self.assertIn("نفس الدفعة", rejected[0]["reasons"][0])

    def test_opposite_financial_directions_are_not_deduplicated_within_batch(self):
        first = {
            "id": "rate-up",
            "link": "https://example.com/rates-up",
            "title": "البنك المركزي يرفع أسعار الفائدة لمواجهة التضخم",
            "source": "مصدر مالي",
            "published": "Mon, 16 Nov 2026 14:00:00 +0200",
        }
        opposite = {
            "id": "rate-down",
            "link": "https://example.com/rates-down",
            "title": "البنك المركزي يخفض أسعار الفائدة لدعم الاقتصاد",
            "source": "مصدر مالي",
            "published": "Mon, 16 Nov 2026 14:02:00 +0200",
        }
        accepted, rejected = filter_recent_repeats([first, opposite], [], now=self.now)
        self.assertEqual([item["id"] for item in accepted], ["rate-up", "rate-down"])
        self.assertEqual(rejected, [])

    def test_story_within_30_day_window_is_rejected(self):
        history = [{
            **self.story,
            "prepared_at": (self.now - timedelta(days=29, hours=23)).isoformat(),
        }]
        accepted, rejected = filter_recent_repeats([self.story], history, now=self.now)
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("30 يوماً", rejected[0]["reasons"][0])

    def test_story_after_30_day_cooldown_is_allowed(self):
        history = [{
            **self.story,
            "prepared_at": (self.now - timedelta(days=30, hours=1)).isoformat(),
        }]
        accepted, rejected = filter_recent_repeats([self.story], history, now=self.now)
        self.assertEqual(accepted, [self.story])
        self.assertEqual(rejected, [])

    def test_same_story_angle_is_rejected_even_when_headline_changes(self):
        previous = {
            "id": "old-story",
            "link": "https://example.com/old-story",
            "title": "المغرب يتوقع تراجع أسعار المحروقات بدءاً من الاثنين",
            "summary": (
                "توقع المغرب تراجع أسعار المحروقات بدءاً من 16 نوفمبر مع انخفاض الأسعار "
                "العالمية، وتدرس الحكومة تسقيف هوامش أرباح الشركات ورفع الضرائب على الشركات الكبرى."
            ),
            "prepared_at": (self.now - timedelta(days=4)).isoformat(),
        }
        candidate = {
            "id": "new-story",
            "link": "https://another.example/morocco-fuel",
            "title": "الحكومة المغربية تدرس تحديد أرباح شركات الوقود",
            "summary": (
                "توقع المغرب تراجع أسعار المحروقات بدءاً من 16 نوفمبر مع انخفاض الأسعار "
                "العالمية، وتدرس الحكومة تحديد هوامش أرباح الشركات ورفع الضرائب على الشركات الكبرى."
            ),
        }
        accepted, rejected = filter_recent_repeats([candidate], [previous], now=self.now)
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("زاويته", rejected[0]["reasons"][0])

    def test_record_history_retains_30_days_and_stores_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history" / "used_stories.json"
            old = {
                **self.story,
                "id": "old-story",
                "prepared_at": (self.now - timedelta(days=31)).isoformat(),
            }
            recent = {
                **self.story,
                "id": "recent-story",
                "prepared_at": (self.now - timedelta(days=29)).isoformat(),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"version": 1, "stories": [old, recent]}),
                encoding="utf-8",
            )
            record_story_history(path, [self.story], now=self.now)
            loaded = load_story_history(path)
            self.assertEqual({item["id"] for item in loaded}, {"recent-story", "story-1"})
            current = next(item for item in loaded if item["id"] == "story-1")
            self.assertEqual(current["summary"], self.story["summary"])

    def test_future_history_timestamp_does_not_block_story(self):
        history = [{
            **self.story,
            "prepared_at": (self.now + timedelta(minutes=2)).isoformat(),
        }]
        accepted, rejected = filter_recent_repeats([self.story], history, now=self.now)
        self.assertEqual(accepted, [self.story])
        self.assertEqual(rejected, [])

    def test_record_and_reload_history_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history" / "used_stories.json"
            count = record_story_history(path, [self.story], now=self.now)
            loaded = load_story_history(path)
            self.assertEqual(count, 1)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["id"], "story-1")
            self.assertEqual(loaded[0]["state"], "scheduled_draft")
            self.assertEqual(loaded[0]["summary"], self.story["summary"])

    def test_empty_story_batch_does_not_create_history_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            self.assertEqual(record_story_history(path, [], now=self.now), 0)
            self.assertFalse(path.exists())

    def test_corrupt_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "سجل منع التكرار غير صالح"):
                load_story_history(path)

    def test_unsupported_history_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps({"version": 2, "stories": []}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "غير متوافق"):
                load_story_history(path)


if __name__ == "__main__":
    unittest.main()

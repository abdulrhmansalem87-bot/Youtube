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

    def test_story_after_cooldown_is_allowed(self):
        history = [{
            **self.story,
            "prepared_at": (self.now - timedelta(hours=9)).isoformat(),
        }]
        accepted, rejected = filter_recent_repeats([self.story], history, now=self.now)
        self.assertEqual(accepted, [self.story])
        self.assertEqual(rejected, [])

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

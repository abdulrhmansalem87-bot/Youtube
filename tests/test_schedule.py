import unittest
from datetime import datetime, timezone

from newsflow.schedule import resolve_schedule_slot


class CairoScheduleTests(unittest.TestCase):
    def test_non_schedule_event_is_not_a_due_slot(self):
        result = resolve_schedule_slot("", datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc))
        self.assertFalse(result["run"])
        self.assertEqual(result["reason"], "not a scheduled event")

    def test_unknown_cron_is_skipped(self):
        result = resolve_schedule_slot("15 13 * * *", datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc))
        self.assertFalse(result["run"])
        self.assertEqual(result["reason"], "unknown cron expression")

    def test_winter_slots_match_cairo_utc_plus_two(self):
        cases = (
            ("0 13 * * *", datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc), "15:00", 4),
            ("0 17 * * *", datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc), "19:00", 4),
            ("0 20 * * *", datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc), "22:00", 3),
        )
        for cron, instant, target, lookback in cases:
            with self.subTest(cron=cron):
                result = resolve_schedule_slot(cron, instant)
                self.assertTrue(result["run"])
                self.assertEqual(result["target_local_time"], target)
                self.assertEqual(result["lookback_hours"], lookback)
                self.assertEqual(result["cairo_utc_offset"], "+0200")

    def test_summer_slots_match_cairo_utc_plus_three(self):
        cases = (
            ("0 12 * * *", datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc), "15:00", 4),
            ("0 16 * * *", datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc), "19:00", 4),
            ("0 19 * * *", datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc), "22:00", 3),
        )
        for cron, instant, target, lookback in cases:
            with self.subTest(cron=cron):
                result = resolve_schedule_slot(cron, instant)
                self.assertTrue(result["run"])
                self.assertEqual(result["target_local_time"], target)
                self.assertEqual(result["lookback_hours"], lookback)
                self.assertEqual(result["cairo_utc_offset"], "+0300")

    def test_inactive_season_cron_does_not_duplicate_the_slot(self):
        winter = resolve_schedule_slot(
            "0 12 * * *", datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        )
        summer = resolve_schedule_slot(
            "0 13 * * *", datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
        )
        self.assertFalse(winter["run"])
        self.assertFalse(summer["run"])
        self.assertIn("inactive seasonal cron", winter["reason"])
        self.assertIn("inactive seasonal cron", summer["reason"])

    def test_cairo_delivery_window_allows_small_delay_but_rejects_stale_slot(self):
        near_boundary = resolve_schedule_slot(
            "0 13 * * *", datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
        )
        stale = resolve_schedule_slot(
            "0 13 * * *", datetime(2026, 11, 15, 14, 31, tzinfo=timezone.utc)
        )
        self.assertTrue(near_boundary["run"])
        self.assertFalse(stale["run"])
        self.assertIn("missed slot", stale["reason"])

    def test_naive_now_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            resolve_schedule_slot("0 13 * * *", datetime(2026, 11, 15, 13, 0))


if __name__ == "__main__":
    unittest.main()

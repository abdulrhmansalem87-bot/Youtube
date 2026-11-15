import unittest
from datetime import datetime, timezone

from newsflow.schedule import resolve_schedule_slot


class CairoScheduleTests(unittest.TestCase):
    def test_winter_afternoon_cron_matches_cairo_15(self):
        now = datetime(2026, 11, 14, 13, 43, tzinfo=timezone.utc)
        result = resolve_schedule_slot("0 13 * * *", now)
        self.assertTrue(result["run"])
        self.assertEqual(result["target_local_time"], "15:00")
        self.assertEqual(result["lookback_hours"], 4)

    def test_summer_afternoon_cron_matches_cairo_15(self):
        now = datetime(2026, 6, 15, 12, 43, tzinfo=timezone.utc)
        result = resolve_schedule_slot("0 12 * * *", now)
        self.assertTrue(result["run"])
        self.assertEqual(result["target_local_time"], "15:00")

    def test_wrong_season_cron_is_skipped(self):
        winter = datetime(2026, 11, 14, 12, 43, tzinfo=timezone.utc)
        summer = datetime(2026, 6, 15, 13, 43, tzinfo=timezone.utc)
        self.assertFalse(resolve_schedule_slot("0 12 * * *", winter)["run"])
        self.assertFalse(resolve_schedule_slot("0 13 * * *", summer)["run"])

    def test_late_evening_uses_three_hour_lookback(self):
        winter = datetime(2026, 11, 14, 20, 43, tzinfo=timezone.utc)
        summer = datetime(2026, 6, 15, 19, 43, tzinfo=timezone.utc)
        self.assertEqual(resolve_schedule_slot("0 20 * * *", winter)["lookback_hours"], 3)
        self.assertEqual(resolve_schedule_slot("0 19 * * *", summer)["lookback_hours"], 3)

    def test_stale_scheduled_run_is_skipped(self):
        now = datetime(2026, 11, 14, 16, 45, tzinfo=timezone.utc)
        self.assertFalse(resolve_schedule_slot("0 13 * * *", now)["run"])

    def test_non_schedule_events_are_not_treated_as_daily_slots(self):
        result = resolve_schedule_slot("")
        self.assertFalse(result["run"])
        self.assertEqual(result["lookback_hours"], 4)
        self.assertEqual(result["reason"], "not a scheduled event")


if __name__ == "__main__":
    unittest.main()

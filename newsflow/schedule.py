"""Keep GitHub's UTC cron entries aligned with Cairo time year-round."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")
# cron -> (target local hour, Cairo UTC offset, editorial lookback hours)
SCHEDULES = {
    "0 13 * * *": (15, 2, 4),
    "0 17 * * *": (19, 2, 4),
    "0 20 * * *": (22, 2, 3),
    "0 12 * * *": (15, 3, 4),
    "0 16 * * *": (19, 3, 4),
    "0 19 * * *": (22, 3, 3),
}
MAX_LATENESS_MINUTES = 90
EARLY_TOLERANCE_MINUTES = 5


def resolve_schedule_slot(schedule: str, now: datetime | None = None) -> dict:
    """Run only the cron matching Cairo's actual offset and a fresh delivery window."""
    if not schedule:
        return {"run": True, "lookback_hours": 4, "target_local_time": "", "reason": "non-scheduled event"}
    slot = SCHEDULES.get(schedule)
    if slot is None:
        return {"run": False, "lookback_hours": 4, "target_local_time": "", "reason": "unknown cron"}
    target_hour, expected_offset, lookback_hours = slot
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = current.astimezone(CAIRO)
    offset_matches = local.utcoffset() == timedelta(hours=expected_offset)
    minutes_from_target = (local.hour - target_hour) * 60 + local.minute
    fresh_window = -EARLY_TOLERANCE_MINUTES <= minutes_from_target <= MAX_LATENESS_MINUTES
    return {
        "run": bool(offset_matches and fresh_window),
        "lookback_hours": lookback_hours,
        "target_local_time": f"{target_hour:02d}:00",
        "reason": "matched Cairo offset and delivery window" if offset_matches and fresh_window
                  else "cron offset or delivery window does not match Cairo",
    }


def main() -> None:
    schedule = sys.argv[1] if len(sys.argv) > 1 else ""
    result = resolve_schedule_slot(schedule)
    for key, value in result.items():
        print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")


if __name__ == "__main__":
    main()

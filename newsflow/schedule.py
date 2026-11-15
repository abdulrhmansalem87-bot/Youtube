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
    """Accept only a real scheduled event in the active Cairo season and delivery window.

    Empty schedule values are push, pull-request, or manually dispatched events;
    they must never be interpreted as a due production slot.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local = current.astimezone(CAIRO)
    local_offset = local.utcoffset() or timedelta(0)

    if not schedule:
        return {
            "run": False,
            "lookback_hours": 4,
            "target_local_time": "",
            "cairo_local_time": local.strftime("%Y-%m-%d %H:%M"),
            "cairo_utc_offset": local.strftime("%z"),
            "minutes_from_target": "",
            "reason": "not a scheduled event",
        }

    slot = SCHEDULES.get(schedule)
    if slot is None:
        return {
            "run": False,
            "lookback_hours": 4,
            "target_local_time": "",
            "cairo_local_time": local.strftime("%Y-%m-%d %H:%M"),
            "cairo_utc_offset": local.strftime("%z"),
            "minutes_from_target": "",
            "reason": "unknown cron expression",
        }

    target_hour, expected_offset, lookback_hours = slot
    offset_matches = local_offset == timedelta(hours=expected_offset)
    target_local = local.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    minutes_from_target = int((local - target_local).total_seconds() // 60)

    if not offset_matches:
        reason = (
            f"inactive seasonal cron: expected UTC{expected_offset:+d}, "
            f"Cairo is UTC{int(local_offset.total_seconds() // 3600):+d}"
        )
        run = False
    elif minutes_from_target < -EARLY_TOLERANCE_MINUTES:
        reason = "scheduled event arrived before its delivery window"
        run = False
    elif minutes_from_target > MAX_LATENESS_MINUTES:
        reason = "missed slot: scheduled event arrived more than 90 minutes late"
        run = False
    else:
        reason = "matched active Cairo slot and delivery window"
        run = True

    return {
        "run": run,
        "lookback_hours": lookback_hours,
        "target_local_time": f"{target_hour:02d}:00",
        "cairo_local_time": local.strftime("%Y-%m-%d %H:%M"),
        "cairo_utc_offset": local.strftime("%z"),
        "minutes_from_target": minutes_from_target,
        "reason": reason,
    }


def main() -> None:
    schedule = sys.argv[1] if len(sys.argv) > 1 else ""
    result = resolve_schedule_slot(schedule)
    for key, value in result.items():
        print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")


if __name__ == "__main__":
    main()

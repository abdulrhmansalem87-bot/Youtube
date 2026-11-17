"""Persist 30-day story and angle history between scheduled WealthRadar runs."""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HISTORY_VERSION = 1
DEFAULT_COOLDOWN_HOURS = 24 * 30
RETENTION_DAYS = 30
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid"}


def canonical_story_link(value: str) -> str:
    """Remove tracking-only URL parts while preserving meaningful query parameters."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.split("#", 1)[0].rstrip("/")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((
        parsed.scheme.casefold(),
        parsed.netloc.casefold(),
        parsed.path.rstrip("/") or "/",
        urlencode(sorted(query)),
        "",
    ))


def normalize_story_title(value: str) -> str:
    """Normalize Arabic diacritics and punctuation for conservative duplicate checks."""
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    text = "".join(
        char for char in text
        if unicodedata.category(char) not in {"Mn", "Cf"} and char != "ـ"
    )
    text = text.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
    }))
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _entry_timestamp(item: dict) -> datetime | None:
    value = str(item.get("prepared_at") or item.get("used_at") or "").strip()
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)

def _published_day(item: dict) -> str:
    """Return the publisher's calendar day for conservative same-batch duplicate checks."""
    value = str(item.get("published") or "").strip()
    if not value:
        return ""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            timestamp = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return ""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).date().isoformat()


def _batch_comparison_title(value: str) -> str:
    """Ignore common headline filler so same-day syndicated variants compare reliably."""
    stopwords = {
        "عاجل", "في", "من", "على", "عن", "الى", "إلى", "بعد", "قبل",
        "بشكل", "للمساعدة", "المساعدة", "هذا", "هذه", "ذلك", "التي", "الذي",
    }
    return " ".join(
        token for token in normalize_story_title(value).split()
        if token not in stopwords
    )


def _opposite_financial_direction(first: str, second: str) -> bool:
    """Do not collapse otherwise similar headlines that report opposite market moves."""
    positive_terms = ("يرفع", "رفع", "يزيد", "زيادة", "يرتفع", "ارتفاع", "صعود", "يصعد", "قفز", "نمو")
    negative_terms = ("يخفض", "خفض", "يتراجع", "تراجع", "ينخفض", "انخفاض", "هبوط", "يهبط", "تقلص", "تباطؤ")
    first = normalize_story_title(first)
    second = normalize_story_title(second)
    first_positive = any(term in first for term in positive_terms)
    first_negative = any(term in first for term in negative_terms)
    second_positive = any(term in second for term in positive_terms)
    second_negative = any(term in second for term in negative_terms)
    return (
        (first_positive and not first_negative and second_negative and not second_positive)
        or (first_negative and not first_positive and second_positive and not second_negative)
    )


def load_story_history(path: Path) -> list[dict]:
    """Load history; fail closed on a malformed cache instead of silently repeating stories."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "سجل منع التكرار غير صالح؛ أوقفنا اختيار الأخبار حتى لا نعيد أخباراً سبق إعدادها."
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != HISTORY_VERSION:
        raise RuntimeError(
            "إصدار سجل منع التكرار غير متوافق؛ أوقفنا التشغيل بدلاً من تجاهل سجل الأخبار السابقة."
        )
    stories = payload.get("stories")
    if not isinstance(stories, list) or any(not isinstance(item, dict) for item in stories):
        raise RuntimeError("بنية سجل منع التكرار غير سليمة؛ أوقفنا التشغيل بأمان.")
    return stories


def filter_recent_repeats(
    stories: list[dict],
    history: list[dict],
    *,
    now: datetime | None = None,
    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
) -> tuple[list[dict], list[dict]]:
    """Remove exact, canonical-link, or strongly similar story angles within the 30-day window."""
    if not isinstance(cooldown_hours, (int, float)) or cooldown_hours <= 0:
        raise ValueError("cooldown_hours must be a positive number")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    cutoff = timedelta(hours=float(cooldown_hours))

    recent: list[dict] = []
    for item in history:
        timestamp = _entry_timestamp(item)
        if timestamp is not None:
            age = current - timestamp
            if timedelta(0) <= age <= cutoff:
                recent.append(item)

    accepted: list[dict] = []
    rejected: list[dict] = []
    batch_seen: list[dict] = []
    for story in stories:
        story_id = str(story.get("id") or "").strip()
        link = canonical_story_link(story.get("link", ""))
        title = normalize_story_title(story.get("title", ""))
        summary = normalize_story_title(story.get("summary", ""))
        duplicate = None
        duplicate_in_batch = False

        comparisons = [(item, False) for item in recent]
        comparisons.extend((item, True) for item in batch_seen)
        for previous, same_batch in comparisons:
            old_id = str(previous.get("id") or "").strip()
            old_link = canonical_story_link(previous.get("link", ""))
            old_title = normalize_story_title(previous.get("title", ""))
            old_summary = normalize_story_title(previous.get("summary", ""))
            same_id = bool(story_id and old_id and story_id == old_id)
            same_link = bool(link and old_link and link == old_link)
            title_ratio = (
                difflib.SequenceMatcher(None, title, old_title).ratio()
                if title and old_title else 0.0
            )
            # A changed headline must not disguise the same angle. Compare the
            # source summaries as well, but require enough text to avoid matching
            # generic one-line RSS descriptions.
            summary_ratio = (
                difflib.SequenceMatcher(None, summary, old_summary).ratio()
                if len(summary) >= 80 and len(old_summary) >= 80 else 0.0
            )
            same_publisher_same_day = (
                same_batch
                and bool(str(story.get("source") or "").strip())
                and normalize_story_title(story.get("source", ""))
                    == normalize_story_title(previous.get("source", ""))
                and bool(_published_day(story))
                and _published_day(story) == _published_day(previous)
            )
            batch_title_ratio = (
                difflib.SequenceMatcher(
                    None,
                    _batch_comparison_title(title),
                    _batch_comparison_title(old_title),
                ).ratio()
                if title and old_title else 0.0
            )
            similar_same_batch_headline = (
                same_publisher_same_day
                and len(title) >= 24
                and batch_title_ratio >= 0.76
                and not _opposite_financial_direction(title, old_title)
            )
            opposite_direction = _opposite_financial_direction(title, old_title)
            if (
                same_id or same_link
                or (
                    not opposite_direction
                    and (
                        (len(title) >= 24 and title_ratio >= 0.90)
                        or summary_ratio >= 0.88
                    )
                )
                or similar_same_batch_headline
            ):
                duplicate = previous
                duplicate_in_batch = same_batch
                break

        if duplicate is not None:
            cooldown_days = float(cooldown_hours) / 24
            cooldown_label = (
                "نفس الدفعة"
                if duplicate_in_batch
                else (
                    f"{int(cooldown_days)} يوماً"
                    if cooldown_days.is_integer()
                    else f"{float(cooldown_hours):g} ساعة"
                )
            )
            rejected.append({
                "id": story.get("id"),
                "title": story.get("title"),
                "source": story.get("source", "مصدر غير محدد"),
                "reasons": [
                    f"خبر مكرر أو زاويته سبق تناولها خلال {cooldown_label}."
                ],
                "duplicate_of_id": duplicate.get("id", ""),
                "previously_prepared_at": duplicate.get("prepared_at") or duplicate.get("used_at", ""),
            })
        else:
            accepted.append(story)
            batch_seen.append(story)
    return accepted, rejected


def record_story_history(
    path: Path,
    stories: list[dict],
    *,
    now: datetime | None = None,
) -> int:
    """Atomically record reviewed stories and retain 30 days for repeat prevention."""
    if not stories:
        return 0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    stamp = current.isoformat(timespec="seconds").replace("+00:00", "Z")

    existing = load_story_history(path)
    combined = list(existing)
    for story in stories:
        combined.append({
            "id": str(story.get("id") or ""),
            "link": canonical_story_link(story.get("link", "")),
            "title": str(story.get("title") or ""),
            "summary": str(story.get("summary") or ""),
            "source": str(story.get("source") or ""),
            "prepared_at": stamp,
            "state": "scheduled_draft",
        })

    cutoff = current - timedelta(days=RETENTION_DAYS)
    retained = []
    for item in combined:
        timestamp = _entry_timestamp(item)
        if timestamp is not None and timestamp >= cutoff:
            retained.append(item)

    # Collapse multiple records for the same story while preserving the newest record.
    unique: dict[str, dict] = {}
    for item in retained:
        key = (
            str(item.get("id") or "")
            or canonical_story_link(item.get("link", ""))
            or normalize_story_title(item.get("title", ""))
        )
        if key:
            unique[key] = item
    final_stories = list(unique.values())[-500:]

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"version": HISTORY_VERSION, "stories": final_stories},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return len(stories)

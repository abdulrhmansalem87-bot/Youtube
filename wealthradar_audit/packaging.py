"""Packaging checks and the launch SOP for an audit episode (owner platform rules, 2026-11-26).

1. Suggested/Browse-first: curiosity plus a clear promise in the title and thumbnail. Keywords go naturally in the
   description only, never stuffed.
2. Hook rule: the first 5 to 10 seconds state the result. No intro or logo before it (see newsflow.hook_rule).
3. A/B protocol: Test & Compare is Studio-only and manual. The decision metric is average view duration, not CTR.
4. Accuracy and disclosure: every number is sourced in the description; the synthetic-media disclosure is set on upload.
5. Per-video scorecard: retention and watch time from Analytics once data exists, no fixed-schedule superstition.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter

from newsflow import hook_rule

TITLE_MAX = 100
MAX_HASHTAGS = 3
_WORD = re.compile(r"[\u0600-\u06FFA-Za-z0-9]+")

SCORECARD_COLUMNS = [
    "video_id", "title", "published_cairo", "thumbnail_variant_winner", "avg_view_duration_s", "avg_pct_viewed",
    "watch_time_hours", "retention_at_30s_pct", "retention_dip_at_s", "impressions", "ctr_pct",
    "viewed_vs_swiped_pct", "traffic_suggested_pct", "traffic_browse_pct", "traffic_search_pct", "subs_gained",
    "what_we_change_next",
]


def title_problems(title: str, description: str = "") -> list[str]:
    """Return packaging problems. Empty list means the title and description pass the mechanical checks."""
    problems = []
    t = re.sub(r"\s+", " ", title or "").strip()
    if not t:
        return ["empty title"]
    if len(t) > TITLE_MAX:
        problems.append(f"title is {len(t)} characters, over {TITLE_MAX}")
    counts = Counter(w.lower() for w in _WORD.findall(t) if len(w) > 2)
    stuffed = [w for w, n in counts.items() if n > 2]
    if stuffed:
        problems.append("keyword repeated in the title: " + ", ".join(stuffed))
    if t.count("!") > 1 or t.count("؟") > 1 or t.count("?") > 1:
        problems.append("too many exclamation or question marks in the title")
    if description:
        tags = re.findall(r"#\S+", description)
        if len(tags) > MAX_HASHTAGS:
            problems.append(f"{len(tags)} hashtags in the description, keep at most {MAX_HASHTAGS}")
    return problems


def script_hook_problems(first_line: str) -> list[str]:
    """The finished narration's first line must state the result as a number, with no intro before it."""
    return hook_rule.hook_problems(first_line, require_number=True)


def scorecard_csv() -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow(SCORECARD_COLUMNS)
    return buf.getvalue()


def launch_checklist(brief: dict) -> str:
    q = brief.get("question_ar", "")
    return f"""# Launch checklist (manual Studio pass, owner)

Episode question: {q}

## Before upload
- [ ] The first narration line states the result as a number, with no greeting, intro or logo before it (hook rule, {hook_rule.HOOK_MAX_WORDS} words at most). The branded ident, if used, comes after the hook.
- [ ] Title: a clear promise plus curiosity, within {TITLE_MAX} characters, no repeated keywords, no clickbait the video does not pay off in the first seconds.
- [ ] Description: sources listed for every number (never on screen), keywords only as natural words, at most {MAX_HASHTAGS} hashtags, no unresolved affiliate placeholders.
- [ ] Every number on screen and in the script is in `brief.json`. Nothing added by hand.
- [ ] Upload is PRIVATE first.

## Altered or synthetic content disclosure
- The narration is text-to-speech, so the disclosure is turned on. The upload step sets `status.containsSyntheticMedia = true` through the API (field documented on https://developers.google.com/youtube/v3/docs/videos, added to the API in the 2024-10-30 revision).
- [ ] In Studio, open Details, Show more, "Altered content", and confirm it shows Yes. If it shows No, set it by hand before publishing (the API setting is unverified until the first real upload).

## A/B (Test & Compare, Studio on a computer, manual)
- [ ] Upload `thumb_A.jpg` and `thumb_B.jpg` under Test & Compare (up to 3 thumbnails; https://support.google.com/youtube/answer/16391400).
- [ ] Decision metric: average view duration (and viewer satisfaction), not CTR alone. A thumbnail that wins clicks but loses view duration loses the test.
- [ ] Let the test run to the end, then keep the winner. Record it in the scorecard.

## After publish: per-video scorecard (`scorecard.csv`)
- [ ] Once Analytics has data: retention curve (where it dips), average view duration, watch time, traffic from Suggested and Browse versus Search, viewed-versus-swiped for Shorts.
- [ ] One line: what we change next. Judge each video on its own numbers, not on a posting-time rule.
"""

"""Fast lane: a Short for a breaking Egyptian event that has a money angle.

Design (see HANDOVER.md section 11). This module is the offline, deterministic part: money-angle detection,
safety gate, title and hashtag generation, and the brief that the v3 Short renderer consumes. The live watch
(RSS + Tavily search + Groq) calls these functions once the keys are wired; nothing here needs a network.

Rules baked in:
- Only figures that carry a source URL may appear. A brief with no sourced figure is blocked, never invented.
- At least two independent source domains for any figure, else blocked.
- Events with deaths or injuries are flagged sensitive: the Short must be about the economic fallout, with no
  victim names, no blame, and the owner reviews before it goes live.
- Sources go in the description, never on screen.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

SHOW_NAME = "كشف حساب"
MAX_TITLE_CHARS = 70
MAX_HASHTAGS = 8

MONEY_TERMS = {
    "loss": ["خسائر", "خسارة", "تلفيات", "تكلفة", "كلفت", "أضرار"],
    "compensation": ["تعويض", "تعويضات", "تأمين", "وثيقة", "صرف"],
    "prices": ["أسعار", "سعر", "غلاء", "ارتفاع", "انخفاض", "تسعيرة"],
    "markets": ["ذهب", "دولار", "الدولار", "بورصة", "فائدة", "الفائدة", "جنيه", "الجنيه", "عملة"],
    "traders": ["تجار", "تاجر", "محلات", "سوق", "أسواق", "مصنع", "مخازن", "بضائع"],
    "policy": ["ضريبة", "ضرائب", "دعم", "رسوم", "قرار", "معاش", "إيجار", "بنزين", "كهرباء"],
}
SENSITIVE_TERMS = ["وفاة", "قتلى", "قتيل", "مصرع", "إصابة", "مصابين", "ضحايا", "جثث", "اغتصاب", "انتحار"]
TITLE_TEMPLATES = {
    "loss": "{event}: كلّف كام؟",
    "compensation": "{event}: مين هيعوّض؟",
    "prices": "{event}: إيه اللي هيحصل للأسعار؟",
    "markets": "{event}: إيه تأثيره على فلوسك؟",
    "traders": "{event}: التجار خسروا كام؟",
    "policy": "{event}: هيكلّفك كام؟",
}
ANGLE_PRIORITY = ["loss", "compensation", "traders", "prices", "markets", "policy"]


def money_angles(text: str) -> dict:
    found = {k: [w for w in words if w in text] for k, words in MONEY_TERMS.items()}
    found = {k: v for k, v in found.items() if v}
    score = sum(len(v) for v in found.values())
    return {"angles": found, "score": score, "has_money_angle": score >= 2 or bool({"loss", "compensation"} & set(found))}


def is_sensitive(text: str) -> bool:
    return any(w in text for w in SENSITIVE_TERMS)


def pick_angle(angles: dict) -> str | None:
    for key in ANGLE_PRIORITY:
        if key in angles:
            return key
    return None


def make_title(event_phrase: str, angle: str) -> str:
    event_phrase = re.sub(r"\s+", " ", event_phrase).strip()
    title = TITLE_TEMPLATES[angle].format(event=event_phrase)
    while len(title) > MAX_TITLE_CHARS and " " in event_phrase:
        event_phrase = event_phrase.rsplit(" ", 1)[0]
        title = TITLE_TEMPLATES[angle].format(event=event_phrase)
    return title


def _tag(term: str) -> str:
    term = re.sub(r"[^\w\s]", "", term, flags=re.UNICODE).strip()
    return "#" + re.sub(r"\s+", "_", term) if term else ""


def make_hashtags(trend_terms: list[str], extra: list[str] | None = None) -> list[str]:
    """Trending terms first (most specific), then the fixed channel tags. YouTube shows the first three above the title."""
    tags: list[str] = []
    for term in list(trend_terms) + list(extra or []) + [SHOW_NAME, "Shorts", "اقتصاد_مصر"]:
        tag = _tag(term)
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    return tags[:MAX_HASHTAGS]


def build_short_brief(event: dict, facts: list[dict], trend_terms: list[str]) -> dict:
    """event: {headline, summary, event_phrase}; facts: [{text, value, unit, source_url}]."""
    text = f"{event.get('headline', '')} {event.get('summary', '')}"
    m = money_angles(text)
    blockers: list[str] = []
    if not m["has_money_angle"]:
        blockers.append("no money angle: not a fast-lane event")
    angle = pick_angle(m["angles"])
    sourced = [f for f in facts if str(f.get("source_url", "")).startswith("https://") and f.get("value") not in (None, "")]
    if len(sourced) != len(facts):
        blockers.append("a figure has no https source or no value: remove or source it")
    domains = {urlparse(f["source_url"]).netloc.removeprefix("www.") for f in sourced}
    if not sourced:
        blockers.append("no sourced figure: nothing to show on screen")
    elif len(domains) < 2:
        blockers.append("figures come from a single source domain: need two independent sources")
    sensitive = is_sensitive(text)
    review = []
    if sensitive:
        review.append("sensitive event (deaths or injuries): economic fallout only, no victim names, no blame, owner review before publishing")
    title = make_title(event.get("event_phrase") or event.get("headline", ""), angle) if angle else ""
    return {
        "show": SHOW_NAME, "angle": angle, "title": title, "hashtags": make_hashtags(trend_terms),
        "figures": sourced, "source_urls": sorted({f["source_url"] for f in sourced}),
        "format": {"render_path": "v3 Short (palette A, 720x1280, 35-45 s)", "sources_on_screen": False,
                   "numbers": "final values only"},
        "sensitive": sensitive, "owner_review_required": review, "blockers": blockers,
        "publishable": not blockers and not sensitive,
    }

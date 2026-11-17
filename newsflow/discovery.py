"""Trend signals for story discovery; never a source of factual verification."""
from __future__ import annotations

import re
import unicodedata


TREND_CATEGORIES = {"ترند مصر", "ترند عالمي"}


def is_trend_source(source: dict) -> bool:
    return str(source.get("category") or "").strip().casefold() in TREND_CATEGORIES


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[\u064b-\u065f\u0670ـ]", "", value)
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "into", "about",
        "after", "before", "today", "news", "latest", "في", "من", "على", "عن",
        "الى", "إلى", "هذا", "هذه", "ذلك", "مع", "بعد", "قبل", "اليوم",
    }
    return {
        token for token in re.findall(r"[a-z0-9]+|[\u0600-\u06ff]+", _normalize(value))
        if len(token) > 1 and token not in stop
    }


def parse_trend_signal(entry: dict, source: dict) -> dict | None:
    title = re.sub(r"\s+", " ", str(entry.get("title") or "")).strip()
    if len(title) < 2:
        return None
    return {
        "query": title[:180],
        "country": "Egypt" if source.get("category") == "ترند مصر" else "Global",
        "source": str(source.get("name") or "Google Trends"),
        "url": str(entry.get("link") or "")[:1000],
        "approx_traffic": str(entry.get("ht_approx_traffic") or "")[:40],
    }


def match_trend_signal(story: dict, signal: dict) -> float:
    query = _normalize(signal.get("query") or "")
    text = _normalize(f"{story.get('title') or ''} {story.get('summary') or ''}")
    if not query or not text:
        return 0.0
    if len(query) >= 4 and query in text:
        return 1.0
    query_tokens = _tokens(query)
    if len(query_tokens) < 2:
        token = next(iter(query_tokens), "")
        return 0.75 if len(token) >= 6 and token in _tokens(text) else 0.0
    overlap = len(query_tokens & _tokens(text)) / len(query_tokens)
    return overlap if overlap >= 0.6 else 0.0


def attach_trend_signals(stories: list[dict], signals: list[dict]) -> list[dict]:
    """Annotate matching news stories; trend records themselves are never stories."""
    enriched = []
    for story in stories:
        matches = []
        for signal in signals:
            score = match_trend_signal(story, signal)
            if score:
                matches.append({
                    "query": signal["query"],
                    "country": signal["country"],
                    "source": signal["source"],
                    "match_score": round(score, 3),
                })
        matches.sort(key=lambda item: item["match_score"], reverse=True)
        item = dict(story)
        item["trend_matches"] = matches[:3]
        item["trend_score"] = max((m["match_score"] for m in matches), default=0.0)
        enriched.append(item)
    return enriched

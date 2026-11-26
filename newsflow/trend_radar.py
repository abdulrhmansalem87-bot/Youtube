"""Tavily-backed trend radar: fresh news headlines used only to RANK stories we already collected.

A radar signal is never a fact and never a story. It has the same shape as a Google Trends
signal (see newsflow.discovery), so attach_trend_signals() boosts matching stories and nothing
else changes. Fact checking stays with the evidence gates. Only public query text is sent.

Cost: one basic Tavily search is 1 credit. Default is 3 searches per run
(NEWSFLOW_TREND_RADAR_QUERIES caps it; 0 turns the radar off). Fail-soft: any error returns [].
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from newsflow.discovery import match_trend_signal
from newsflow.editorial import _has_term, relevance

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_QUERIES = (
    ("أسعار الذهب والدولار والبورصة المصرية اليوم", "Egypt"),
    ("global economy markets central bank inflation oil today", "Global"),
    ("Elon Musk OR Nvidia OR OpenAI OR Federal Reserve announcement", "Global"),
)
MAX_SIGNALS = 40


def _queries() -> list[tuple[str, str]]:
    try:
        limit = int(os.getenv("NEWSFLOW_TREND_RADAR_QUERIES", str(len(DEFAULT_QUERIES))))
    except ValueError:
        limit = len(DEFAULT_QUERIES)
    return list(DEFAULT_QUERIES[: max(0, min(limit, len(DEFAULT_QUERIES)))])


def _domain(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_results(response: dict, country: str) -> list[dict]:
    """Turn one Tavily response into trend signals (same shape as discovery.parse_trend_signal)."""
    signals = []
    results = response.get("results") if isinstance(response, dict) else None
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        url = str(item.get("url") or "").strip()
        if len(title) < 8 or not url.startswith(("http://", "https://")):
            continue
        signals.append({
            "query": title[:180],
            "country": country,
            "source": f"Tavily Trend Radar ({_domain(url) or 'web'})",
            "url": url[:1000],
            "approx_traffic": "",
            "snippet": re.sub(r"\s+", " ", str(item.get("content") or "")).strip()[:400],
            "published": str(item.get("published_date") or "")[:60],
        })
    return signals


def fetch_signals(api_key: str | None = None, post=None) -> list[dict]:
    """Run the radar queries. Returns signals, or [] when disabled, keyless or failing."""
    key = (api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")).strip()
    queries = _queries()
    if not key or not queries:
        print("[TREND_RADAR] skipped: no TAVILY_API_KEY or radar disabled")
        return []
    if post is None:
        from newsflow.fact_check import _post_json as post
    signals, seen = [], set()
    for query, country in queries:
        payload = {
            "query": query, "topic": "news", "time_range": "day",
            "search_depth": "basic", "max_results": 10,
            "include_answer": False, "include_raw_content": False,
        }
        try:
            response = post(TAVILY_SEARCH_URL, payload, key, "Tavily trend radar")
        except Exception as exc:  # noqa: BLE001 - the radar must never stop an episode
            print(f"[TREND_RADAR] query failed ({type(exc).__name__}): {str(exc)[:120]}")
            continue
        for signal in parse_results(response, country):
            if signal["url"] in seen:
                continue
            seen.add(signal["url"])
            signals.append(signal)
    signals = signals[:MAX_SIGNALS]
    print(f"[TREND_RADAR] signals={len(signals)} queries={len(queries)}")
    return signals


# ---- radar signals that match no collected story become candidate topics -------------------
# Channel rule (owner, 2026-11-26): the format is "what did it cost people", not plain news.
# A candidate needs a clear money angle on top of the normal editorial finance check, and it
# then goes through exactly the same gates as any RSS story: relevance, original-source
# extraction, fact check. The radar only supplies a lead and a real article URL.
CONSEQUENCE_TERMS = (
    "كلف", "كلفت", "تكلفة", "تكاليف", "خسائر", "خسارة", "خسر", "خسرت", "غرامة", "غرامات",
    "ارتفاع الأسعار", "ارتفاع أسعار", "انخفاض الأسعار", "زيادة الأسعار", "رفع الأسعار", "تخفيض الأسعار",
    "أسعار", "سعر", "غلاء", "تضخم", "رسوم", "ضرائب", "جمارك", "أجور", "رواتب", "معاشات", "دعم",
    "فاتورة", "فواتير", "تسريح", "إفلاس", "تعويضات", "تعويض",
    "cost", "costs", "costing", "loss", "losses", "lost", "price", "prices", "tariff", "tariffs",
    "tax", "taxes", "fee", "fees", "fine", "fined", "bill", "bills", "salary", "salaries", "wage",
    "wages", "layoffs", "bankruptcy", "compensation", "inflation", "savings", "pension", "subsidy",
)
AMOUNT_PATTERN = re.compile(
    r"(?:\d[\d,.\u066b\u066c]*\s*(?:billion|million|trillion|bn|مليار|مليون|تريليون|ألف)?\s*"
    r"(?:egp|usd|eur|gbp|dollars?|euros?|pounds?|جنيه|دولار|يورو|ريال|درهم|\$|€|£))"
    r"|(?:[$€£]\s?\d)"
    r"|(?:\d[\d,.\u066b\u066c]*\s*(?:billion|million|trillion|مليار|مليون|تريليون))",
    re.IGNORECASE,
)
DEFAULT_MAX_CANDIDATES = 3


def money_angle(title: str, snippet: str = "") -> str:
    """Return why the item has a clear money angle, or '' when it does not."""
    title = str(title or "")
    snippet = str(snippet or "")
    if AMOUNT_PATTERN.search(title):
        return "مبلغ مالي صريح في العنوان"
    if _has_term(title, CONSEQUENCE_TERMS):
        return "عنوان يتناول تكلفة أو خسارة أو سعراً يمس جيب الناس"
    if AMOUNT_PATTERN.search(snippet) and _has_term(title, ("اقتصاد", "الاقتصاد", "economy", "market", "markets", "سوق", "الأسواق")):
        return "مبلغ مالي صريح في النص مع عنوان اقتصادي"
    return ""


def _published_ts(value: str) -> float:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


def radar_candidates(signals: list[dict], stories: list[dict], limit: int | None = None) -> list[dict]:
    """Unmatched radar signals with a money angle, as story dicts for the normal pipeline."""
    if limit is None:
        try:
            limit = int(os.getenv("NEWSFLOW_RADAR_TOPICS_MAX", str(DEFAULT_MAX_CANDIDATES)))
        except ValueError:
            limit = DEFAULT_MAX_CANDIDATES
    if limit <= 0:
        return []
    known_links = {str(story.get("link") or "") for story in stories}
    out = []
    for signal in signals:
        url = str(signal.get("url") or "")
        if not url or url in known_links:
            continue
        if any(match_trend_signal(story, signal) for story in stories):
            continue  # a collected story already covers it; the signal only boosts that story
        title = str(signal.get("query") or "")
        snippet = str(signal.get("snippet") or "")
        reason = money_angle(title, snippet)
        if not reason:
            continue
        story = {
            "id": hashlib.sha256(url.encode()).hexdigest()[:12],
            "title": title, "link": url, "published": str(signal.get("published") or ""),
            "published_ts": _published_ts(str(signal.get("published") or "")),
            "summary": snippet[:280],
            "source": str(signal.get("source") or "Tavily Trend Radar"),
            "category": "رادار الترند",  # neutral on purpose: no finance-category shortcut
            "origin": "trend_radar", "money_angle": reason,
        }
        is_relevant, _why = relevance(story)
        if not is_relevant:
            continue
        known_links.add(url)
        out.append(story)
        if len(out) >= limit:
            break
    print(f"[TREND_RADAR] candidate_topics={len(out)} from_signals={len(signals)}")
    return out

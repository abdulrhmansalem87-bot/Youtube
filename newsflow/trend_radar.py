"""Tavily-backed trend radar: fresh news headlines used only to RANK stories we already collected.

A radar signal is never a fact and never a story. It has the same shape as a Google Trends
signal (see newsflow.discovery), so attach_trend_signals() boosts matching stories and nothing
else changes. Fact checking stays with the evidence gates. Only public query text is sent.

Cost: one basic Tavily search is 1 credit. Default is 3 searches per run
(NEWSFLOW_TREND_RADAR_QUERIES caps it; 0 turns the radar off). Fail-soft: any error returns [].
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

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

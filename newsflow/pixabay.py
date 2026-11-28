"""Pixabay video search: the licensed second B-roll source (insurance for Pexels).

Pixabay Content License allows free commercial use; attribution is not required but we credit every clip in the
description anyway. Pixabay asks that results are downloaded, not hotlinked, which broll._download already does
(cached). The free API allows 100 requests per 60 seconds. Docs: https://pixabay.com/api/docs/
License summary: https://pixabay.com/service/license-summary/
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

PIXABAY_API = "https://pixabay.com/api/videos/"
PIXABAY_LICENSE = "Pixabay Content License"
MIN_SECONDS = 2.5
MIN_SHORT_SIDE = 720
SIZE_ORDER = ("large", "medium", "small")


def _request_json(url: str) -> dict:
    """Retry transient failures. Errors never include the URL (it carries the key)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "WealthRadar-NewsFlow/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"تعذر جلب لقطات Pixabay (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError("تعذر الاتصال بـ Pixabay بعد ثلاث محاولات.") from None
        time.sleep(1.5 * (attempt + 1))


def search_videos(query: str, api_key: str, portrait: bool, request_json=_request_json) -> list[dict]:
    """Return candidates in the same shape as broll._search_videos (id, url, duration, photographer, page, provider).

    Pixabay has no orientation filter for video, so every orientation is accepted; the renderer cover-crops to the
    frame. Clips whose short side is under 720 px or shorter than 2.5 s are skipped.
    """
    params = urllib.parse.urlencode({
        "key": api_key, "q": query[:100], "video_type": "film", "per_page": 20, "safesearch": "true",
    })
    payload = request_json(f"{PIXABAY_API}?{params}")
    candidates = []
    for hit in payload.get("hits", []):
        duration = float(hit.get("duration") or 0)
        if duration < MIN_SECONDS:
            continue
        videos = hit.get("videos") or {}
        chosen = None
        for size in SIZE_ORDER:
            item = videos.get(size) or {}
            width, height = int(item.get("width") or 0), int(item.get("height") or 0)
            if item.get("url") and min(width, height) >= MIN_SHORT_SIDE:
                chosen = item
                break
        page = str(hit.get("pageURL") or "")
        if not chosen or not page.startswith("https://pixabay.com/"):
            continue
        candidates.append({
            "id": f"pixabay-{hit.get('id')}",
            "url": chosen["url"],
            "duration": duration,
            "photographer": str(hit.get("user") or ""),
            "page": page,
            "provider": "Pixabay",
        })
    if not candidates:
        raise RuntimeError(f"لم يعثر Pixabay على لقطات فيديو مناسبة لعبارة: {query}.")
    return candidates[:15]

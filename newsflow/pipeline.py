from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import html
import json
import unicodedata
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request

import edge_tts
import feedparser
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from newsflow.editorial import relevance, review_stories, upload_review_blockers
from newsflow.broll import render_broll_video

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def config():
    with (ROOT / "config" / "sources.yml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


MAX_BULLETIN_STORIES = 4
LOCAL_GOLD_MARKET_NAMES = (
    "مصر", "السعودية", "الإمارات", "الأردن", "العراق", "الكويت",
    "قطر", "البحرين", "عمان", "المغرب", "لبنان",
    "egypt", "saudi arabia", "uae", "jordan", "iraq", "kuwait",
    "qatar", "bahrain", "oman", "morocco", "lebanon",
)


def clamp_max_stories(value: int) -> int:
    return min(max(int(value), 1), MAX_BULLETIN_STORIES)


def validate_audio_duration(duration: float, *, private_test: bool = False) -> float:
    """Keep regular long-form bulletins in the 3–5 minute window; allow short private smoke tests."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        raise RuntimeError("مدة التعليق الصوتي غير صالحة؛ تم إيقاف بناء الفيديو.") from None
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("مدة التعليق الصوتي غير صالحة؛ تم إيقاف بناء الفيديو.")
    minimum = 1 if private_test else 240
    maximum = 300 if private_test else 480
    if value < minimum or value > maximum:
        target = "من 4 إلى 8 دقائق" if not private_test else "حتى 5 دقائق"
        raise RuntimeError(f"مدة الفيديو الرئيسي يجب أن تكون {target}؛ تم إيقاف الإنتاج.")
    return value


def story_topic_key(story: dict) -> str:
    title = str(story.get("title", "")).casefold()
    is_gold = "ذهب" in title or "gold" in title
    is_daily = "اليوم" in title or "today" in title
    is_local = any(name.casefold() in title for name in LOCAL_GOLD_MARKET_NAMES)
    is_gold_price = any(
        term in title for term in ("سعر الذهب", "أسعار الذهب", "جنيه الذهب", "gold price")
    )
    if is_gold and is_local and (is_daily or is_gold_price):
        return "daily-local-gold-price"
    return str(story.get("id") or title)


def select_stories(stories: list[dict], max_stories: int):
    selected, source_counts, rejected, seen_topics = [], {}, [], set()
    for story in stories:
        is_relevant, reason = relevance(story)
        if not is_relevant:
            rejected.append({
                "id": story.get("id"), "title": story.get("title"),
                "source": story.get("source"), "reasons": [reason],
            })
            continue
        topic_key = story_topic_key(story)
        if topic_key in seen_topics:
            continue
        source = story.get("source", "مصدر غير محدد")
        if source_counts.get(source, 0) >= 3:
            continue
        item = dict(story)
        item["relevance_reason"] = reason
        selected.append(item)
        seen_topics.add(topic_key)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= clamp_max_stories(max_stories):
            break
    return selected, rejected


def normalize_story_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        value = value.replace(source, target)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    stop = {
        "في", "من", "على", "عن", "الى", "إلى", "مع", "هذا", "هذه", "ذلك",
        "التي", "الذي", "بعد", "قبل", "اليوم", "امس", "غدا", "تقرير", "مصادر",
        "وسط", "بسبب", "حول", "هل", "كيف", "ما", "ماذا", "the", "a", "an",
        "of", "to", "for", "in", "on", "after", "amid", "as", "with",
    }
    return " ".join(token for token in value.split() if token not in stop)


def load_story_history() -> list[dict]:
    """Load persistent private-upload history plus the initial known duplicate seed."""
    history = []
    seed_path = ROOT / "content" / "wealthradar_history.json"
    runtime_path = ROOT / os.getenv(
        "NEWSFLOW_HISTORY_FILE", "output/history/used_stories.json"
    )
    for path in (seed_path, runtime_path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = payload.get("stories", []) if isinstance(payload, dict) else []
        if isinstance(items, list):
            history.extend(item for item in items if isinstance(item, dict))
    unique, seen = [], set()
    for item in reversed(history):
        key = str(item.get("id") or item.get("link") or item.get("title") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return list(reversed(unique))


def filter_recent_repeats(
    stories: list[dict], history: list[dict], now: datetime | None = None,
    lookback_days: int = 30,
) -> tuple[list[dict], list[dict]]:
    """Block previously uploaded stories and near-identical headlines for 30 days."""
    now = now or datetime.now(timezone.utc)
    eligible_history = []
    for previous in history:
        used_at = str(previous.get("used_at", "")).strip()
        if used_at:
            try:
                timestamp = datetime.fromisoformat(used_at.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if (now - timestamp).total_seconds() > lookback_days * 86400:
                    continue
            except ValueError:
                continue
        eligible_history.append(previous)

    selected, rejected = [], []
    for story in stories:
        story_id = str(story.get("id") or "")
        story_link = str(story.get("link") or "").split("?", 1)[0].rstrip("/")
        title = normalize_story_title(story.get("title", ""))
        tokens = set(title.split())
        duplicate = None
        for previous in eligible_history:
            old_id = str(previous.get("id") or "")
            old_link = str(previous.get("link") or "").split("?", 1)[0].rstrip("/")
            old_title = normalize_story_title(previous.get("title", ""))
            old_tokens = set(old_title.split())
            exact = bool(story_id and old_id and story_id == old_id)
            same_link = bool(story_link and old_link and story_link == old_link)
            ratio = difflib.SequenceMatcher(None, title, old_title).ratio() if title and old_title else 0
            overlap = (
                len(tokens & old_tokens) / len(tokens | old_tokens)
                if len(tokens | old_tokens) >= 3 else 0
            )
            same_topic = (
                story_topic_key(story) == str(previous.get("topic_key") or "")
                and story_topic_key(story) != story_id
            )
            if exact or same_link or ratio >= 0.82 or overlap >= 0.68 or same_topic:
                duplicate = previous
                break
        if duplicate:
            rejected.append({
                "id": story.get("id"), "title": story.get("title"),
                "source": story.get("source"),
                "reasons": ["موضوع سبق رفعه أو تجهيزه للمراجعة خلال آخر 30 يوماً؛ منعنا تكراره."],
            })
        else:
            selected.append(story)
    return selected, rejected


def record_story_as_used(story: dict, video_url: str) -> None:
    """Persist the lead story only after YouTube confirms its PRIVATE upload."""
    path = ROOT / os.getenv(
        "NEWSFLOW_HISTORY_FILE", "output/history/used_stories.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_story_history()
    history = [
        item for item in history
        if str(item.get("id") or "") != str(story.get("id") or "")
        and str(item.get("link") or "").split("?", 1)[0]
            != str(story.get("link") or "").split("?", 1)[0]
    ]
    history.append({
        "id": story.get("id"),
        "title": story.get("title"),
        "link": story.get("link"),
        "source": story.get("source"),
        "topic_key": story_topic_key(story),
        "used_at": datetime.now(timezone.utc).isoformat(),
        "video_url": video_url,
    })
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "stories": history[-100:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def caption_phrases(value: str, words_per_caption: int = 4) -> list[str]:
    """Make short Arabic captions that refresh on each moving B-roll cut."""
    words = clean_narration(value).split()
    return [
        " ".join(words[index:index + words_per_caption])
        for index in range(0, len(words), words_per_caption)
    ] or ["WealthRadar"]


def collect(max_stories: int):
    stories, seen = [], set()
    for source in config().get("sources", []):
        try:
            parsed = feedparser.parse(source["url"])
            for entry in parsed.entries[:40]:
                link = entry.get("link", "").strip()
                title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                published = entry.get("published", entry.get("updated", ""))
                published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                published_ts = datetime(*published_struct[:6], tzinfo=timezone.utc).timestamp() if published_struct else 0
                # Prefer the fullest RSS payload (content:encoded/content) over the
                # short display summary. The previous 280-character slice truncated
                # otherwise usable stories and caused editorial review to reject them.
                summary_candidates = [entry.get("summary", "")]
                summary_detail = entry.get("summary_detail") or {}
                summary_candidates.append(summary_detail.get("value", ""))
                for content_item in entry.get("content", []) or []:
                    if isinstance(content_item, dict):
                        summary_candidates.append(content_item.get("value", ""))
                raw_summary = max(summary_candidates, key=lambda value: len(str(value or "")), default="")
                summary = html.unescape(re.sub(r"<[^>]+>", " ", str(raw_summary or "")))
                summary = re.sub(r"\s+", " ", summary).strip()[:4000]
                stories.append({
                    "id": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title": title, "link": link, "published": published,
                    "published_ts": published_ts, "summary": summary,
                    "source": source["name"], "category": source.get("category", "عام"),
                })
        except Exception as exc:
            print(f"[WARN] تعذر جلب {source.get('name')}: {exc}")
    now_ts = datetime.now(timezone.utc).timestamp()
    try:
        lookback_hours = float(os.getenv("NEWSFLOW_LOOKBACK_HOURS", "72"))
    except (TypeError, ValueError):
        raise RuntimeError("NEWSFLOW_LOOKBACK_HOURS غير صالح؛ تم إيقاف اختيار الأخبار.")
    if not math.isfinite(lookback_hours) or lookback_hours <= 0:
        raise RuntimeError("NEWSFLOW_LOOKBACK_HOURS يجب أن يكون رقماً موجباً.")
    lookback_seconds = lookback_hours * 3600
    strict_freshness = os.getenv("NEWSFLOW_STRICT_FRESHNESS", "false").lower() == "true"
    stories = [
        item for item in stories
        if (
            (
                item["published_ts"] > 0
                and 0 <= now_ts - item["published_ts"] <= lookback_seconds
            )
            if strict_freshness else (
                not item["published_ts"]
                or 0 <= now_ts - item["published_ts"] <= lookback_seconds
            )
        )
    ]
    stories.sort(key=lambda item: item["published_ts"], reverse=True)
    selected, rejected = select_stories(stories, max_stories)
    for story in selected:
        story.pop("published_ts", None)
    return selected, rejected


LOCAL_IMPACT_LOOKBACK_HOURS = 12
LOCAL_IMPACT_TERMS = {
    "الوقود والطاقة": (
        "بنزين", "سولار", "وقود", "أسطوانة البوتاجاز", "اسطوانة البوتاجاز",
        "أنبوبة البوتاجاز", "الغاز الطبيعي", "أسعار الغاز", "أسعار الوقود",
        "سعر الوقود", "تسعيرة الوقود", "fuel prices", "fuel costs",
    ),
    "الكهرباء والمرافق": (
        "الكهرباء", "فاتورة الكهرباء", "شرائح الكهرباء", "تعريفة الكهرباء",
        "أسعار الكهرباء", "المياه", "فاتورة المياه", "تعريفة المياه",
        "power tariff", "electricity prices",
    ),
    "أسعار السلع والغذاء": (
        "الخبز", "رغيف العيش", "بطاقات التموين", "التموين", "السلع التموينية",
        "أسعار السلع", "السلع الغذائية", "أسعار الغذاء", "السكر", "الأرز",
        "الزيت", "اللحوم", "الدواجن", "البيض", "food prices",
    ),
    "الدخل والمعاشات": (
        "المعاشات", "أصحاب المعاشات", "صرف المعاش", "صرف المرتبات",
        "صرف الرواتب", "المرتبات", "الرواتب", "الأجور", "الحد الأدنى للأجور",
        "العلاوة", "تكافل وكرامة", "minimum wage", "pensions",
    ),
    "الجنيه والبنوك والفائدة": (
        "الجنيه المصري", "سعر الصرف", "سعر الدولار", "الدولار في مصر",
        "البنك المركزي المصري", "البنك المركزي", "أسعار الفائدة",
        "شهادات الادخار", "الودائع", "القروض", "التحويلات البنكية",
        "رسوم السحب", "رسوم التحويل", "egyptian pound", "central bank of egypt",
    ),
    "الضرائب والرسوم الحكومية": (
        "الضرائب", "ضريبة", "القيمة المضافة", "الجمارك", "رسوم الخدمات",
        "رسوم التراخيص", "رسوم التسجيل", "الإعفاء الضريبي", "الرسوم الحكومية",
        "customs fees", "tax changes",
    ),
    "المواصلات والخدمات": (
        "تذاكر المترو", "أسعار تذاكر", "تذكرة المترو", "القطارات",
        "السكة الحديد", "تعريفة المواصلات", "النقل العام", "رسوم الطرق",
        "رسوم المرور", "باقات الإنترنت", "أسعار الإنترنت", "أسعار الاتصالات",
        "باقات المحمول", "internet packages", "public transport fares",
    ),
    "السكن والإيجارات": (
        "الإيجار القديم", "الإيجارات", "قانون الإيجار", "الإيجار السكني",
        "زيادة الإيجار", "rent increases", "old rent law",
    ),
}
LOCAL_IMPACT_ACTION_TERMS = (
    "عاجل", "قرار", "قررت", "يقرر", "تقرر", "أعلن", "أعلنت", "إعلان",
    "زيادة", "ارتفاع", "رفع", "خفض", "تخفيض", "تراجع", "تثبيت", "تعديل",
    "تطبيق", "تنفيذ", "يبدأ", "تبدأ", "بدء", "اعتبارا من", "اعتبارًا من",
    "غدا", "غدًا", "اليوم", "الليلة", "موعد", "مواعيد", "سعر", "أسعار",
    "تعريفة", "رسوم", "إلغاء", "إيقاف", "وقف", "انقطاع", "تنقطع",
    "صرف", "مهلة", "إعفاء", "تمديد", "إتاحة", "حظر", "مواعيد جديدة",
    "effective", "increase", "decrease", "cut", "raise", "new price",
    "new fees", "will take effect", "starts", "from tomorrow",
)


def local_impact_category(story: dict) -> str | None:
    """Return a household-impact category only for concrete Egypt-facing changes."""
    title = str(story.get("title", ""))
    summary = str(story.get("summary", ""))
    blob = f"{title} {summary}".casefold()
    if not _has_any_local_term(blob, LOCAL_IMPACT_ACTION_TERMS):
        return None
    for category, terms in LOCAL_IMPACT_TERMS.items():
        if _has_any_local_term(blob, terms):
            return category
    return None


def _has_any_local_term(value: str, terms: tuple[str, ...]) -> bool:
    normalized = str(value or "").casefold()
    return any(term.casefold() in normalized for term in terms)


def _local_story_is_usable(story: dict, now_ts: float, lookback_hours: float) -> tuple[bool, str]:
    title = str(story.get("title", "")).strip()
    summary = str(story.get("summary", "")).strip()
    link = str(story.get("link", "")).strip()
    if len(title) < 12:
        return False, "عنوان الخبر قصير أو غير مكتمل"
    if len(summary) < 45 or summary.endswith(("...", "…", "[...]")):
        return False, "ملخص المصدر قصير أو مبتور"
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "رابط المصدر غير صالح"
    published_ts = float(story.get("published_ts", 0) or 0)
    if published_ts <= 0:
        return False, "تاريخ النشر غير متاح؛ لا يمكن إثبات أن الخبر مباشر"
    age = now_ts - published_ts
    if age < -300 or age > lookback_hours * 3600:
        return False, f"الخبر خارج نافذة التحديث المحلية ({lookback_hours:g} ساعة)"
    category = local_impact_category(story)
    if not category:
        return False, "الخبر محلي لكنه لا يتضمن تغييراً مباشراً في الأسعار أو الخدمات أو دخل الأسر"
    return True, category


def collect_local_impact_stories(now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Run an independent, strict-freshness sweep over Egypt-local RSS feeds."""
    now = now or datetime.now(timezone.utc)
    now_ts = now.timestamp()
    try:
        lookback_hours = float(os.getenv(
            "NEWSFLOW_LOCAL_LOOKBACK_HOURS", str(LOCAL_IMPACT_LOOKBACK_HOURS)
        ))
    except (TypeError, ValueError):
        raise RuntimeError("NEWSFLOW_LOCAL_LOOKBACK_HOURS غير صالح.")
    if not math.isfinite(lookback_hours) or lookback_hours <= 0:
        raise RuntimeError("NEWSFLOW_LOCAL_LOOKBACK_HOURS يجب أن يكون رقماً موجباً.")

    local_sources = [
        source for source in config().get("sources", [])
        if source.get("local_impact") is True
    ]
    candidates, rejected, seen = [], [], set()
    for source in local_sources:
        source_name = source.get("name", "مصدر محلي")
        try:
            parsed = feedparser.parse(source["url"])
            if getattr(parsed, "bozo", False) and not parsed.entries:
                rejected.append({"source": source_name, "reasons": ["تعذر قراءة موجز RSS"]})
                continue
            for entry in parsed.entries[:60]:
                link = str(entry.get("link", "")).strip()
                title = re.sub(r"\s+", " ", str(entry.get("title", ""))).strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                published_ts = (
                    datetime(*published_struct[:6], tzinfo=timezone.utc).timestamp()
                    if published_struct else 0
                )
                summary_candidates = [entry.get("summary", "")]
                summary_detail = entry.get("summary_detail") or {}
                summary_candidates.append(summary_detail.get("value", ""))
                for item in entry.get("content", []) or []:
                    if isinstance(item, dict):
                        summary_candidates.append(item.get("value", ""))
                raw_summary = max(
                    summary_candidates, key=lambda value: len(str(value or "")), default=""
                )
                summary = html.unescape(
                    re.sub(r"<[^>]+>", " ", str(raw_summary or ""))
                )
                summary = re.sub(r"\s+", " ", summary).strip()[:4000]
                story = {
                    "id": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title": title,
                    "link": link,
                    "published": entry.get("published", entry.get("updated", "")),
                    "published_ts": published_ts,
                    "summary": summary,
                    "source": source_name,
                    "category": source.get("category", "أخبار مصر المحلية"),
                    "local_impact_source": True,
                }
                usable, reason = _local_story_is_usable(story, now_ts, lookback_hours)
                if usable:
                    story["local_impact_category"] = reason
                    candidates.append(story)
                else:
                    rejected.append({
                        "id": story["id"], "title": title, "source": source_name,
                        "reasons": [reason],
                    })
        except Exception as exc:
            print(f"[LOCAL_IMPACT_WARN] تعذر جلب {source_name}: {type(exc).__name__}")
            rejected.append({
                "source": source_name,
                "reasons": [f"تعذر جلب الموجز: {type(exc).__name__}"],
            })
    candidates.sort(key=lambda item: item.get("published_ts", 0), reverse=True)
    return candidates, rejected


def select_local_impact_story(
    stories: list[dict], history: list[dict], excluded_stories: list[dict] | None = None
) -> tuple[dict | None, list[dict]]:
    """Select the freshest direct-impact story and attach independent matching sources."""
    excluded = list(history or [])
    excluded.extend(excluded_stories or [])
    eligible, repeated = filter_recent_repeats(stories, excluded)
    if not eligible:
        return None, repeated

    # Group nearly identical headlines from distinct publishers to retain corroboration.
    best_story = None
    best_sources: dict[str, dict] = {}
    best_score = (-1, -1.0)
    for story in eligible:
        category = story.get("local_impact_category") or local_impact_category(story)
        title = normalize_story_title(story.get("title", ""))
        tokens = set(title.split())
        matches = []
        for other in eligible:
            if other is story or other.get("local_impact_category") != category:
                continue
            other_title = normalize_story_title(other.get("title", ""))
            other_tokens = set(other_title.split())
            union = tokens | other_tokens
            overlap = len(tokens & other_tokens) / len(union) if union else 0
            ratio = difflib.SequenceMatcher(None, title, other_title).ratio()
            if ratio >= 0.55 or overlap >= 0.34:
                matches.append(other)
        sources = {str(story.get("source") or "مصدر محلي"): {
            "source": story.get("source"), "link": story.get("link")
        }}
        for match in matches:
            sources[str(match.get("source") or match.get("link"))] = {
                "source": match.get("source"), "link": match.get("link")
            }
        age = max(0.0, datetime.now(timezone.utc).timestamp() - float(story.get("published_ts", 0) or 0))
        score = (len(sources), -age)
        if score > best_score:
            best_story, best_sources, best_score = story, sources, score

    if not best_story:
        return None, repeated
    selected = dict(best_story)
    selected["corroborating_sources"] = list(best_sources.values())
    selected["corroboration_count"] = len(best_sources)
    selected["local_impact_category"] = best_story.get("local_impact_category") or local_impact_category(best_story)
    selected.pop("published_ts", None)
    return selected, repeated


def make_local_impact_short_script(story: dict) -> str:
    """Build a direct Egypt-facing Short without inventing an effect not in the source."""
    title = clean_narration(str(story.get("title", "")).strip())
    summary = clean_narration(str(story.get("summary", "")).strip())
    if not title or len(summary) < 45:
        raise ValueError("لا يمكن إعداد فيديو محلي من عنوان أو ملخص غير مكتمل.")
    summary = make_bulletin_summary(summary, limit=260)
    source = clean_narration(str(story.get("source", "المصدر المحلي")))
    return (
        f"الخبر ده يهم الناس في مصر: {title}. "
        f"بحسب {source}، {summary}. "
        "خلّينا نفرّق بين التصريح والقرار اللي بدأ تنفيذه فعلاً. "
        "راجع تاريخ التنفيذ والفئات اللي يشملها الخبر من المصدر الأصلي، "
        "وما تعتمدش على عنوان متداول من غير تفاصيل. "
        "هنفضل نتابع أي تحديث رسمي يغيّر الصورة. "
        "تابع WealthRadar عشان توصلك الأخبار المحلية اللي تمس حياتك مباشرة."
    )


def build_local_impact_metadata(story: dict, script: str) -> tuple[str, str, list[str]]:
    title_seed = clean_narration(str(story.get("title", "")).strip()).rstrip(" .،؛:؟!")
    if len(title_seed) > 62:
        title_seed = title_seed[:59].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    title = f"{title_seed} | WealthRadar #Shorts"
    category = str(story.get("local_impact_category") or local_impact_category(story) or "")
    if category == "الوقود والطاقة":
        topics = ("أسعار_الوقود", "الطاقة")
    elif category == "الكهرباء والمرافق":
        topics = ("الكهرباء", "خدمات_مصر")
    elif category == "أسعار السلع والغذاء":
        topics = ("أسعار_السلع", "تكلفة_المعيشة")
    elif category == "الدخل والمعاشات":
        topics = ("المعاشات", "المرتبات")
    elif category == "الجنيه والبنوك والفائدة":
        topics = ("الجنيه_المصري", "البنوك")
    elif category == "الضرائب والرسوم الحكومية":
        topics = ("قرارات_الحكومة", "الرسوم")
    elif category == "المواصلات والخدمات":
        topics = ("المواصلات", "خدمات_مصر")
    else:
        topics = ("الإيجارات", "اقتصاد_مصر")

    sources = story.get("corroborating_sources") or [{
        "source": story.get("source", "المصدر الأصلي"), "link": story.get("link", "")
    }]
    source_lines = "\n".join(
        f"{index}. {item.get('source', 'مصدر محلي')}: {item.get('link', '')}"
        for index, item in enumerate(sources, start=1)
    )
    description = (
        f"تحديث محلي من مصر: {title_seed}.\n"
        f"التصنيف: {category}. هذا الخبر مرتبط بتغيير أو خدمة تمس الأسر والمواطنين مباشرة.\n"
        f"ملخص المصدر: {make_bulletin_summary(story.get('summary', ''), 420)}\n\n"
        f"المصادر:\n{source_lines}\n\n"
        "نتابع المعلومة من مصدرها وتاريخها، ونفرّق بين الإعلان الرسمي والتوقع أو المقترح. "
        "ملاحظاتك بتساعدنا نطوّر WealthRadar. هذا محتوى إخباري وتوعوي وليس نصيحة مالية.\n\n"
        f"#shorts #WealthRadar #{topics[0]} #{topics[1]}"
    )
    tags = ["WealthRadar", "Shorts", "أخبار مصر", "أخبار محلية", category, *topics]
    return title[:100], description[:5000], tags[:30]


def produce_local_impact_short(
    story: dict, output: Path, upload_enabled: bool, auth_credentials=None
) -> str | None:
    """Render and optionally stage one separate Egypt-local impact Short as PRIVATE."""
    folder = output / "local-impact"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    script = make_local_impact_short_script(story)
    (folder / "script.txt").write_text(script, encoding="utf-8")
    audio = folder / "short.mp3"
    video = folder / "short.mp4"
    asyncio.run(make_audio(script, audio))
    title, description, tags = build_local_impact_metadata(story, script)
    (folder / "metadata.json").write_text(json.dumps({
        "title": title, "description": description, "tags": tags,
        "sources": story.get("corroborating_sources", []),
        "local_impact_category": story.get("local_impact_category"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    make_video(title, audio, video, short=True, stories=[story])
    validate_video(video, audio, expected_short=True)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe غير متاح لفحص الفيديو المحلي")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True, capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip())
    if not 35 <= duration <= 45:
        raise RuntimeError(f"Short الخبر المحلي يجب أن يكون 35–45 ثانية؛ المدة {duration:.1f} ثانية.")
    print(
        f"[LOCAL_IMPACT_SHORT_READY] {video} duration={duration:.1f}s "
        f"category={story.get('local_impact_category')} corroboration={story.get('corroboration_count', 1)}"
    )
    video_url = None
    if upload_enabled:
        video_url = youtube_upload(
            video, title, description, tags,
            privacy_override="private", credentials=auth_credentials
        )
        if video_url:
            record_story_as_used(story, video_url)
            print(f"[LOCAL_IMPACT_UPLOAD_VERIFIED] {video_url} privacy=private")
    else:
        print("[LOCAL_IMPACT_ARTIFACT_ONLY] YouTube upload is disabled")
    return video_url


def run_local_impact_sweep(
    output: Path, upload_enabled: bool, auth_credentials=None,
    excluded_stories: list[dict] | None = None,
) -> str | None:
    """After the regular episode, independently check for fresh Egypt-local impact news."""
    try:
        candidates, rejected = collect_local_impact_stories()
    except Exception as exc:
        print(f"[LOCAL_IMPACT_FAILED] {type(exc).__name__}: {exc}")
        return None
    (output / "local-impact").mkdir(parents=True, exist_ok=True)
    (output / "local-impact" / "review.json").write_text(
        json.dumps({
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "rejected": rejected,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    story, repeats = select_local_impact_story(
        candidates, load_story_history(), excluded_stories=excluded_stories
    )
    if not story:
        print(
            f"[LOCAL_IMPACT_NONE] fresh_direct_impact=0 candidates={len(candidates)} "
            f"rejected={len(rejected)} repeated={len(repeats)}"
        )
        return None
    (output / "local-impact" / "review.json").write_text(
        json.dumps({
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "rejected": rejected,
            "selected": story,
            "repeat_rejections": repeats,
            "fact_checking": "not_performed",
            "human_review_required": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[LOCAL_IMPACT_SELECTED] {story['title']} "
        f"category={story['local_impact_category']} sources={story.get('corroboration_count', 1)}"
    )
    return produce_local_impact_short(
        story, output, upload_enabled=upload_enabled, auth_credentials=auth_credentials
    )


def make_opening_hook(stories):
    """Lead with the strongest verified story in clear modern Arabic."""
    if not stories:
        return "ما أبرز ما يحرك الأسواق اليوم؟ إليك الصورة ببساطة."
    lead = clean_narration(stories[0].get("title", ""))
    lead = re.sub(r"^(عاجل|آخر الأخبار|أخبار اليوم)\s*[:：-]?\s*", "", lead, flags=re.I)
    if len(lead) > 115:
        lead = lead[:112].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    return f"{lead}. ما الذي حدث؟ ولماذا يهمك الخبر؟"


def make_bulletin_summary(value, limit=500):
    """Keep each story factual and concise so the long episode stays within 4–8 minutes."""
    summary = clean_narration(value)
    if len(summary) <= limit:
        return summary
    excerpt = summary[:limit]
    # Prefer a complete sentence; otherwise stop at a word boundary without inventing text.
    sentence_end = max(excerpt.rfind("؟"), excerpt.rfind("!"), excerpt.rfind("."))
    if sentence_end >= int(limit * 0.55):
        return excerpt[:sentence_end + 1].strip()
    return excerpt.rsplit(" ", 1)[0].rstrip("،؛:") + "…"


def make_topic_context(stories):
    """Add topic-specific explanation so a one-story long episode is substantive."""
    blob = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}"
        for item in stories
    ).casefold()
    if any(term in blob for term in ("البيتكوين", "بتكوين", "bitcoin", "عملات مشفرة", "crypto")):
        return (
            "وفي سوق العملات المشفرة، ينبغي قراءة حركة البيتكوين ضمن مؤشرات منفصلة: السعر، "
            "وحجم التداول، والسيولة المتاحة في منصات التداول. التراجع بنسبة معينة يصف ما حدث "
            "خلال فترة محددة فقط، ولا يشرح وحده السبب أو ما سيحدث لاحقاً. كذلك قد تختلف الأسعار "
            "بين المنصات بسبب توقيت القياس والسيولة، ولهذا نحدد وقت السعر ومصدره قبل المقارنة. "
            "ومن المهم التمييز بين حركة السوق وقرارات الجهات التنظيمية أو بيانات الشركات. "
            "لا نفترض أن انخفاض يوم واحد يؤكد اتجاهاً هابطاً طويل الأجل، ولا أن التعافي القصير "
            "يثبت عودة الصعود. نتابع أيضاً أحجام التداول والتغيرات في السيولة، ولا ننسب حركة "
            "السعر إلى تصفية مراكز أو خبر تنظيمي إلا إذا أكد المصدر ذلك."
        )
    if any(term in blob for term in ("فائدة", "الفيدرالي", "البنك المركزي", "interest rate", "central bank")):
        return (
            "وفي أخبار أسعار الفائدة، يجب الفصل بين قرار البنك المركزي وما تتوقعه الأسواق قبل "
            "الاجتماع. القرار الرسمي يصدر عن الجهة المختصة، أما احتمالات الرفع أو الخفض التي "
            "تعكسها العقود والأسواق فهي تقديرات تتغير مع كل بيان جديد. لفهم الاتجاه نتابع التضخم "
            "والأجور والنشاط الاقتصادي وتكلفة الاقتراض، ونقارنها بتاريخ كل تصريح. كما نميّز بين "
            "تأثير الفائدة على الودائع والقروض والسندات والعملات؛ فالأثر لا يظهر بالسرعة نفسها "
            "على جميع الأسواق، ولا يعني تغير توقع واحد أن القرار حُسم بالفعل."
        )
    if any(term in blob for term in ("ذهب", "gold")):
        return (
            "وفي سوق الذهب، من المهم التمييز بين السعر الفوري وسعر العقود الآجلة والسعر المحلي "
            "الذي قد يشمل فروق المصنعية والضرائب وهوامش التجار. ويتأثر المعدن بعوامل متعددة، "
            "منها الدولار والعوائد الحقيقية وتوقعات الفائدة والطلب على الملاذات الآمنة. لكن لا "
            "يكفي تزامن عاملين لإثبات أن أحدهما سبب الحركة. عند المقارنة نثبت وحدة القياس والعملة "
            "وتوقيت السعر، وننتبه إلى أن أسعار الأسواق العالمية لا تتحول بالضرورة إلى السعر "
            "نفسه في كل بلد. لذلك نقرأ الرقم في سياقه ولا نحوّله إلى توصية شراء أو بيع."
        )
    if any(term in blob for term in ("إنفيديا", "رقائق", "أشباه الموصلات", "ذكاء اصطناعي", "nvidia", "semiconductor")):
        return (
            "وفي أخبار شركات التكنولوجيا، لا تكفي حركة السهم وحدها لتقييم وضع الشركة. نراجع "
            "الإيرادات وهوامش الربح والتدفقات النقدية والإنفاق الرأسمالي والطلب الفعلي على "
            "المنتجات، ثم نقارن الأرقام بالفترة السابقة وتوقعات الإدارة. وقد يتحرك السهم بسبب "
            "توقعات المستثمرين قبل أن يظهر الأثر في النتائج المالية، لذلك نفرّق بين خبر عن "
            "الإدارة أو المنتج وبين تغير مثبت في الأرباح. وإذا لم يذكر المصدر علاقة مباشرة بين "
            "حدث معين والسعر، فلا ننسب الحركة إليه من دون دليل."
        )
    if any(term in blob for term in ("نفط", "طاقة", "غاز", "oil", "energy")):
        return (
            "وفي أسواق الطاقة، نتابع جانب العرض والطلب معاً: مستويات الإنتاج والمخزونات "
            "والاستهلاك وتكاليف النقل والتأمين. كما نفرّق بين سعر الخام الفوري والعقود الآجلة "
            "والأسعار التي تصل فعلياً إلى المستهلك. قد يضغط ارتفاع المخزونات على السعر، بينما "
            "تضيف مخاطر الإمدادات علاوة مؤقتة؛ لكن لا يمكن تحديد أثر أي عامل من دون بيانات "
            "تدعمه. لذلك نذكر وقت السعر ومصدره، ونفصل بين حركة جلسة واحدة والاتجاه الأسبوعي "
            "أو الشهري، ولا نقدّم توقعاً مؤكداً من قراءة مؤشر منفرد."
        )
    return (
        "ولكي نقيّم أي تطور مالي بصورة عملية، نحدد أولاً المقياس الذي تغير، والفترة التي يقارن "
        "بها، والجهة التي أعلنت الرقم. ثم نبحث عن المؤشرات التي قد تؤكد استمرار الأثر أو تشير "
        "إلى أنه مؤقت، ونقارن المعلومة بمصدر مستقل عندما يكون ذلك متاحاً. كما نفرّق بين السعر "
        "والقيمة، وبين التوقع والنتيجة المحققة، وبين التصريح والقرار الذي دخل حيز التنفيذ. "
        "إذا كانت البيانات غير مكتملة نقول ذلك بوضوح، وننتظر التحديث بدلاً من بناء استنتاج "
        "واسع على عنوان قصير أو رقم منفرد."
    )


def make_script(stories):
    parts = [
        make_opening_hook(stories),
        "أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar.",
        "سنقدم الوقائع المؤكدة، ونفصلها عن التحليل والتوقع."
    ]
    for index, story in enumerate(stories, start=1):
        # A one-story companion episode needs the fuller source detail, not a short bulletin excerpt.
        summary = make_bulletin_summary(
            story.get("summary", ""), limit=1800 if len(stories) == 1 else 500
        )
        if not summary:
            summary = "لم يرفق المصدر ملخصاً كافياً لهذا الخبر؛ راجعوا الرابط الأصلي للتفاصيل."
        parts.append(
            f"الخبر {index}: {clean_narration(story['title'])}. "
            f"{summary} بحسب {story['source']}."
        )
    parts.append(make_topic_context(stories))
    parts.extend([
        "كيف نقرأ الصورة؟ أول خطوة هي تحديد ما نعرفه بالفعل من الخبر، وما الذي ما زال مجرد احتمال. "
        "نراجع تاريخ المعلومة والجهة التي أعلنتها، وننتبه إلى ما إذا كان الرقم أولياً أم نهائياً، "
        "وهل يقارن الفترة نفسها أم فترة مختلفة. هذه التفاصيل الصغيرة تمنع الخلط بين تطور حقيقي "
        "وتغير ناتج عن طريقة العرض أو توقيت القياس.",
        "وفي متابعة الأسواق، لا تتحرك الأسعار بسبب عامل واحد دائماً. قد تتداخل تكلفة التمويل "
        "مع العرض والطلب وسعر العملة وتوقعات الشركات والمستهلكين. لذلك من الأفضل النظر إلى "
        "مجموعة المؤشرات معاً، وعدم نسبة أي تغير إلى سبب محدد ما لم يذكر المصدر دليلاً واضحاً "
        "على هذه العلاقة. وعندما تغيب البيانات الكافية، نقول بوضوح إن الصورة لم تكتمل بعد.",
        "ومن المهم أيضاً التمييز بين القرار الذي دخل حيز التنفيذ، والتصريح الذي يشرح توجهاً، "
        "والمقترح الذي ما زال قيد الدراسة. لكل واحد منها وزن مختلف في قراءة الخبر. كذلك فإن "
        "التمييز بين التوقعات والتحقق الفعلي يساعدنا على فهم ما إذا كانت حركة السوق استجابة "
        "لمعلومة مؤكدة أم لتقدير قد يتغير مع صدور بيانات جديدة.",
        "أما بالنسبة للأفراد والشركات، فقد يختلف الأثر بحسب الدخل والالتزامات وتكلفة التشغيل "
        "والقدرة على التمويل وتوقيت الشراء أو البيع. لهذا لا نقدم نتيجة واحدة باعتبارها مناسبة "
        "للجميع، ولا نحوّل خبراً عاماً إلى توصية شخصية. المطلوب هو فهم العوامل التي تستحق "
        "المتابعة، ثم الرجوع إلى المعلومات الرسمية التي تخص كل حالة.",
        "ولكي نقرأ الخبر بصورة عملية، نتابع ثلاثة أمور: ما الذي تأكد بالفعل، وما المؤشر الذي "
        "يمكن أن يثبت استمرار الأثر، وما المعلومة التي قد تغيّر التوقع الحالي. ففي أخبار الشركات "
        "نفرّق بين حركة السهم والنتائج التشغيلية والتدفقات النقدية، وفي أخبار السلع نفرّق بين "
        "السعر الفوري والعقود الآجلة وحجم المخزون. أما قرارات الفائدة والعملات فنربطها بتاريخ "
        "البيانات والجهة التي أصدرتها، ولا نعامل تسعير الأسواق لاحتمال معين على أنه قرار رسمي. "
        "بهذه الطريقة يصبح الخبر نقطة بداية للفهم، لا سبباً للتسرع.",
        "الخلاصة العملية: لا نبني قراراً مالياً على عنوان منفرد. تحققوا من المصدر الأصلي، "
        "ومن تاريخ الأرقام ووحدات القياس، وقارنوا المعلومة بأكثر من مصدر موثوق. وإذا ظهر "
        "تحديث أو تصحيح لاحق، يجب أن تتغير قراءتنا تبعاً له. المتابعة الهادئة والمنهجية "
        "أفضل من التسرع وراء حركة يوم واحد أو توقع غير مؤكد."
    ])
    parts.append(
        "كانت هذه أبرز أخبار المال والاقتصاد. روابط المصادر في وصف الفيديو، "
        "وقد تتغير الأرقام مع صدور بيانات جديدة. هذا موجز إخباري وتثقيفي وليس نصيحة استثمارية. "
        "ولا تنسوا الاشتراك في WealthRadar وتفعيل زر الجرس."
    )
    return "\\n\\n".join(parts)


def make_short_script(story):
    """Create a concise, source-grounded Arabic Short designed for 35–45 seconds."""
    title = clean_narration(str(story.get("title", "")).strip())
    summary = clean_narration(str(story.get("summary", "")).strip())
    if not title or not summary or len(summary) < 45:
        raise ValueError("لا يمكن إعداد Short من عنوان أو ملخص غير مكتمل.")
    if len(title) > 90:
        title = title[:87].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    # Keep the factual core short enough for the 35–45 second voice contract.
    # Never add a consequence that the source itself does not establish.
    if len(summary) > 160:
        summary = summary[:160].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    return (
        f"{title}. "
        f"{summary} "
        "واللي يهمك هنا: تابع المصدر والرقم الرسمي وتاريخه؛ فالتأثير بيختلف من شخص للتاني. "
        "إنت شايف التطور ده هيأثر على قراراتك المالية؟ اكتب رأيك. "
        "ده محتوى توعوي مش توصية استثمارية. ابعت الفيديو لحد يهمه واشترك في WealthRadar."
    )


def build_short_youtube_metadata(story, script, long_video_url=None):
    """Short-specific title, two-line benefit summary, numbered source and four hashtags."""
    title_seed = clean_narration(story.get("title", "")).rstrip(" .،؛:؟!")
    if len(title_seed) > 62:
        title_seed = title_seed[:59].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    title = f"{title_seed} | WealthRadar #Shorts"
    summary = clean_narration(story.get("summary", ""))[:220].rsplit(" ", 1)[0]
    topic = "الاقتصاد"
    second_topic = "الأسواق"
    blob = f"{story.get('title', '')} {story.get('summary', '')}".casefold()
    if "ذهب" in blob or "gold" in blob:
        topic, second_topic = "الذهب", "أسعار_الذهب"
    elif any(term in blob for term in ("دولار", "عملة", "عملات", "currency")):
        topic, second_topic = "الدولار", "العملات"
    elif any(term in blob for term in ("تضخم", "inflation", "أسعار المستهلك")):
        topic, second_topic = "التضخم", "الأسعار"
    elif any(term in blob for term in ("بورصة", "أسهم", "stocks", "market")):
        topic, second_topic = "البورصة", "الأسهم"
    elif any(term in blob for term in ("نفط", "طاقة", "oil")):
        topic, second_topic = "النفط", "الطاقة"
    elif any(term in blob for term in ("إنفيديا", "رقائق", "أشباه الموصلات", "ذكاء اصطناعي", "nvidia", "semiconductor", "ai ")):
        topic, second_topic = "الذكاء_الاصطناعي", "التكنولوجيا"
    elif any(term in blob for term in ("تهريب", "مضيق", "شحن", "ناقلات", "shipping")):
        topic, second_topic = "التجارة", "سلاسل_الإمداد"
    elif any(term in blob for term in ("عملات مشفرة", "بيتكوين", "باينانس", "crypto", "bitcoin")):
        topic, second_topic = "العملات_المشفرة", "الأصول_الرقمية"
    description = (
        f"في هذا الفيديو نفهم ببساطة: {title_seed}.\n"
        f"ملخص الخبر: {summary}.\n\n"
        f"المصادر:\n1. {story.get('source', 'المصدر الأصلي')}: {story.get('link', '')}\n"
        + (f"الحلقة الكاملة التي تشرح تفاصيل هذا الخبر: {long_video_url}\n" if long_video_url else "")
        + "\n"
        "بنحاول نقدّم لك المعلومة بأفضل صورة نقدر عليها، ولو حصلت هفوة بسيطة في الصوت فملاحظتك بتساعدنا نتحسن. "
        "بدعمك بنتطور سوا خطوة بخطوة. شكرًا إنك مع WealthRadar.\n\n"
        f"#shorts #WealthRadar #{topic.replace(' ', '_')} #{second_topic}"
    )
    tags = ["WealthRadar", "Shorts", "أخبار اقتصادية", topic, second_topic]
    return title[:100], description[:5000], tags


def build_youtube_metadata(stories, script):
    # Specific, curiosity-driven title based on the actual lead story; no fake urgency.
    lead_title = clean_narration((stories or [{}])[0].get("title", ""))
    lead_title = re.sub(r"^(عاجل|آخر الأخبار|أخبار اليوم)\s*[:：-]?\s*", "", lead_title, flags=re.I)
    if lead_title:
        lead_title = lead_title.rstrip(" .،؛:؟!")
        if len(lead_title) > 65:
            lead_title = lead_title[:62].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
        title = f"{lead_title[:58].rstrip()} | WealthRadar"
    else:
        title = "أهم تطورات المال والأسواق اليوم | WealthRadar"
    title = title[:100].rstrip()
    text_blob = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('category', '')}"
        for item in stories
    ).lower()
    keyword_map = [
        (("ذهب", "gold"), "الذهب"),
        (("دولار", "عملة", "عملات", "currency"), "الدولار"),
        (("بورصة", "أسهم", "سندات", "stocks", "market"), "البورصة"),
        (("بنك", "مصارف", "فائدة", "interest"), "البنوك"),
        (("نفط", "طاقة", "oil"), "النفط"),
        (("مصر", "مصري", "egypt"), "اقتصاد مصر"),
        (("استثمار", "invest"), "الاستثمار"),
    ]
    tags = ["WealthRadar", "أخبار اقتصادية", "أخبار المال", "الاقتصاد", "الأسواق"]
    for terms, tag in keyword_map:
        if any(term in text_blob for term in terms):
            tags.append(tag)
    tags = list(dict.fromkeys(tags))[:15]
    hashtags = ["#WealthRadar", "#أخبار_اقتصادية"]
    if any(term in text_blob for term in ("ذهب", "gold")):
        hashtags.extend(["#الذهب", "#أسعار_الذهب"])
    elif any(term in text_blob for term in ("دولار", "عملة", "currency")):
        hashtags.extend(["#الدولار", "#أسواق_العملات"])
    elif any(term in text_blob for term in ("بورصة", "أسهم", "stocks")):
        hashtags.extend(["#البورصة", "#الأسهم"])
    elif any(term in text_blob for term in ("إنفيديا", "رقائق", "ذكاء اصطناعي", "nvidia", "semiconductor")):
        hashtags.extend(["#الذكاء_الاصطناعي", "#التكنولوجيا"])
    elif any(term in text_blob for term in ("نفط", "طاقة", "oil")):
        hashtags.extend(["#النفط", "#الطاقة"])
    else:
        hashtags.extend(["#الاقتصاد", "#الأسواق"])
    source_lines = "\n".join(
        f"{i}. {item['source']}: {item['link']}"
        for i, item in enumerate(stories, start=1)
    )
    description = (
        "موجز WealthRadar اليومي لأهم تطورات المال والاقتصاد والأسواق. "
        "عناوين واضحة ومصادر مباشرة لمساعدتك على متابعة ما يحدث.\n\n"
        + script + "\n\nمصادر الأخبار وروابطها:\n" + source_lines
        + "\n\nبنحاول نقدّم لك المعلومة بأفضل صورة نقدر عليها، ولو حصلت هفوة بسيطة في الصوت فملاحظتك بتساعدنا نتحسن. "
        + "بدعمك بنتطور سوا خطوة بخطوة. شكرًا إنك مع WealthRadar.\n\n"
        + "هذا المحتوى إخباري وتثقيفي، ولا يُعد توصية أو نصيحة استثمارية. "
        + "تحقق من المصدر الأصلي قبل اتخاذ أي قرار مالي.\n\n"
        + " ".join(hashtags)
    )
    return title, description[:5000], tags

def clean_narration(value):
    """Normalize feed text before TTS to reduce awkward pauses and symbol readings."""
    import html
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u200f", " ").replace("\u200e", " ")
    # Keep Arabic brand/story names readable; remove English-only parenthetical aliases
    # that the Arabic card font cannot render consistently (e.g. "(Siemens Energy)").
    text = re.sub(r"\(\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\s*\)", " ", text)
    text = re.sub(r"[|*_~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.{2,}", ".", text)
    text = text.replace("…", "،")
    text = re.sub(r"\s*([،؛؟!])\s*", r"\1 ", text)
    # A period between digits is a decimal separator, not sentence punctuation.
    text = re.sub(r"(?<![0-9٠-٩۰-۹])\s*\.\s*|\.(?![0-9٠-٩۰-۹])\s*", ". ", text)
    return text.strip()


async def make_audio(text, path):
    """Generate the user's cloned WealthRadar voice through Fish Audio, then master it."""
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    reference_id = os.getenv("FISH_AUDIO_REFERENCE_ID", "").strip()
    model = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free").strip()
    if not api_key:
        raise RuntimeError("FISH_AUDIO_API_KEY غير موجود في GitHub Secrets؛ لن نستخدم صوتاً بديلاً.")
    if not reference_id:
        raise RuntimeError("FISH_AUDIO_REFERENCE_ID غير موجود في GitHub Secrets؛ لن نستخدم صوتاً بديلاً.")
    clean_text = clean_narration(text)
    payload = json.dumps(
        {"text": clean_text, "reference_id": reference_id, "format": "mp3"},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.fish.audio/v1/tts",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": model,
            "Accept": "audio/mpeg",
            "User-Agent": "WealthRadarNewsFlow/1.0",
        },
        method="POST",
    )
    raw_path = path.with_name(path.stem + ".raw.mp3")
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        detail = " ".join(detail.split()).replace(api_key, "[REDACTED]")[:300]
        raise RuntimeError(
            f"Fish Audio رفض توليد الصوت (HTTP {exc.code}). "
            f"{detail or 'راجع المفتاح والرصيد وVoice ID واسم النموذج.'}"
        ) from None
    if len(audio) < 1000:
        raise RuntimeError("Fish Audio أعاد ملفاً صوتياً فارغاً أو غير مكتمل.")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(audio)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.move(str(raw_path), str(path))
        print(f"[VOICE_READY] Fish Audio | model={model} | mastering=skipped")
        return
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(raw_path),
                "-af",
                "highpass=f=75,lowpass=f=12500,"
                "acompressor=threshold=-18dB:ratio=2.2:attack=18:release=220,"
                "loudnorm=I=-16:TP=-1.5:LRA=10",
                "-codec:a", "libmp3lame", "-q:a", "2", str(path),
            ],
            check=True, capture_output=True,
        )
    finally:
        raw_path.unlink(missing_ok=True)
    print(f"[VOICE_READY] Fish Audio cloned voice | model={model} | bytes={path.stat().st_size}")


def find_font(bold=False):
    candidates = (
        [
            "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ] if bold else [
            "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for item in candidates:
        if Path(item).exists():
            return item
    return None


SOURCE_DISPLAY_NAMES = {
    "CNBC عربية - أسواق المال": "سي إن بي سي عربية - أسواق المال",
    "CNBC عربية - أخبار الشركات": "سي إن بي سي عربية - أخبار الشركات",
    "BBC Arabic": "بي بي سي عربي",
    "Al Jazeera": "الجزيرة",
    "IMF": "صندوق النقد الدولي",
    "UN News Arabic": "أخبار الأمم المتحدة",
}


def source_display_name(value: str) -> str:
    return SOURCE_DISPLAY_NAMES.get(str(value or "").strip(), "مصدر الخبر")


def make_video(title, audio, output, short=False, stories=None, portrait=None):
    # A vertical long-form video is still a regular video; only Shorts have a 180s cap.
    portrait = short if portrait is None else portrait
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe غير متاح للتحقق من مدة الصوت")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True, capture_output=True, text=True,
    )
    total_duration = float(probe.stdout.strip())
    story_list = stories or []
    cards = [{
        "heading": "المقدمة",
        "title": make_opening_hook(story_list),
        "body": "أهم تطورات المال والأسواق، من غير تهويل وبالمصادر",
        "captions": caption_phrases(make_opening_hook(story_list)),
    }]
    for index, story in enumerate(story_list, start=1):
        story_title = clean_narration(story.get("title", ""))
        story_summary = clean_narration(story.get("summary", ""))
        cards.append({
            "heading": f"الخبر {index:02d}، {source_display_name(story.get('source', 'المصدر'))}",
            "title": story_title,
            "body": story_summary[:180] or "راجع رابط المصدر لمعرفة التفاصيل الكاملة.",
            "captions": caption_phrases(f"{story_title}. {story_summary[:1800]}"),
        })
    cards.append({
        "heading": "الخلاصة",
        "title": "قبل أي قرار مالي",
        "body": "تابع المصدر الأصلي وقارن المعلومات. اشترك في WealthRadar وفعّل زر الجرس لمتابعة الموجز القادم.",
        "captions": caption_phrases(
            "تابع المصدر الأصلي وقارن المعلومات قبل أي قرار مالي واشترك في WealthRadar"
        ),
    })

    weights = [max(90, len(card["title"]) + len(card["body"])) for card in cards]
    weight_total = sum(weights)
    durations = [total_duration * weight / weight_total for weight in weights]
    durations[-1] += total_duration - sum(durations)

    # NewsFlow must use licensed moving footage. Missing Pexels credentials or
    # footage are fatal: never silently fall back to animated still cards.
    render_broll_video(cards, durations, audio, output, portrait=portrait)
    print(f"[BROLL_RENDER_COMPLETE] cards={len(cards)} orientation={'portrait' if portrait else 'landscape'}")

def validate_video(
    video_path: Path,
    audio_path: Path,
    expected_short: bool = False,
    expected_portrait: bool | None = None,
):
    expected_portrait = expected_short if expected_portrait is None else expected_portrait
    if expected_short and not expected_portrait:
        raise RuntimeError("يجب أن تكون مقاطع Shorts رأسية.")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe غير متاح للتحقق من الفيديو")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height",
         "-of", "json", str(video_path)],
        check=True, capture_output=True, text=True
    )
    data = json.loads(probe.stdout)
    streams = data.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise RuntimeError("فشل فحص الفيديو: لا يوجد مسار صورة")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("فشل فحص الفيديو: لا يوجد مسار صوت")
    duration = float(data.get("format", {}).get("duration", 0))
    video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    expected_dimensions = (1080, 1920) if expected_portrait else (1920, 1080)
    if (width, height) != expected_dimensions:
        orientation = "رأسياً" if expected_portrait else "أفقياً"
        raise RuntimeError(
            f"فشل فحص أبعاد الفيديو: يجب أن يكون {orientation} بمقاس "
            f"{expected_dimensions[0]}×{expected_dimensions[1]}، والموجود {width}×{height}"
        )
    if expected_short and duration > 180:
        raise RuntimeError("فشل فحص النسخة القصيرة: المدة تتجاوز 3 دقائق")
    audio_probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        check=True, capture_output=True, text=True
    )
    audio_duration = float(audio_probe.stdout.strip())
    if duration <= 0 or abs(duration - audio_duration) > 2.5:
        raise RuntimeError(
            f"فشل فحص تزامن الصوت والصورة: video={duration:.2f}s audio={audio_duration:.2f}s"
        )
    if video_path.stat().st_size < 100_000:
        raise RuntimeError("حجم الفيديو صغير بشكل غير طبيعي؛ تم إيقاف الرفع")
    print(f"[VIDEO_QA_OK] duration={duration:.1f}s bytes={video_path.stat().st_size}")

def create_youtube_credentials():
    from google.oauth2.credentials import Credentials
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("أسرار YouTube ناقصة في GitHub Secrets: " + ", ".join(missing))
    return Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )


def validate_youtube_auth():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    creds = create_youtube_credentials()
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        if "invalid_grant" in str(exc):
            raise RuntimeError(
                "فشل تجديد صلاحية YouTube (invalid_grant). غالباً Refresh Token منتهي أو ملغي، "
                "أو لا يطابق Client ID وClient Secret. أنشئ Refresh Token جديداً من نفس OAuth Client "
                "وحدّث أسرار GitHub الثلاثة معاً. إذا كان التطبيق في وضع Testing فقد تنتهي صلاحية "
                "Refresh Token بعد 7 أيام. لم يتم رفع أي فيديو."
            ) from None
        raise RuntimeError(
            "تعذر تجديد صلاحية YouTube؛ راجع إعدادات OAuth وGitHub Secrets. لم يتم رفع أي فيديو. "
            + type(exc).__name__
        ) from None
    if not creds.valid:
        raise RuntimeError("Google لم يؤكد صلاحية Access Token؛ لم يتم رفع أي فيديو.")
    print("[AUTH_OK] تم تجديد صلاحية YouTube بنجاح.")
    return creds


def resolve_upload_privacy(privacy_override: str | None = None) -> str:
    status = str(
        privacy_override or os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
    ).strip().lower()
    if status != "private":
        raise ValueError("WealthRadar uploads are restricted to PRIVATE privacy.")
    return status


def verify_target_channel(youtube, expected_title: str | None = None) -> str:
    """Verify the authenticated account owns exactly one WealthRadar channel before upload."""
    expected = str(
        expected_title or os.getenv("YOUTUBE_EXPECTED_CHANNEL_TITLE", "WealthRadar")
    ).strip().casefold()
    try:
        response = youtube.channels().list(
            part="snippet", mine=True, maxResults=50
        ).execute()
    except Exception:
        raise RuntimeError(
            "تعذر التحقق من قناة WealthRadar عبر channels.list(mine=true). "
            "لن يتم رفع أي فيديو؛ قد لا تتضمن صلاحية OAuth الحالية القراءة المطلوبة."
        ) from None
    matches = [
        item for item in response.get("items", [])
        if str(item.get("snippet", {}).get("title", "")).strip().casefold() == expected
    ]
    if len(matches) != 1 or not matches[0].get("id"):
        raise RuntimeError(
            "تعذر تأكيد قناة WealthRadar المستهدفة بشكل فريد؛ تم إيقاف الرفع."
        )
    channel_id = str(matches[0]["id"])
    print(f"[CHANNEL_VERIFIED] title={expected_title or 'WealthRadar'} id={channel_id}")
    return channel_id


def youtube_upload(
    video_path: Path, title: str, description: str, tags: list[str],
    privacy_override: str | None = None, credentials=None
):
    if os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() != "true":
        print("[SAFE] رفع يوتيوب معطل. الفيديو محفوظ كـ Artifact.")
        return
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = credentials or create_youtube_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    status = resolve_upload_privacy(privacy_override)
    target_channel_id = verify_target_channel(youtube)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags,
                    "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "25"),
                    "defaultLanguage": "ar", "defaultAudioLanguage": "ar"},
        "status": {"privacyStatus": status, "selfDeclaredMadeForKids": False},
    }
    request = youtube.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = request.execute()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube لم يُرجع معرّف الفيديو بعد الرفع")
    returned_status = response.get("status", {}).get("privacyStatus")
    returned_channel_id = response.get("snippet", {}).get("channelId")
    if returned_status != status:
        raise RuntimeError("استجابة YouTube لم تؤكد الخصوصية المطلوبة؛ لن نعلن نجاح التحقق.")
    if returned_channel_id != target_channel_id:
        raise RuntimeError("استجابة YouTube لا تطابق القناة التي تم التحقق منها؛ لن نعلن نجاح الرفع.")
    video_url = f"https://youtu.be/{video_id}"
    print(f"[UPLOAD_VERIFIED] {video_url} privacy={status} channel={target_channel_id}")
    return video_url

def main():
    parser = argparse.ArgumentParser(description="WealthRadar Arabic financial news pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Collect and write drafts only")
    parser.add_argument("--max-stories", type=int, default=int(os.getenv("NEWSFLOW_MAX_STORIES", "4")))
    parser.add_argument("--private-test", action="store_true", help="Upload exactly one long video with private privacy after manual approvals")
    parser.add_argument("--render-only", action="store_true", help="Render the long episode and companion Shorts as review artifacts; never upload")
    parser.add_argument("--private-staging", action="store_true", help="Scheduled production: render bulletin and Shorts and upload as PRIVATE for owner review")
    parser.add_argument("--shorts-only", action="store_true", help="Render and stage one story-specific Short only; never render the long bulletin")
    args = parser.parse_args()
    args.max_stories = clamp_max_stories(args.max_stories)
    if (args.private_test or args.private_staging) and args.dry_run:
        parser.error("Private production modes cannot be combined with --dry-run")
    if args.private_test and args.private_staging:
        parser.error("Choose either manual private-test or scheduled private-staging, not both")
    if args.shorts_only and not args.private_staging:
        parser.error("--shorts-only is restricted to PRIVATE staging")
    if args.shorts_only and args.private_test:
        parser.error("--shorts-only cannot be combined with --private-test")
    if not args.dry_run and not args.private_test and not args.private_staging and not args.render_only:
        parser.error("الرندر الكامل محظور؛ استخدم --dry-run أو وضع PRIVATE المعتمد.")
    staging_env = os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true"
    if args.private_staging and not staging_env:
        parser.error("--private-staging is allowed only for the scheduled staging workflow")
    if not args.private_staging and staging_env:
        parser.error("NEWSFLOW_PRIVATE_STAGING requires --private-staging")
    upload_enabled = os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() == "true"
    if args.render_only and upload_enabled:
        parser.error("--render-only refuses to run while YouTube uploads are enabled.")
    editorial_approved = os.getenv("NEWSFLOW_EDITORIAL_APPROVED", "false").lower() == "true"
    private_staging = os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true"
    visual_qa_approved = os.getenv("NEWSFLOW_VISUAL_QA_APPROVED", "false").lower() == "true"
    if upload_enabled and not editorial_approved and not args.private_staging:
        parser.error("الرفع محظور: يلزم اعتماد المراجعة التحريرية صراحةً عبر NEWSFLOW_EDITORIAL_APPROVED=true.")
    if args.private_staging and not upload_enabled:
        parser.error("Scheduled private staging requires YOUTUBE_UPLOAD_ENABLED=true")
    if args.private_test:
        args.max_stories = 1
        if not upload_enabled:
            parser.error("Private test requires YOUTUBE_UPLOAD_ENABLED=true")
        if not visual_qa_approved:
            parser.error("Private test requires explicit phone visual QA approval.")
    # Verify OAuth before spending time generating audio/video.
    auth_credentials = None
    if args.private_test or args.private_staging or (not args.dry_run and upload_enabled):
        try:
            auth_credentials = validate_youtube_auth()
        except RuntimeError as exc:
            parser.error(str(exc))
    out = ROOT / os.getenv("NEWSFLOW_OUTPUT_DIR", "output")
    out.mkdir(parents=True, exist_ok=True)
    stories, filtered_stories = collect(args.max_stories)
    editorial_report = review_stories(stories)
    editorial_report["rejected"].extend(filtered_stories)
    editorial_report["rejected_count"] += len(filtered_stories)
    (out / "editorial_review.json").write_text(
        json.dumps(editorial_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stories = editorial_report["accepted"]
    stories, repeat_rejections = filter_recent_repeats(stories, load_story_history())
    if repeat_rejections:
        editorial_report["rejected"].extend(repeat_rejections)
        editorial_report["rejected_count"] += len(repeat_rejections)
    editorial_report["accepted"] = stories
    editorial_report["accepted_count"] = len(stories)
    editorial_report["status"] = "needs_human_review" if stories else "blocked"
    (out / "editorial_review.json").write_text(
        json.dumps(editorial_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[EDITORIAL_REVIEW] status={editorial_report['status']} accepted={editorial_report['accepted_count']} rejected={editorial_report['rejected_count']} warnings={editorial_report['warning_count']} fact_checking=not_performed")
    upload_blockers = upload_review_blockers(editorial_report, editorial_approved, private_staging=args.private_staging)
    if args.private_test and upload_blockers:
        print("[SAFE] PRIVATE test blocked before rendering: " + " | ".join(upload_blockers))
        return
    if upload_enabled and not visual_qa_approved and not args.private_staging:
        print("[SAFE] PRIVATE upload blocked: phone visual QA has not been explicitly approved.")
        upload_enabled = False
    if upload_enabled and upload_blockers:
        print("[SAFE] PRIVATE upload blocked: " + " | ".join(upload_blockers)
              + ". Generated video will remain an Artifact.")
        upload_enabled = False
    if not stories:
        message = "لا توجد أخبار اجتازت المراجعة التحريرية؛ لم يتم إنتاج فيديو."
        print("[BLOCKED] " + message)
        if args.render_only or args.private_staging:
            raise RuntimeError(message)
        return
    for story in stories:
        folder = out / story["id"]
        folder.mkdir(exist_ok=True)
        (folder / "script.txt").write_text(make_script([story]), encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DRAFT] {story['title']} — {story['link']}")

    # The long episode is a multi-story bulletin. Its lead story is also the source
    # for the companion Short, so both formats stay editorially connected.
    companion_story = stories[0]
    companion_stories = [companion_story]
    # The companion long episode must explain the exact same single lead story as its Short.
    bulletin_stories = [companion_story]
    bulletin_script = make_script(bulletin_stories)
    (out / "companion_story.json").write_text(
        json.dumps(companion_story, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[COMPANION_TOPIC] long episode + Shorts story={companion_story['id']}")
    bulletin = out / "bulletin"
    bulletin.mkdir(exist_ok=True)
    (bulletin / "script.txt").write_text(bulletin_script, encoding="utf-8")
    (bulletin / "stories.json").write_text(
        json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.dry_run:
        return

    if args.shorts_only:
        # Reuse the already-proven Fish Audio + NewsFlow vertical renderer.
        # This path deliberately creates exactly one story-specific Short and no long video.
        shorts_dir = bulletin / "shorts"
        shorts_dir.mkdir(exist_ok=True)
        story = stories[0]
        short_script = make_short_script(story)
        short_audio = shorts_dir / "short-1.mp3"
        short_video = shorts_dir / "short-1.mp4"
        asyncio.run(make_audio(short_script, short_audio))
        short_title, short_description, short_tags = build_short_youtube_metadata(story, short_script)
        (shorts_dir / "short-1.youtube-metadata.json").write_text(
            json.dumps(
                {"title": short_title, "description": short_description, "tags": short_tags, "privacyStatus": "private"},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        make_video(short_title, short_audio, short_video, short=True, stories=[story])
        validate_video(short_video, short_audio, expected_short=True)
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise RuntimeError("FFprobe غير متاح للتحقق من مدة Short")
        short_probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(short_audio)],
            check=True, capture_output=True, text=True,
        )
        short_duration = float(short_probe.stdout.strip())
        if not 35 <= short_duration <= 45:
            raise RuntimeError(
                f"مدة Short يجب أن تكون بين 35 و45 ثانية؛ المدة الحالية {short_duration:.1f} ثانية."
            )
        print(f"[SHORT_READY] {short_video} duration={short_duration:.1f}s story={story['id']}")
        if upload_enabled:
            youtube_upload(
                short_video, short_title, short_description, short_tags,
                privacy_override="private", credentials=auth_credentials
            )
        else:
            print("[SAFE] Short rendered but not uploaded; upload approval is disabled.")
        return

    audio = bulletin / "voice.mp3"
    asyncio.run(make_audio(bulletin_script, audio))
    ffprobe = shutil.which("ffprobe")
    main_portrait = os.getenv("NEWSFLOW_MAIN_VIDEO_PORTRAIT", "false").lower() == "true"
    duration = None
    if ffprobe:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            check=True, capture_output=True, text=True
        )
        measured_duration = float(probe.stdout.strip())
        print(f"[AUDIO_DURATION_MEASURED] {measured_duration:.1f} seconds")
        duration = validate_audio_duration(measured_duration, private_test=args.private_test)
        print(f"[AUDIO_DURATION] {duration:.1f} seconds (duration follows editorial content)")

    single_long_upload = os.getenv("NEWSFLOW_UPLOAD_SINGLE_LONG", "false").lower() == "true"
    video_title, description, tags = build_youtube_metadata(bulletin_stories, bulletin_script)
    (bulletin / "long.youtube-metadata.json").write_text(
        json.dumps(
            {"title": video_title, "description": description, "tags": tags, "privacyStatus": "private"},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[YOUTUBE_METADATA] title={video_title} | words={len(video_title.split())} | tags={len(tags)}")

    long_video = bulletin / "long.mp4"
    make_video(video_title, audio, long_video, short=False, portrait=main_portrait, stories=bulletin_stories)
    validate_video(long_video, audio, expected_portrait=main_portrait)
    if args.private_test:
        if upload_enabled:
            youtube_upload(
                long_video, video_title, description, tags,
                privacy_override="private", credentials=auth_credentials
            )
        else:
            print("[SAFE] PRIVATE upload skipped; generated video remains an Artifact.")
        return
    if args.private_staging:
        print("[PRIVATE_STAGING] Uploading validated long video and story Shorts as PRIVATE only.")
    long_video_url = None
    if upload_enabled:
        long_video_url = youtube_upload(
            long_video, video_title, description, tags,
            privacy_override="private", credentials=auth_credentials
        )
        if long_video_url:
            record_story_as_used(companion_story, long_video_url)
            print(f"[HISTORY_RECORDED] story={companion_story.get('id')} after PRIVATE upload")
    else:
        print("[SAFE] Long episode rendered; no YouTube upload is enabled.")

    # Companion Shorts are derived only from the same lead story as the long episode.
    if not single_long_upload:
        shorts_dir = bulletin / "shorts"
        shorts_dir.mkdir(exist_ok=True)
        for index, story in enumerate(companion_stories, start=1):
            short_script = make_short_script(story)
            short_audio = shorts_dir / f"short-{index}.mp3"
            short_video = shorts_dir / f"short-{index}.mp4"
            asyncio.run(make_audio(short_script, short_audio))
            short_title, short_description, short_tags = build_short_youtube_metadata(
                story, short_script, long_video_url=long_video_url
            )
            (shorts_dir / f"short-{index}.youtube-metadata.json").write_text(
                json.dumps(
                    {"title": short_title, "description": short_description, "tags": short_tags, "privacyStatus": "private"},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            make_video(short_title, short_audio, short_video, short=True, stories=[story])
            validate_video(short_video, short_audio, expected_short=True)
            short_probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(short_audio)],
                check=True, capture_output=True, text=True,
            )
            short_duration = float(short_probe.stdout.strip())
            if not 35 <= short_duration <= 45:
                raise RuntimeError(
                    f"مدة Short يجب أن تكون بين 35 و45 ثانية؛ المدة الحالية {short_duration:.1f} ثانية."
                )
            print(f"[SHORT_READY] {short_video} duration={short_duration:.1f}s story={story['id']}")
            if upload_enabled:
                youtube_upload(
                    short_video, short_title, short_description, short_tags,
                    privacy_override="private" if args.private_staging else os.getenv("YOUTUBE_PRIVACY_STATUS", "private"), credentials=auth_credentials
                )


if __name__ == "__main__":
    main()

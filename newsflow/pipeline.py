from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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
from newsflow.history import filter_recent_repeats, load_story_history, record_story_history
from newsflow.broll import render_broll_video
from newsflow.source_evidence import collect_source_evidence
from newsflow.fact_check import fact_check_stories
from newsflow.scriptwriter import generate_plan, is_arabic_text
from newsflow.trend_radar import fetch_signals as fetch_radar_signals, radar_candidates
from newsflow.discovery import attach_trend_signals, is_trend_source, parse_trend_signal

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def story_history_path() -> Path:
    raw = Path(os.getenv("NEWSFLOW_HISTORY_FILE", "output/history/used_stories.json"))
    return raw if raw.is_absolute() else ROOT / raw


def config():
    with (ROOT / "config" / "sources.yml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


MAX_BULLETIN_STORIES = 5
LOCAL_GOLD_MARKET_NAMES = (
    "مصر", "السعودية", "الإمارات", "الأردن", "العراق", "الكويت",
    "قطر", "البحرين", "عمان", "المغرب", "لبنان",
    "egypt", "saudi arabia", "uae", "jordan", "iraq", "kuwait",
    "qatar", "bahrain", "oman", "morocco", "lebanon",
)


def clamp_max_stories(value: int) -> int:
    return min(max(int(value), 1), MAX_BULLETIN_STORIES)


def validate_audio_duration(duration: float, *, private_test: bool = False) -> float:
    """Keep regular long-form episodes within 4–8 minutes; allow short private smoke tests."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        raise RuntimeError("مدة التعليق الصوتي غير صالحة؛ تم إيقاف بناء الفيديو.") from None
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("مدة التعليق الصوتي غير صالحة؛ تم إيقاف بناء الفيديو.")
    minimum = 1 if private_test else 240
    maximum = 480
    if value < minimum or value > maximum:
        target = "من 4 إلى 8 دقائق" if not private_test else "من ثانية إلى 8 دقائق"
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
    ordered_stories = sorted(
        stories,
        key=lambda item: (float(item.get("trend_score") or 0), float(item.get("published_ts") or 0)),
        reverse=True,
    )
    for story in ordered_stories:
        is_relevant, reason = relevance(story)
        if not is_relevant:
            rejected.append({
                "id": story.get("id"), "title": story.get("title"),
                "source": story.get("source"), "reasons": [reason],
            })
            continue
        # Do not let an incomplete top-ranked RSS item consume the story limit.
        # RSS summaries are frequently truncated or absent. Do not discard a story
        # for that reason: fetch the original publisher page below and use its readable
        # article text for fact-checking and narration instead.
        link = str(story.get("link") or "").strip()
        parsed_link = urlparse(link)
        completeness_reasons = []
        if len(str(story.get("title") or "").strip()) < 12:
            completeness_reasons.append("عنوان قصير أو غير مكتمل")
        if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
            completeness_reasons.append("رابط المصدر غير صالح")
        if not str(story.get("published") or "").strip():
            completeness_reasons.append("تاريخ النشر غير متاح")
        if completeness_reasons:
            rejected.append({
                "id": story.get("id"), "title": story.get("title"),
                "source": story.get("source"), "reasons": completeness_reasons,
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


def collect(max_stories: int):
    stories, seen, trend_signals = [], set(), []
    for source in config().get("sources", []):
        try:
            parsed = feedparser.parse(source["url"])
            if is_trend_source(source):
                trend_signals.extend(
                    signal for entry in parsed.entries[:40]
                    if (signal := parse_trend_signal(entry, source)) is not None
                )
                continue
            for entry in parsed.entries[:40]:
                link = entry.get("link", "").strip()
                title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                published = entry.get("published", entry.get("updated", ""))
                published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                published_ts = datetime(*published_struct[:6], tzinfo=timezone.utc).timestamp() if published_struct else 0
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
                summary = re.sub(r"\s+", " ", summary).strip()[:280]
                stories.append({
                    "id": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title": title, "link": link, "published": published,
                    "published_ts": published_ts, "summary": summary,
                    "source": source["name"], "category": source.get("category", "عام"),
                })
        except Exception as exc:
            print(f"[WARN] تعذر جلب {source.get('name')}: {exc}")
    # Tavily radar: extra ranking signals only, fail-soft, never a fact source.
    radar_signals = fetch_radar_signals()
    trend_signals.extend(radar_signals)
    stories = attach_trend_signals(stories, trend_signals)
    # Unmatched radar signals with a clear money angle join as ordinary candidates and face every gate.
    stories.extend(radar_candidates(radar_signals, stories))
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
    recent_repeats = []
    if os.getenv("NEWSFLOW_DEDUPE_HISTORY_ENABLED", "false").lower() == "true":
        history = load_story_history(story_history_path())
        stories, recent_repeats = filter_recent_repeats(stories, history, cooldown_hours=24 * 30)
    # Keep a small candidate buffer so an inaccessible or unsupported lead does
    # not consume the whole bulletin limit; final output is capped after fact-checking.
    candidate_limit = min(clamp_max_stories(max_stories) + 3, MAX_BULLETIN_STORIES + 3)
    selected, rejected = select_stories(stories, candidate_limit)
    rejected.extend(recent_repeats)
    for story in selected:
        story.pop("published_ts", None)
    return selected, rejected

def make_opening_hook(stories):
    """Lead with the strongest verified story in clear modern Arabic."""
    if not stories:
        return "ما أبرز ما يحرك الأسواق اليوم؟ إليك الصورة ببساطة."
    lead = clean_narration(stories[0].get("title", ""))
    lead = re.sub(r"^(عاجل|آخر الأخبار|أخبار اليوم)\s*[:：-]?\s*", "", lead, flags=re.I)
    if len(lead) > 115:
        lead = lead[:112].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    return f"{lead}. ما الذي حدث؟ ولماذا يهمك الخبر؟"


ORDINALS = ("الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس")


def make_planned_script(stories):
    """Natural Arabic bulletin from validated story plans: real numbers, one idea per story."""
    count = len(stories)
    first = stories[0]["plan"]
    lead_number = f" وأولها: {first['headline_ar']}" if first.get("headline_ar") else ""
    parts = [
        f"أهلاً بكم في ويلث رادار. {count} أخبار اقتصادية تهمك اليوم{lead_number}."
        if count > 1 else f"أهلاً بكم في ويلث رادار. خبر اقتصادي يهمك اليوم: {first['headline_ar']}."
    ]
    for index, story in enumerate(stories):
        plan = story["plan"]
        ordinal = ORDINALS[index] if index < len(ORDINALS) else str(index + 1)
        parts.append(
            f"الخبر {ordinal}: {plan['headline_ar']}. {plan['narration_ar']} "
            f"ماذا يعني هذا لك؟ {plan['why_it_matters_ar']}"
        )
    parts.append(
        "هذه أبرز أخبار اليوم. روابط المصادر الأصلية في وصف الفيديو، وهذا المحتوى للتوعية "
        "وليس نصيحة استثمارية. اكتب في التعليقات أي خبر كان الأهم بالنسبة لك."
    )
    return "\n\n".join(parts)


def make_script(stories):
    if stories and all(isinstance(item.get("plan"), dict) for item in stories):
        return make_planned_script(stories)
    parts = [
        "أهلاً بكم. إليكم أهم الأخبار الاقتصادية والمالية، ببساطة ووضوح.",
        make_opening_hook(stories),
        "سنقدم الوقائع المؤكدة، ونفصلها عن التحليل والتوقع."
    ]
    for index, story in enumerate(stories, start=1):
        summary = story["summary"] or "لم يرفق المصدر ملخصاً كافياً لهذا الخبر؛ راجعوا الرابط الأصلي للتفاصيل."
        parts.append(
            f"الخبر {index}: {story['title']}. "
            f"{summary} بحسب {story['source']}."
        )
    parts.append(
        "كيف نقرأ الصورة؟ حركة السوق لا تُفهم من رقم واحد. راقبوا البيانات الرسمية، "
        "وتكلفة التمويل، واتجاهات الطلب، وقارنوا الخبر بتأثيره على الشركات والأسر. "
        "الخبر المؤكد شيء، وتوقعات المستثمرين شيء آخر، والتمييز بينهما مهم عند متابعة الأسواق."
    )
    # Add useful explanatory context rather than repeating headlines or inventing facts.
    parts.append(
        "أول نقطة مهمة هي التمييز بين أثر الخبر الفوري وأثره على المدى المتوسط. "
        "قد يتفاعل السوق بسرعة مع عنوان أو تصريح، لكن استمرار التأثير يتوقف على البيانات "
        "التي تظهر بعد ذلك، وعلى القرارات الرسمية، وعلى استجابة الشركات والمستهلكين. "
        "لهذا لا يصح اعتبار حركة الأسعار في جلسة واحدة دليلاً كافياً على اتجاه طويل الأجل."
    )
    parts.append(
        "النقطة الثانية هي متابعة ما يمكن قياسه فعلاً. في الأخبار الاقتصادية نبحث عن "
        "الأرقام المنشورة ومصدرها وتاريخها، ونقارنها بالفترة السابقة وبالتوقعات المعلنة "
        "عندما تكون متاحة. وإذا لم يذكر الخبر رقماً أو لم يوضح طريقة احتسابه، فمن الأفضل "
        "التوقف عند حدود المعلومة وعدم ملء الفراغ بتخمينات أو استنتاجات غير مؤكدة."
    )
    parts.append(
        "أما تأثير الخبر على الناس والشركات فليس بالضرورة واحداً. فالنتيجة قد تختلف "
        "بحسب حجم النشاط، وتكاليف التشغيل، والقدرة على التمويل، وتوقيت الشراء أو البيع. "
        "لذلك نعرض الصورة العامة ونوضح العوامل التي تستحق المتابعة، من دون الجزم بأن "
        "كل مستثمر أو كل أسرة سيواجه النتيجة نفسها."
    )
    parts.append(
        "وخلال الساعات والأيام التالية، راقبوا أي بيان رسمي جديد وأي تحديث من المصدر "
        "الأصلي، وانتبهوا إلى الفرق بين القرار الذي دخل حيز التنفيذ والمقترح الذي ما زال "
        "قيد الدراسة. كذلك يجب التمييز بين التوقعات والتحقق الفعلي؛ فالتوقع قابل للتغير "
        "ولا يتحول إلى حقيقة لمجرد تكراره في أكثر من عنوان."
    )
    parts.append(
        "الخلاصة العملية هي ألا نبني قراراً مالياً على عنوان منفرد. اقرأوا التفاصيل، "
        "وتحققوا من التاريخ والوحدة المستخدمة في الأرقام، وقارنوا أكثر من مصدر موثوق، "
        "ثم قيّموا مدى صلة المعلومة بظروفكم. هذا الأسلوب يساعد على فهم الخبر بهدوء "
        "ويقلل خطر اتخاذ قرار متسرع بسبب ضجة مؤقتة."
    )
    parts.append(
        "وللمتابع العادي، الأهم هو فهم ما قد يتغير في تكلفة الاقتراض والطاقة والسلع، "
        "لا مطاردة حركة يوم واحد. إذا ظهرت بيانات جديدة أو صدر قرار رسمي، فقد تتبدل التوقعات بسرعة. "
        "لذلك نضع الروابط الأصلية في الوصف، ونراجع الأرقام قبل كل تحديث."
    )
    parts.append(
        "كانت هذه أبرز أخبار المال والاقتصاد لهذا اليوم. "
        "روابط المصادر في وصف الفيديو، وقد تتغير الأرقام مع صدور بيانات جديدة. "
        "تذكّروا أن الأخبار والمعلومات الواردة من المصادر قد تتغير، "
        "وأن هذا الموجز لا يمثل نصيحة استثمارية. "
        "تابعوا التحديثات القادمة، وشاركونا آراءكم وتعليقاتكم."
    )
    return "\n\n".join(parts)


TEASER_HOOK_AR = "ماذا يعني هذا لك بالتحديد؟ التفاصيل الكاملة في الفيديو الكامل على قناة ويلث رادار."
TEASER_DISCLAIMER_AR = "هذا المحتوى للتوعية وليس نصيحة استثمارية."


def make_short_script(story, teaser=False):
    """Create a hook-first Arabic Short with a practical angle and engagement CTA.

    teaser=True is used when the Short accompanies a long episode: the news in seconds, then one line that
    sends the viewer to the full video (no new facts are added in the hook)."""
    plan = story.get("plan")
    if isinstance(plan, dict):
        if teaser:
            return f"{plan['short_hook_ar']} {plan['short_body_ar']} {TEASER_HOOK_AR} {TEASER_DISCLAIMER_AR}"
        return (
            f"{plan['short_hook_ar']} {plan['short_body_ar']} "
            "تابع ويلث رادار لأخبار الاقتصاد كل يوم، وهذا المحتوى للتوعية وليس نصيحة استثمارية."
        )
    title = clean_narration(str(story.get("title", "")).strip())
    summary = clean_narration(str(story.get("summary", "")).strip())
    if not title or not summary or len(summary) < 45:
        raise ValueError("لا يمكن إعداد Short من عنوان أو ملخص غير مكتمل.")
    if len(title) > 105:
        title = title[:102].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    # Preserve only source-supported facts; the practical question is framed as a question,
    # never as a guaranteed effect or investment recommendation.
    if len(summary) > 520:
        summary = summary[:520].rsplit(" ", 1)[0]
    if teaser:
        return (
            f"الخبر ده ممكن يفرق في فهمك لفلوسك: {title}. "
            f"خليني أبسطهالك: {summary} {TEASER_HOOK_AR} {TEASER_DISCLAIMER_AR}"
        )
    return (
        f"الخبر ده ممكن يفرق في فهمك لفلوسك: {title}. "
        f"خليني أبسطهالك: {summary} "
        "المهم هنا تتابع الرقم أو القرار الرسمي، لأن تأثيره بيختلف حسب ظروف كل شخص. "
        "إنت شايف التطور ده هيأثر على قراراتك المالية؟ اكتب رأيك، "
        "وده محتوى توعوي، مش توصية استثمارية. ابعت الفيديو لحد يهمه الموضوع، واكتب رأيك في التعليقات."
    )


TOPIC_HASHTAGS = (
    (("الناتج المحلي", "gdp", "gross domestic"), "الناتج_المحلي"),
    (("فائدة", "الفيدرالي", "federal reserve", "interest rate", "powell"), "الفائدة"),
    (("تضخم", "inflation", "أسعار المستهلك", "cpi"), "التضخم"),
    (("ذهب", "gold"), "الذهب"),
    (("نفط", "oil", "crude", "برنت"), "النفط"),
    (("دولار", "dollar", "currency", "عملة"), "الدولار"),
    (("بيتكوين", "bitcoin", "crypto", "عملات مشفرة"), "بيتكوين"),
    (("بورصة", "أسهم", "stocks", "wall street", "nasdaq", "s&p"), "الأسهم"),
    (("إنفيديا", "nvidia", "chip", "رقائق", "ai ", "الذكاء الاصطناعي"), "الذكاء_الاصطناعي"),
    (("وظائف", "بطالة", "jobs", "unemployment", "payroll"), "الوظائف"),
    (("مصر", "egypt", "الجنيه"), "اقتصاد_مصر"),
    (("بنك", "bank", "قرض"), "البنوك"),
    (("تجارة", "تعرفة", "tariff", "trade"), "التجارة"),
    (("عقارات", "real estate", "housing", "mortgage"), "العقارات"),
)
DEFAULT_TOPIC_TAGS = ("الاقتصاد", "الأسواق", "أخبار_المال")


def topic_hashtags(stories, limit=3):
    """Hashtags (without #) taken from the stories' own topics, never a fixed generic set."""
    tags = []
    for story in stories:
        plan = story.get("plan") if isinstance(story.get("plan"), dict) else {}
        for tag in plan.get("hashtags", []) or []:
            if tag and tag not in tags:
                tags.append(tag)
    blob = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}" for item in stories
    ).casefold() + " "
    for terms, tag in TOPIC_HASHTAGS:
        if tag not in tags and any(term in blob for term in terms):
            tags.append(tag)
    for tag in DEFAULT_TOPIC_TAGS:
        if tag not in tags:
            tags.append(tag)
    return tags[:limit]


def original_link(story):
    """Prefer the publisher's own page over an aggregator (Google News RSS) redirect."""
    for key in ("source_url", "link"):
        value = str(story.get(key) or "").strip()
        host = (urlparse(value).hostname or "").lower()
        if value.startswith("https://") and host and not host.endswith("news.google.com"):
            return value
    return str(story.get("link") or "").strip()


def arabic_title_or_default(title, default):
    title = str(title or "").strip()
    return title if title and is_arabic_text(title, 0.6) else default


def build_short_youtube_metadata(story, script):
    """Short-specific title, two-line benefit summary, numbered source and four hashtags."""
    plan = story.get("plan") if isinstance(story.get("plan"), dict) else {}
    seed = plan.get("headline_ar") or clean_narration(story.get("title", ""))
    title_seed = arabic_title_or_default(seed, "خبر اقتصادي يهمك اليوم").rstrip(" .،؛:؟!")
    if len(title_seed) > 62:
        title_seed = title_seed[:59].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    title = f"{title_seed} | #Shorts"
    if plan:
        summary = plan.get("short_body_ar", "")[:260].rsplit(" ", 1)[0]
        why = plan.get("why_it_matters_ar", "")
    else:
        summary = clean_narration(story.get("summary", ""))[:220].rsplit(" ", 1)[0]
        why = ""
    tag_a, tag_b = (topic_hashtags([story], 2) + list(DEFAULT_TOPIC_TAGS))[:2]
    why_line = f"ماذا يعني لك؟ {why}\n\n" if why else ""
    description = (
        f"{title_seed}.\n"
        f"{summary}\n\n{why_line}"
        f"المصدر:\n1. {story.get('source', 'المصدر الأصلي')}: {original_link(story)}\n\n"
        "محتوى إخباري وتثقيفي، وليس نصيحة استثمارية. تحقق من المصدر الأصلي قبل أي قرار مالي.\n\n"
        f"#shorts #WealthRadar #{tag_a} #{tag_b}"
    )
    tags = ["WealthRadar", "Shorts", "أخبار اقتصادية", tag_a.replace("_", " "), tag_b.replace("_", " ")]
    return title[:100], description[:5000], tags


def build_youtube_metadata(stories, script):
    """Build a concise long-form description that preserves sources and all four hashtags."""
    first_plan = (stories or [{}])[0].get("plan") if stories else None
    first_plan = first_plan if isinstance(first_plan, dict) else {}
    lead_title = first_plan.get("headline_ar") or clean_narration((stories or [{}])[0].get("title", ""))
    lead_title = re.sub(r"^(عاجل|آخر الأخبار|أخبار اليوم)\s*[:：-]?\s*", "", lead_title, flags=re.I)
    lead_title = arabic_title_or_default(lead_title, "")
    episode_title = str((stories or [{}])[0].get("episode_title_ar") or "").strip()
    if episode_title and is_arabic_text(episode_title, 0.6):
        title = episode_title[:100]
    elif lead_title:
        lead_title = lead_title.rstrip(" .،؛:؟!")
        if len(lead_title) > 65:
            lead_title = lead_title[:62].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
        title = f"{lead_title} | وأهم أخبار المال اليوم" if len(stories) > 1 else f"{lead_title} | التفاصيل التي تهمك"
    else:
        title = "أهم أخبار المال والأسواق اليوم"

    topics = topic_hashtags(stories, 3)
    tags = ["WealthRadar", "أخبار اقتصادية", "أخبار المال", "الاقتصاد", "الأسواق"]
    tags += [topic.replace("_", " ") for topic in topics]
    tags = list(dict.fromkeys(tags))[:15]
    hashtags = ["#WealthRadar"] + [f"#{topic}" for topic in topics]

    story_lines = []
    source_lines = []
    for index, item in enumerate(stories, start=1):
        plan = item.get("plan") if isinstance(item.get("plan"), dict) else None
        if plan:
            number = f" ({plan['key_number_ar']})" if plan.get("key_number_ar") else ""
            story_lines.append(f"{index}. {plan['headline_ar']}{number}\nماذا يعني لك؟ {plan['why_it_matters_ar']}")
        else:
            item_title = clean_narration(item.get("title", ""))[:160]
            item_summary = clean_narration(item.get("summary", ""))
            if len(item_summary) > 280:
                item_summary = item_summary[:277].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
            story_lines.append(f"{index}. {item_title}\n{item_summary}")
        source_lines.append(f"{index}. {item.get('source', 'المصدر الأصلي')}: {original_link(item)}")

    # Do not paste the entire narration into the description. That can push source
    # links and required hashtags beyond YouTube's 5,000-character limit.
    description = (
        "أهم أخبار المال والاقتصاد والأسواق بالأرقام، مع شرح لما تعنيه لك وروابط المصادر الأصلية.\n\n"
        + "أبرز الأخبار:\n" + "\n\n".join(story_lines)
        + "\n\nمصادر الأخبار وروابطها:\n" + "\n".join(source_lines)
        + "\n\nهذا المحتوى إخباري وتثقيفي، ولا يُعد توصية أو نصيحة استثمارية. "
        + "تحقق من المصدر الأصلي قبل اتخاذ أي قرار مالي."
        + "\n\n" + " ".join(hashtags)
    )
    if len(description) > 5000:
        raise RuntimeError("وصف الفيديو الطويل يتجاوز حد يوتيوب؛ تم إيقافه بدلاً من قص المصادر أو الهاشتاجات.")
    return title, description, tags


def validate_youtube_metadata(title, description, *, short=False):
    """Fail closed if upload metadata is missing, overlong, branded in the title, or tag-incomplete."""
    title = str(title or "").strip()
    description = str(description or "").strip()
    if not title or len(title) > 100:
        raise RuntimeError("عنوان يوتيوب فارغ أو يتجاوز 100 حرف؛ تم إيقاف الرفع.")
    if "wealthradar" in title.casefold():
        raise RuntimeError("اسم القناة لا يجب أن يظهر في العنوان؛ تم إيقاف الرفع.")
    if not description or len(description) > 5000:
        raise RuntimeError("وصف يوتيوب فارغ أو يتجاوز 5000 حرف؛ تم إيقاف الرفع.")
    tag_line = description.splitlines()[-1].strip()
    hashtags = tag_line.split()
    if len(hashtags) != 4 or any(not tag.startswith("#") for tag in hashtags):
        raise RuntimeError("يجب أن ينتهي وصف الفيديو بأربعة هاشتاجات بالضبط؛ تم إيقاف الرفع.")
    required = {"#WealthRadar", "#shorts"} if short else {"#WealthRadar"}
    if len(set(hashtags)) != 4 or not required.issubset(set(hashtags)):
        raise RuntimeError("هاشتاجات النشر غير مكتملة أو مكررة؛ تم إيقاف الرفع.")
    if not re.search(r"https://", description):
        raise RuntimeError("روابط المصادر غير موجودة في وصف الفيديو؛ تم إيقاف الرفع.")
    return True

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


# Egyptian voice first (the channel speaks to Egypt), then the Egyptian female voice, then the old Saudi voice
# as a last resort so a voice outage never stalls the channel. Chosen 2026-11-26 on dialect fit; not yet judged by ear.
EDGE_VOICE_DEFAULT = "ar-EG-ShakirNeural"
EDGE_VOICE_FALLBACKS = ("ar-EG-SalmaNeural", "ar-SA-HamedNeural")


def prepare_tts_text(value):
    """Make written Arabic read naturally: spell out percent signs and drop symbols voices skip or mispronounce."""
    text = clean_narration(value)
    text = re.sub(r"(\d)\s*[%٪]", r"\1 في المئة", text)
    text = text.replace("%", " في المئة").replace("&", " و ").replace("$", " دولار ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def master_audio(raw_path, path, label):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.move(str(raw_path), str(path))
        print(f"[VOICE_READY] {label} | mastering=skipped")
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
    print(f"[VOICE_READY] {label} | bytes={path.stat().st_size}")


async def make_audio_edge(text, path):
    """Free Microsoft neural Arabic voice (edge-tts). Hamed reads numbers and decimals correctly."""
    voice = os.getenv("NEWSFLOW_TTS_VOICE", EDGE_VOICE_DEFAULT).strip() or EDGE_VOICE_DEFAULT
    rate = os.getenv("NEWSFLOW_TTS_RATE", "+8%").strip() or "+8%"
    clean_text = prepare_tts_text(text)
    raw_path = path.with_name(path.stem + ".raw.mp3")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for candidate in dict.fromkeys((voice, *EDGE_VOICE_FALLBACKS)):
        for attempt in range(3):
            try:
                await edge_tts.Communicate(clean_text, candidate, rate=rate).save(str(raw_path))
                if raw_path.is_file() and raw_path.stat().st_size > 1000:
                    master_audio(raw_path, path, f"Edge neural voice {candidate} rate={rate}")
                    return
            except Exception as exc:  # noqa: BLE001 - retry, then try the fallback voice
                last_error = exc
                await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"فشل توليد الصوت المجاني (edge-tts): {type(last_error).__name__ if last_error else 'empty audio'}")


async def make_audio(text, path):
    """Default: free Edge neural voice. Fish Audio only when NEWSFLOW_TTS_PROVIDER=fish."""
    if os.getenv("NEWSFLOW_TTS_PROVIDER", "edge").strip().lower() != "fish":
        return await make_audio_edge(text, path)
    return await make_audio_fish(text, path)


async def make_audio_fish(text, path):
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
    from newsflow.rendering import _font_path

    try:
        return _font_path(bold)
    except RuntimeError:
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


def caption_phrases(value, words_per_caption=4):
    """Create short Arabic captions that refresh with every moving B-roll cut."""
    words = clean_narration(value).split()
    return [
        " ".join(words[index:index + words_per_caption])
        for index in range(0, len(words), words_per_caption)
    ] or ["تابع التفاصيل"]


def split_required_hashtags(description, *, short=False):
    """Separate the mandatory four-tag footer so later edits cannot truncate it."""
    base = str(description or "").strip()
    if not base:
        raise RuntimeError("وصف يوتيوب فارغ؛ تم إيقاف الرفع.")
    lines = base.splitlines()
    tag_line = lines[-1].strip()
    hashtags = tag_line.split()
    if len(hashtags) != 4 or any(not tag.startswith("#") for tag in hashtags):
        raise RuntimeError("الوصف يجب أن ينتهي بأربعة هاشتاجات قبل إضافة بيانات الترخيص.")
    required = {"#WealthRadar", "#shorts"} if short else {"#WealthRadar"}
    if len(set(hashtags)) != 4 or not required.issubset(set(hashtags)):
        raise RuntimeError("الهاشتاجات المطلوبة ناقصة أو مكررة.")
    return "\n".join(lines[:-1]).rstrip(), tag_line


def append_long_video_link(description, long_video_url):
    """Add the verified companion episode URL without disturbing source links or hashtags."""
    url = str(long_video_url or "").strip()
    if not url:
        return description
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.casefold() != "youtu.be" or not parsed.path.strip("/"):
        raise RuntimeError("رابط الحلقة الطويلة غير صالح؛ لم نضفه إلى وصف Short.")
    body, footer = split_required_hashtags(description, short=True)
    if url not in body:
        body = f"{body}\n\nشاهد الحلقة الكاملة المرتبطة بهذا الخبر: {url}"
    return f"{body}\n\n{footer}"


def append_broll_attribution(description, video_path, *, short=False):
    """Require a valid Pexels manifest and preserve sources and hashtags in full."""
    manifest_path = video_path.with_suffix(".broll-manifest.json")
    if not manifest_path.is_file():
        raise RuntimeError("ملف توثيق لقطات Pexels غير موجود؛ أوقفنا تجهيز وصف النشر.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("ملف توثيق لقطات Pexels غير صالح؛ أوقفنا تجهيز وصف النشر.") from None
    allowed = {
        "Pexels": "Pexels License",
        "Pixabay": "Pixabay Content License",
        "Pexels+Pixabay": "Pexels License + Pixabay Content License",
    }
    if allowed.get(manifest.get("provider")) != manifest.get("license"):
        raise RuntimeError("بيانات ترخيص B-roll غير مطابقة؛ أوقفنا تجهيز وصف النشر.")
    page_prefix = {"Pexels": "https://www.pexels.com/", "Pixabay": "https://pixabay.com/"}
    credits, seen, used = [], set(), []
    for source in manifest.get("sources", []):
        page = str(source.get("source_page") or "").strip()
        name = str(source.get("provider") or "Pexels")
        photographer = str(source.get("photographer") or f"مصور {name}").strip()
        if name not in page_prefix or not page.startswith(page_prefix[name]) or page in seen:
            continue
        seen.add(page)
        if name not in used:
            used.append(name)
        credits.append(f"- {photographer} / {name}: {page}")
        if len(credits) >= 12:
            break
    if not credits:
        raise RuntimeError("لا توجد روابط إسناد صالحة لمقاطع Pexels؛ أوقفنا تجهيز وصف النشر.")
    body, hashtag_line = split_required_hashtags(description, short=short)
    label = " + ".join(f"{name} ({'Pexels License' if name == 'Pexels' else 'Pixabay Content License'})" for name in used)
    attribution = f"لقطات الفيديو المتحركة المرخّصة من {label}:\n" + "\n".join(credits)
    result = body + "\n\n" + attribution + "\n\n" + hashtag_line
    if len(result) > 5000:
        raise RuntimeError("إضافة إسناد لقطات Pexels تتجاوز حد يوتيوب؛ تم إيقاف الرفع بدلاً من حذف الروابط أو الهاشتاجات.")
    return result


def add_private_review_notice(description, *, short=False):
    """Mark a private review copy without dropping any source links or required hashtags."""
    # The notice is opt-in: it must never leak into a description that goes public.
    if os.getenv("NEWSFLOW_PRIVATE_REVIEW_NOTICE", "false").strip().lower() != "true":
        return description
    notice = (
        "نسخة مراجعة خاصة — ليست معتمدة للنشر العام بعد. "
        "التحقق المستقل من الوقائع ومراجعة المصادر مطلوبان قبل إتاحتها للعامة."
    )
    body, hashtag_line = split_required_hashtags(description, short=short)
    result = notice + "\n\n" + body + "\n\n" + hashtag_line
    if len(result) > 5000:
        raise RuntimeError("إضافة تنبيه المراجعة الخاصة تتجاوز حد يوتيوب؛ تم إيقاف الرفع.")
    return result


def planned_cards(story_list, *, short=False):
    """Scene cards for the planned Arabic script. Returns (cards, spoken_text_per_card) so timing follows speech length."""
    if short:
        story = story_list[0]
        plan = story["plan"]
        spoken = make_short_script(story)
        card = {
            "heading": "", "title": plan["headline_ar"], "body": "",
            "headline": "", "key_number": plan.get("key_number_ar", ""),
            "captions": caption_phrases(spoken, words_per_caption=6),
        }
        return [card], [spoken]
    script = make_planned_script(story_list)
    paragraphs = script.split("\n\n")
    cards, spoken = [], []
    intro_text = paragraphs[0]
    cards.append({
        "heading": "", "title": "", "body": "", "headline": "", "key_number": "",
        "captions": caption_phrases(intro_text, words_per_caption=6),
    })
    spoken.append(intro_text)
    for story, text in zip(story_list, paragraphs[1:1 + len(story_list)]):
        plan = story["plan"]
        cards.append({
            "heading": "", "title": plan["headline_ar"], "body": "",
            "headline": plan["headline_ar"], "key_number": plan.get("key_number_ar", ""),
            "captions": caption_phrases(text, words_per_caption=6),
        })
        spoken.append(text)
    outro_text = paragraphs[-1]
    cards.append({
        "heading": "", "title": "", "body": "", "headline": "", "key_number": "",
        "captions": caption_phrases(outro_text, words_per_caption=6),
    })
    spoken.append(outro_text)
    return cards, spoken


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
    if story_list and all(isinstance(item.get("plan"), dict) for item in story_list):
        cards, spoken = planned_cards(story_list, short=short)
        weights = [max(40, len(text)) for text in spoken]
        weight_total = sum(weights)
        durations = [total_duration * weight / weight_total for weight in weights]
        durations[-1] += total_duration - sum(durations)
        render_broll_video(cards, durations, audio, output, portrait=portrait)
        print(f"[BROLL_RENDER_COMPLETE] cards={len(cards)} orientation={'portrait' if portrait else 'landscape'} layout=planned")
        return
    opening = make_opening_hook(story_list)
    cards = [{
        "heading": "المقدمة",
        "title": opening,
        "body": "أهم تطورات المال والأسواق، من غير تهويل وبالمصادر",
        "captions": caption_phrases(opening),
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
    closing = "تابع المصدر الأصلي، وقارن المعلومات قبل أي قرار مالي."
    cards.append({
        "heading": "الخلاصة",
        "title": "قبل أي قرار مالي",
        "body": "تابع المصدر الأصلي، وقارن المعلومات قبل أي قرار مالي.",
        "captions": caption_phrases(closing),
    })

    weights = [max(90, len(card["title"]) + len(card["body"])) for card in cards]
    weight_total = sum(weights)
    durations = [total_duration * weight / weight_total for weight in weights]
    durations[-1] += total_duration - sum(durations)

    # Moving licensed footage is mandatory. Never fall back to static cards.
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


def upload_status_body(privacy: str) -> dict:
    """The status block for videos.insert. Realistic synthetic narration is disclosed (owner rule 2026-11-26)."""
    body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if os.getenv("NEWSFLOW_DECLARE_SYNTHETIC", "true").strip().lower() not in {"0", "false", "no"}:
        body["containsSyntheticMedia"] = True  # status.containsSyntheticMedia, Data API since 2024-10-30
    return body


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
        "status": upload_status_body(status),
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
    parser.add_argument("--render-only", action="store_true", help="Render long video and companion Shorts as review artifacts; never upload")
    parser.add_argument("--max-stories", type=int, default=int(os.getenv("NEWSFLOW_MAX_STORIES", "4")))
    parser.add_argument("--private-test", action="store_true", help="Upload exactly one long video with private privacy after manual approvals")
    parser.add_argument("--private-staging", action="store_true", help="Owner-approved PRIVATE production: render the main episode and companion Shorts for review")
    parser.add_argument("--shorts-only", action="store_true", help="Experimental isolated run: render one Short only; never use for standard production")
    parser.add_argument("--audit-episode", action="store_true", help="Build the 'كشف حساب' (Money Audit) review package: brief, charts, description. Never renders or uploads.")
    args = parser.parse_args()
    if args.audit_episode:
        if args.dry_run or args.render_only or args.private_test or args.private_staging or args.shorts_only:
            parser.error("--audit-episode is a standalone review step and cannot be combined with other modes")
        from wealthradar_audit.hook import prepare_episode
        audit = prepare_episode(ROOT / os.getenv("NEWSFLOW_OUTPUT_DIR", "output") / "audit-episode")
        for note in audit["on_screen_required"]:
            print(f"[AUDIT_ON_SCREEN] {note}")
        for warning in audit["warnings"]:
            print(f"[AUDIT_WARNING] {warning}")
        if audit["blockers"]:
            print("[AUDIT_UPLOAD_BLOCKED] " + " | ".join(audit["blockers"]))
        print(f"[AUDIT_READY] package in {audit['out']}; upload_allowed={audit['upload_allowed']}")
        return
    if args.shorts_only and os.getenv("NEWSFLOW_ALLOW_ISOLATED_SHORT_EXPERIMENT", "false").strip().lower() != "true":
        parser.error("--shorts-only is an isolated experiment and requires NEWSFLOW_ALLOW_ISOLATED_SHORT_EXPERIMENT=true; use NewsFlow standard production for the main video and companion Shorts.")
    args.max_stories = clamp_max_stories(args.max_stories)
    if (args.render_only and (args.dry_run or args.private_test or args.private_staging)):
        parser.error("--render-only cannot be combined with dry-run or private upload modes")
    if (args.private_test or args.private_staging) and args.dry_run:
        parser.error("Private production modes cannot be combined with --dry-run")
    if args.private_test and args.private_staging:
        parser.error("Choose either manual private-test or scheduled private-staging, not both")
    if args.shorts_only and not args.private_staging:
        parser.error("--shorts-only is restricted to PRIVATE staging")
    if args.shorts_only and args.private_test:
        parser.error("--shorts-only cannot be combined with --private-test")
    if not args.dry_run and not args.private_test and not args.private_staging and not args.render_only:
        parser.error("الرندر الكامل محظور؛ استخدم --dry-run أو --render-only أو وضع PRIVATE المعتمد.")
    staging_env = os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true"
    if args.private_staging and not staging_env:
        parser.error("--private-staging is allowed only for the scheduled staging workflow")
    if not args.private_staging and staging_env:
        parser.error("NEWSFLOW_PRIVATE_STAGING requires --private-staging")
    upload_enabled = os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() == "true"
    if args.render_only and upload_enabled:
        parser.error("--render-only refuses to run while YouTube uploads are enabled.")
    if args.render_only and not (os.getenv("PEXELS_API_KEY", "").strip() or os.getenv("PIXABAY_API_KEY", "").strip()):
        parser.error("--render-only requires PEXELS_API_KEY or PIXABAY_API_KEY; no static-card fallback is allowed.")
    editorial_approved = os.getenv("NEWSFLOW_EDITORIAL_APPROVED", "false").lower() == "true"
    private_staging = os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true"
    visual_qa_approved = os.getenv("NEWSFLOW_VISUAL_QA_APPROVED", "false").lower() == "true"
    if args.private_staging and not upload_enabled:
        parser.error("Scheduled private staging requires YOUTUBE_UPLOAD_ENABLED=true")
    if args.private_test:
        args.max_stories = 1
        if not upload_enabled:
            parser.error("Private test requires YOUTUBE_UPLOAD_ENABLED=true")
        if not visual_qa_approved:
            parser.error("Private test requires explicit phone visual QA approval.")
    # OAuth validation is deliberately delayed until editorial and fact-check gates pass.
    auth_credentials = None
    out = ROOT / os.getenv("NEWSFLOW_OUTPUT_DIR", "output")
    out.mkdir(parents=True, exist_ok=True)
    stories, filtered_stories = collect(args.max_stories)
    editorial_report = review_stories(stories)
    # Fetch original publisher pages even when RSS summaries are missing or truncated.
    # Only readable original article text may replace an incomplete RSS summary.
    evidence_records = collect_source_evidence(editorial_report["accepted"])
    evidence_by_story = {
        str(item.get("story_id") or ""): item for item in evidence_records
    }
    source_validated_stories = []
    source_rejected_stories = []
    for story in editorial_report["accepted"]:
        evidence = evidence_by_story.get(str(story.get("id") or ""), {})
        article_text = str(evidence.get("article_text") or "").strip()
        if evidence.get("status") == "readable" and len(article_text) >= 700:
            source_story = dict(story)
            source_story["summary"] = article_text
            source_relevant, source_relevance_reason = relevance(source_story)
            if not source_relevant:
                source_rejected_stories.append({
                    "id": story.get("id"),
                    "title": story.get("title"),
                    "source": story.get("source"),
                    "reasons": [
                        "استُبعد بعد فحص النص الأصلي: " + source_relevance_reason
                    ],
                })
                continue
            story["rss_summary"] = str(story.get("summary") or "")[:500]
            story["summary"] = article_text[:1800]
            story["summary_source"] = "original_publisher_article"
            story["relevance_reason"] = source_relevance_reason
        source_validated_stories.append(story)
    editorial_report["accepted"] = source_validated_stories
    editorial_report["accepted_count"] = len(source_validated_stories)
    editorial_report["rejected"].extend(source_rejected_stories)
    editorial_report["rejected_count"] += len(source_rejected_stories)
    editorial_report["source_evidence"] = evidence_records
    evidence_counts = {
        status: sum(1 for item in evidence_records if item.get("status") == status)
        for status in ("readable", "partial", "thin", "unavailable")
    }
    evidence_dir = out / "source-evidence"
    if evidence_records:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for index, evidence in enumerate(evidence_records, start=1):
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(evidence.get("story_id") or index))
            (evidence_dir / f"{safe_id}.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    editorial_report["source_evidence_summary"] = {
        "total": len(evidence_records),
        **evidence_counts,
        "meaning": "إتاحة النص الأصلي لا تعني اكتمال التحقق من الوقائع.",
    }
    print(
        "[SOURCE_EVIDENCE] "
        f"total={len(evidence_records)} readable={evidence_counts['readable']} "
        f"partial={evidence_counts['partial']} thin={evidence_counts['thin']} "
        f"unavailable={evidence_counts['unavailable']}"
    )

    # Every accepted claim needs one credible cited domain independent of the original publisher; a second independent source is optional.
    fact_check_enabled = os.getenv("NEWSFLOW_FACT_CHECK_ENABLED", "true").strip().lower() == "true"
    if fact_check_enabled:
        fact_check_report = fact_check_stories(editorial_report["accepted"], evidence_records)
    else:
        fact_check_report = {
            "status": "not_performed",
            "verified_count": 0,
            "rejected_count": len(editorial_report["accepted"]),
            "results": [],
            "reason": "NEWSFLOW_FACT_CHECK_ENABLED=false",
        }
    # Apply verification per story: keep supported items and skip only the
    # individual stories that could not be supported. A failed item must not
    # block the rest of the bulletin.
    check_results = {
        str(item.get("story_id") or ""): item
        for item in fact_check_report.get("results", [])
    }
    eligible_stories = []
    skipped_stories = []
    for story in editorial_report["accepted"]:
        result = check_results.get(str(story.get("id") or ""), {})
        if result.get("verified") is True and result.get("status") == "verified":
            approved_story = dict(story)
            approved_story["fact_check_status"] = "supported"
            approved_story["fact_check_sources"] = result.get("sources", [])
            eligible_stories.append(approved_story)
        else:
            skipped_stories.append({
                "id": story.get("id"),
                "title": story.get("title"),
                "source": story.get("source"),
                "reasons": result.get("blockers") or ["لم يكتمل التحقق من هذا الخبر؛ تم تجاوزه دون تعطيل بقية الأخبار."],
                "fact_check_status": result.get("status") or "not_performed",
            })
    editorial_report["rejected"].extend(skipped_stories)
    editorial_report["rejected_count"] += len(skipped_stories)
    # Fact-check a few candidates beyond the requested output count, then retain
    # only the first supported stories. This lets a bad lead be skipped safely.
    deferred_stories = eligible_stories[args.max_stories:]
    eligible_stories = eligible_stories[:args.max_stories]
    editorial_report["deferred_verified_stories"] = [
        {"id": item.get("id"), "title": item.get("title")}
        for item in deferred_stories
    ]
    editorial_report["deferred_verified_count"] = len(deferred_stories)
    editorial_report["accepted"] = eligible_stories
    editorial_report["accepted_count"] = len(eligible_stories)
    editorial_report["status"] = "ready_for_production" if eligible_stories else "blocked"
    editorial_report["human_approval_required"] = False
    editorial_report["fact_check_report"] = fact_check_report
    editorial_report["fact_checking"] = "verified" if eligible_stories else (
        str(fact_check_report.get("status") or "not_performed")
    )
    fact_check_dir = out / "fact-check"
    fact_check_dir.mkdir(parents=True, exist_ok=True)
    (fact_check_dir / "report.json").write_text(
        json.dumps(fact_check_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for result in fact_check_report.get("results", []):
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(result.get("story_id") or "unknown"))
        (fact_check_dir / f"{safe_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        "[FACT_CHECK] "
        f"status={editorial_report['fact_checking']} "
        f"verified={fact_check_report.get('verified_count', 0)} "
        f"rejected={fact_check_report.get('rejected_count', len(editorial_report['accepted']))} "
        f"method={fact_check_report.get('method', 'none')}"
    )
    # Fish Audio uses the channel owner's configured voice reference; no presenter footage
    # is required for a narrated news video. Licensed B-roll is confirmed after rendering.
    voice_source = (
        "owner_voice_clone"
        if os.getenv("NEWSFLOW_TTS_PROVIDER", "edge").strip().lower() == "fish"
        and os.getenv("FISH_AUDIO_REFERENCE_ID", "").strip()
        else "neural_tts"
    )
    editorial_report.update({
        "voice_source": voice_source,
        "presenter_source": "none",
        "broll_source": "none",
        "publication_review": "private_owner_review_pending" if args.private_staging else "not_approved",
    })
    editorial_report["rejected"].extend(filtered_stories)
    editorial_report["rejected_count"] += len(filtered_stories)
    (out / "editorial_review.json").write_text(
        json.dumps(editorial_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stories = editorial_report["accepted"]
    (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.getenv("NEWSFLOW_RECORD_DRAFT_HISTORY", "false").lower() == "true" and stories:
        count = record_story_history(story_history_path(), stories)
        print(f"[DRAFT_HISTORY_RECORDED] stories={count} cooldown_days=30")
    print(f"[EDITORIAL_REVIEW] status={editorial_report['status']} accepted={editorial_report['accepted_count']} rejected={editorial_report['rejected_count']} warnings={editorial_report['warning_count']} fact_checking={editorial_report['fact_checking']}")
    upload_blockers = upload_review_blockers(
        editorial_report,
        editorial_approved or args.render_only,
        private_staging=args.private_staging,
        require_broll=False,
    )
    # A dry run is collection and validation only: never write scripts or render media.
    if args.dry_run:
        print("[DRY_RUN] Collection, source evidence, and review reports saved; no scripts, audio, or video generated.")
        if upload_blockers:
            print("[DRY_RUN_BLOCKED] " + " | ".join(upload_blockers))
        else:
            print("[DRY_RUN_VALIDATED] Editorial review and independent fact-check passed.")
        return
    # Only individually supported stories enter scripts/media. Unverified stories
    # are skipped above; they do not block other supported stories in the bulletin.
    if args.private_test and upload_blockers:
        print("[SAFE] PRIVATE test blocked before OAuth/audio/render: " + " | ".join(upload_blockers))
        return
    if args.private_staging and upload_blockers:
        raise RuntimeError(
            "PRIVATE review staging blocked before OAuth/audio/render: " + " | ".join(upload_blockers)
        )
    if args.render_only and upload_blockers:
        raise RuntimeError(
            "RENDER ONLY blocked before audio/video because editorial verification is incomplete: "
            + " | ".join(upload_blockers)
        )
    # Every non-dry-run production path must stop before scripts/audio/video on blockers.
    if upload_blockers:
        raise RuntimeError(
            "PRODUCTION blocked before script/audio/video because review requirements are incomplete: "
            + " | ".join(upload_blockers)
        )
    if not args.dry_run and not args.render_only and (
        args.private_test or args.private_staging or upload_enabled
    ):
        try:
            auth_credentials = validate_youtube_auth()
        except RuntimeError as exc:
            parser.error(str(exc))
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
        if args.render_only:
            raise RuntimeError(message)
        return
    # Original publisher URL (final_url) replaces Google News / aggregator links in descriptions.
    for story in stories:
        evidence = evidence_by_story.get(str(story.get("id") or ""), {})
        final_url = str(evidence.get("final_url") or "").strip()
        if final_url.startswith("https://"):
            story["source_url"] = final_url
    # Arabic script with real numbers, a viewer-impact line and per-story hashtags (free Groq model).
    script_plan = generate_plan(stories)
    if script_plan:
        for story in stories:
            planned = script_plan["stories"].get(str(story.get("id")))
            if planned:
                story["plan"] = planned
        if script_plan.get("episode_title_ar") and all(isinstance(s.get("plan"), dict) for s in stories):
            stories[0]["episode_title_ar"] = script_plan["episode_title_ar"]
        # Never fall back to an English headline inside an Arabic bulletin: unplanned stories are skipped.
        stories = [item for item in stories if isinstance(item.get("plan"), dict)]
        print(f"[BULLETIN_STORIES] planned={len(stories)}")
    for story in stories:
        folder = out / story["id"]
        folder.mkdir(exist_ok=True)
        (folder / "script.txt").write_text(make_script([story]), encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DRAFT] {story['title']} — {story['link']}")

    bulletin_script = make_script(stories)
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
        make_video(short_title, short_audio, short_video, short=True, stories=[story])
        validate_video(short_video, short_audio, expected_short=True)
        short_description = append_broll_attribution(short_description, short_video, short=True)
        editorial_report["broll_source"] = "pexels"
        if args.private_staging:
            short_description = add_private_review_notice(short_description, short=True)
        validate_youtube_metadata(short_title, short_description, short=True)
        (out / "editorial_review.json").write_text(
            json.dumps(editorial_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        final_blockers = upload_review_blockers(
            editorial_report, editorial_approved,
            private_staging=args.private_staging, require_broll=True,
        )
        if upload_enabled and final_blockers:
            raise RuntimeError("تم منع الرفع الخاص بعد فحص الوسائط النهائي: " + " | ".join(final_blockers))
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
        duration = validate_audio_duration(probe.stdout.strip(), private_test=args.private_test or args.private_staging)
        print(f"[AUDIO_DURATION] {duration:.1f} seconds (duration follows editorial content)")

    single_long_upload = os.getenv("NEWSFLOW_UPLOAD_SINGLE_LONG", "false").lower() == "true"
    video_title, description, tags = build_youtube_metadata(stories, bulletin_script)
    print(f"[YOUTUBE_METADATA] title={video_title} | words={len(video_title.split())} | tags={len(tags)}")

    long_video = bulletin / "long.mp4"
    make_video(video_title, audio, long_video, short=False, portrait=main_portrait, stories=stories)
    validate_video(long_video, audio, expected_portrait=main_portrait)
    description = append_broll_attribution(description, long_video)
    editorial_report["broll_source"] = "pexels"
    if args.private_staging:
        description = add_private_review_notice(description)
        editorial_report["publication_review"] = "private_owner_review_pending"
    validate_youtube_metadata(video_title, description, short=False)
    (out / "editorial_review.json").write_text(
        json.dumps(editorial_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.render_only:
        print("[RENDER_ONLY_READY] long video complete; YouTube upload is disabled.")
    if args.private_test:
        final_blockers = upload_review_blockers(
            editorial_report, editorial_approved, private_staging=False, require_broll=True,
        )
        if final_blockers:
            raise RuntimeError("تم منع الرفع بعد فحص الوسائط النهائي: " + " | ".join(final_blockers))
        if upload_enabled:
            youtube_upload(
                long_video, video_title, description, tags,
                privacy_override="private", credentials=auth_credentials
            )
        else:
            print("[SAFE] PRIVATE upload skipped; generated video remains an Artifact.")
        return

    # Render and validate every companion Short before uploading anything. This avoids
    # a partial private set if one of the Short renders or source manifests fails.
    staged_shorts = []
    if not single_long_upload:
        shorts_dir = bulletin / "shorts"
        shorts_dir.mkdir(exist_ok=True)
        for index, story in enumerate(stories[:2], start=1):
            short_script = make_short_script(story, teaser=True)  # companion Short = teaser for the long episode
            short_audio = shorts_dir / f"short-{index}.mp3"
            short_video = shorts_dir / f"short-{index}.mp4"
            asyncio.run(make_audio(short_script, short_audio))
            short_title, short_description, short_tags = build_short_youtube_metadata(story, short_script)
            make_video(short_title, short_audio, short_video, short=True, stories=[story])
            validate_video(short_video, short_audio, expected_short=True)
            short_description = append_broll_attribution(short_description, short_video, short=True)
            if args.private_staging:
                short_description = add_private_review_notice(short_description, short=True)
            validate_youtube_metadata(short_title, short_description, short=True)
            short_probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(short_audio)],
                check=True, capture_output=True, text=True,
            )
            short_duration = float(short_probe.stdout.strip())
            short_min, short_max = (25, 60) if args.private_staging else (35, 45)
            if not short_min <= short_duration <= short_max:
                raise RuntimeError(
                    f"مدة Short يجب أن تكون بين 35 و45 ثانية؛ المدة الحالية {short_duration:.1f} ثانية."
                )
            staged_shorts.append((short_video, short_title, short_description, short_tags))
            print(f"[SHORT_READY] {short_video} duration={short_duration:.1f}s story={story['id']}")

    final_blockers = upload_review_blockers(
        editorial_report, editorial_approved,
        private_staging=args.private_staging, require_broll=True,
    )
    if upload_enabled and final_blockers:
        raise RuntimeError("تم منع الرفع بعد فحص الوسائط النهائي: " + " | ".join(final_blockers))

    if args.private_staging:
        print("[PRIVATE_STAGING] All media passed; uploads remain PRIVATE for owner review only.")
    if upload_enabled:
        long_video_url = youtube_upload(
            long_video, video_title, description, tags,
            privacy_override="private", credentials=auth_credentials,
        )
        related_links = []
        for short_video, short_title, short_description, short_tags in staged_shorts:
            linked_description = append_long_video_link(short_description, long_video_url)
            validate_youtube_metadata(short_title, linked_description, short=True)
            short_url = youtube_upload(
                short_video, short_title, linked_description, short_tags,
                privacy_override="private", credentials=auth_credentials,
            )
            related_links.append({"short": short_url, "long": long_video_url})
        # The YouTube Data API cannot set a Short's "Related video"; record the pairs so that single
        # Studio step can be done (or checked) per Short. The description link is set automatically.
        links_path = bulletin / "related_video_links.json"
        links_path.write_text(json.dumps({"pairs": related_links, "api_supported": False},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[RELATED_VIDEO_PAIRS] {len(related_links)} Short(s) -> {long_video_url}; set 'Related video' in Studio")
    else:
        print("[SAFE] Rendered videos remain workflow Artifacts; YouTube upload is disabled.")


if __name__ == "__main__":
    main()


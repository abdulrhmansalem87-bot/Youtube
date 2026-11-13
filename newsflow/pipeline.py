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
from newsflow.rendering import render_cards_video

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
    minimum = 1 if private_test else 181
    if value < minimum or value > 300:
        target = "أكثر من 3 وحتى 5 دقائق" if not private_test else "حتى 5 دقائق"
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

def make_opening_hook(stories):
    """Lead with the strongest verified story in clear modern Arabic."""
    if not stories:
        return "ما أبرز ما يحرك الأسواق اليوم؟ إليك الصورة ببساطة."
    lead = clean_narration(stories[0].get("title", ""))
    lead = re.sub(r"^(عاجل|آخر الأخبار|أخبار اليوم)\s*[:：-]?\s*", "", lead, flags=re.I)
    if len(lead) > 115:
        lead = lead[:112].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    return f"{lead}. ما الذي حدث؟ ولماذا يهمك الخبر؟"


def make_script(stories):
    parts = [
        "أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar.",
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
        "ولا تنسوا الاشتراك في WealthRadar وتفعيل زر الجرس."
    )
    return "\n\n".join(parts)


def make_short_script(story):
    """Create a hook-first Arabic Short with a practical angle and engagement CTA."""
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
    return (
        f"الخبر ده ممكن يفرق في فهمك لفلوسك: {title}. "
        f"خليني أبسطهالك: {summary} "
        "المهم هنا تتابع الرقم أو القرار الرسمي، لأن تأثيره بيختلف حسب ظروف كل شخص. "
        "إنت شايف التطور ده هيأثر على قراراتك المالية؟ اكتب رأيك، "
        "وده محتوى توعوي مش توصية استثمارية. وابعت الفيديو لحد يهمه الموضوع واشترك في WealthRadar."
    )


def build_short_youtube_metadata(story, script):
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
    description = (
        f"في هذا الفيديو نفهم ببساطة: {title_seed}.\n"
        f"ملخص الخبر: {summary}.\n\n"
        f"المصادر:\n1. {story.get('source', 'المصدر الأصلي')}: {story.get('link', '')}\n\n"
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
        title = f"{lead_title} | التفاصيل التي تهمك | WealthRadar"
    else:
        title = "أهم تطورات المال والأسواق اليوم | WealthRadar"
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
        hashtags.append("#الذهب")
    elif any(term in text_blob for term in ("دولار", "currency")):
        hashtags.append("#الدولار")
    elif any(term in text_blob for term in ("بورصة", "أسهم", "stocks")):
        hashtags.append("#البورصة")
    else:
        hashtags.append("#الاقتصاد")
    source_lines = "\n".join(
        f"{i}. {item['source']}: {item['link']}"
        for i, item in enumerate(stories, start=1)
    )
    description = (
        "موجز WealthRadar اليومي لأهم تطورات المال والاقتصاد والأسواق. "
        "عناوين واضحة ومصادر مباشرة لمساعدتك على متابعة ما يحدث.\n\n"
        + script + "\n\nمصادر الأخبار وروابطها:\n" + source_lines
        + "\n\nهذا المحتوى إخباري وتثقيفي، ولا يُعد توصية أو نصيحة استثمارية. "
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
    }]
    for index, story in enumerate(story_list, start=1):
        cards.append({
            "heading": f"الخبر {index:02d}، {source_display_name(story.get('source', 'المصدر'))}",
            "title": clean_narration(story.get("title", "")),
            "body": clean_narration(story.get("summary", "")[:520])
                    or "راجع رابط المصدر لمعرفة التفاصيل الكاملة.",
        })
    cards.append({
        "heading": "الخلاصة",
        "title": "قبل أي قرار مالي",
        "body": "تابع المصدر الأصلي وقارن المعلومات. اشترك في WealthRadar وفعّل زر الجرس لمتابعة الموجز القادم.",
    })

    weights = [max(90, len(card["title"]) + len(card["body"])) for card in cards]
    weight_total = sum(weights)
    durations = [total_duration * weight / weight_total for weight in weights]
    durations[-1] += total_duration - sum(durations)

    cache_dir = output.parent / ".render_cache" / output.stem
    render_cards_video(
        cards, durations, audio, output, short=short, portrait=portrait,
        commit_sha=os.getenv("GITHUB_SHA", "local"), cache_dir=cache_dir,
    )
    print(f"[RENDER_RESUME] scenes={len(cards)} cache={cache_dir}")

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
    print(f"[UPLOAD_VERIFIED] https://youtu.be/{video_id} privacy={status} channel={target_channel_id}")

def main():
    parser = argparse.ArgumentParser(description="WealthRadar Arabic financial news pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Collect and write drafts only")
    parser.add_argument("--max-stories", type=int, default=int(os.getenv("NEWSFLOW_MAX_STORIES", "4")))
    parser.add_argument("--private-test", action="store_true", help="Upload exactly one long video with private privacy")
    args = parser.parse_args()
    args.max_stories = clamp_max_stories(args.max_stories)
    if args.private_test and args.dry_run:
        parser.error("--private-test cannot be combined with --dry-run")
    upload_enabled = os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() == "true"
    editorial_approved = os.getenv("NEWSFLOW_EDITORIAL_APPROVED", "false").lower() == "true"
    private_staging = os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true"
    if upload_enabled and not editorial_approved and not private_staging:
        parser.error("الرفع محظور: يلزم اعتماد المراجعة التحريرية صراحةً عبر NEWSFLOW_EDITORIAL_APPROVED=true.")
    if private_staging and os.getenv("YOUTUBE_PRIVACY_STATUS", "private").lower() != "private":
        parser.error("Private staging لا يسمح إلا برفع PRIVATE.")
    if args.private_test:
        args.max_stories = 1
        if not upload_enabled:
            parser.error("Private test requires YOUTUBE_UPLOAD_ENABLED=true")
    # Verify OAuth before spending time generating audio/video.
    auth_credentials = None
    if args.private_test or (not args.dry_run and upload_enabled):
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
    (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[EDITORIAL_REVIEW] status={editorial_report['status']} accepted={editorial_report['accepted_count']} rejected={editorial_report['rejected_count']} warnings={editorial_report['warning_count']} fact_checking=not_performed")
    upload_blockers = upload_review_blockers(
        editorial_report, editorial_approved, private_staging=private_staging
    )
    visual_qa_approved = os.getenv("NEWSFLOW_VISUAL_QA_APPROVED", "false").lower() == "true"
    if upload_enabled and not visual_qa_approved and not private_staging:
        print("[SAFE] PRIVATE upload blocked: phone visual QA has not been explicitly approved.")
        upload_enabled = False
    if private_staging:
        print("[PRIVATE_STAGING] Owner-only upload; fact_checking remains not_performed and manual review is required before changing visibility.")
    if upload_enabled and upload_blockers:
        print("[SAFE] PRIVATE upload blocked: " + " | ".join(upload_blockers)
              + ". Generated video will remain an Artifact.")
        upload_enabled = False
    if not stories:
        print("[INFO] لم يتم العثور على أخبار في المصادر.")
        return
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
        duration = validate_audio_duration(probe.stdout.strip(), private_test=args.private_test)
        print(f"[AUDIO_DURATION] {duration:.1f} seconds (duration follows editorial content)")

    single_long_upload = os.getenv("NEWSFLOW_UPLOAD_SINGLE_LONG", "false").lower() == "true"
    video_title, description, tags = build_youtube_metadata(stories, bulletin_script)
    print(f"[YOUTUBE_METADATA] title={video_title} | words={len(video_title.split())} | tags={len(tags)}")

    long_video = bulletin / "long.mp4"
    make_video(video_title, audio, long_video, short=False, portrait=main_portrait, stories=stories)
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
    if upload_enabled:
        youtube_upload(long_video, video_title, description, tags, credentials=auth_credentials)

    # Shorts are separate story-specific narrations, not a vertical copy of the full bulletin.
    if not single_long_upload:
        shorts_dir = bulletin / "shorts"
        shorts_dir.mkdir(exist_ok=True)
        for index, story in enumerate(stories[:2], start=1):
            short_script = make_short_script(story)
            short_audio = shorts_dir / f"short-{index}.mp3"
            short_video = shorts_dir / f"short-{index}.mp4"
            asyncio.run(make_audio(short_script, short_audio))
            short_title, short_description, short_tags = build_short_youtube_metadata(story, short_script)
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
                    privacy_override=os.getenv("YOUTUBE_PRIVACY_STATUS", "private"), credentials=auth_credentials
                )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
import feedparser
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from newsflow.editorial import relevance, review_stories, upload_review_blockers

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
    stories = [
        item for item in stories
        if not item["published_ts"] or 0 <= now_ts - item["published_ts"] <= 72 * 3600
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
        make_opening_hook(stories),
        "أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar. سنعرض الوقائع المؤكدة، ونفصلها عن التحليل والتوقع."
    ]
    for index, story in enumerate(stories, start=1):
        summary = story["summary"] or "لم يرفق المصدر ملخصاً كافياً لهذا الخبر؛ راجعوا الرابط الأصلي للتفاصيل."
        parts.append(
            f"الخبر {index}: {story['title']}. "
            f"{summary} بحسب {story['source']}. "
            "تابعوا رابط المصدر في وصف الفيديو للتفاصيل."
        )
    parts.append(
        "كانت هذه أبرز أخبار المال والاقتصاد لهذا اليوم. "
        "تذكّروا أن الأخبار والمعلومات الواردة من المصادر قد تتغير، "
        "وأن هذا الموجز لا يمثل نصيحة استثمارية. "
        "ولا تنسوا الاشتراك في WealthRadar وتفعيل زر الجرس."
    )
    return "\n\n".join(parts)


def make_short_script(story):
    """Create an original, story-specific vertical-video narration."""
    title = str(story.get("title", "")).strip()
    summary = str(story.get("summary", "")).strip()
    source = str(story.get("source", "المصدر الأصلي")).strip()
    if not summary:
        summary = "التفاصيل الكاملة تحتاج إلى مراجعة المصدر الأصلي قبل النشر."
    hook = clean_narration(title)
    if len(hook) > 105:
        hook = hook[:102].rsplit(" ", 1)[0].rstrip("،؛:") + "…"
    return (
        f"{hook}. ما الذي يقف وراء الخبر؟ "
        f"{clean_narration(summary)} "
        f"بحسب {source}. "
        "هذه معلومات للمتابعة، وليست توصية استثمارية. "
        "راجع المصدر قبل اتخاذ أي قرار مالي. "
        "تابع WealthRadar للمزيد."
    )


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
    text = re.sub(r"\s*([،؛؟.!])\s*", r"\1 ", text)
    return text.strip()


async def make_audio(text, path):
    """Generate Egyptian Arabic narration, then master it for clear, even playback."""
    voice = os.getenv("NEWSFLOW_TTS_VOICE", "ar-EG-ShakirNeural")
    rate = os.getenv("NEWSFLOW_TTS_RATE", "-6%")
    pitch = os.getenv("NEWSFLOW_TTS_PITCH", "-2Hz")
    raw_path = path.with_name(path.stem + ".raw.mp3")
    clean_text = clean_narration(text)
    await edge_tts.Communicate(
        clean_text, voice, rate=rate, pitch=pitch
    ).save(str(raw_path))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.move(str(raw_path), str(path))
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


def make_video(title, audio, output, short=False, stories=None):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("يجب تثبيت FFmpeg وFFprobe")
    width, height = (1080, 1920) if short else (1920, 1080)
    regular_path, bold_path = find_font(False), find_font(True)
    heading_font_size = 76 if short else 72
    body_font_size = 45 if short else 42
    small_font_size = 31 if short else 28
    heading_font = ImageFont.truetype(bold_path or regular_path, heading_font_size) if bold_path or regular_path else ImageFont.load_default()
    body_font = ImageFont.truetype(regular_path, body_font_size) if regular_path else ImageFont.load_default()
    small_font = ImageFont.truetype(bold_path or regular_path, small_font_size) if bold_path or regular_path else ImageFont.load_default()
    english_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(22, small_font_size - 5)) if Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf").exists() else small_font
    brand_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    brand_font = ImageFont.truetype(brand_font_path, heading_font_size) if Path(brand_font_path).exists() else heading_font

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True, capture_output=True, text=True
    )
    total_duration = float(probe.stdout.strip())
    story_list = stories or []
    cards = [("إيه الحكاية؟", make_opening_hook(story_list), "أهم تطورات المال والأسواق.. من غير تهويل وبالمصادر", "THE STORY BEHIND THE HEADLINE")]
    for index, story in enumerate(story_list, start=1):
        cards.append((
            f"الخبر {index:02d} • {source_display_name(story.get('source', 'المصدر'))}",
            clean_narration(story.get("title", "")),
            clean_narration(story.get("summary", "")[:520]) or "راجع رابط المصدر لمعرفة التفاصيل الكاملة.",
            f"STORY {index:02d}  |  MARKET WATCH"
        ))
    cards.append((
        "قبل أي قرار مالي",
        "تابع المصدر الأصلي وقارن المعلومات",
        "اشترك في WealthRadar وفعّل زر الجرس لمتابعة موجز الأخبار القادم",
        "FOLLOW • SUBSCRIBE • STAY INFORMED"
    ))

    weights = [max(60, len(head) + len(body)) for _, head, body, _ in cards]
    weight_total = sum(weights)
    durations = [total_duration * weight / weight_total for weight in weights]
    durations[-1] += total_duration - sum(durations)

    frame_dir = output.parent / f"{output.stem}_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []

    def wrap_text(draw, value, font, max_width, limit):
        lines, current = [], ""
        direction = "rtl" if re.search(r"[\u0600-\u06ff]", str(value)) else "ltr"
        for word in str(value).split():
            trial = (current + " " + word).strip()
            bounds = draw.textbbox((0, 0), trial, font=font, direction=direction)
            if bounds[2] - bounds[0] > max_width and current:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines[:limit]

    try:
        for index, (heading, headline, summary, english_label) in enumerate(cards):
            accent = (42, 220, 198) if index % 2 == 0 else (255, 190, 92)
            image = Image.new("RGB", (width, height), (7, 15, 31))
            draw = ImageDraw.Draw(image)
            draw.ellipse((int(width * .62), -int(height * .35), int(width * 1.12), int(height * .25)), fill=(15, 48, 70))
            draw.ellipse((-int(width * .28), int(height * .65), int(width * .30), int(height * 1.15)), fill=(13, 39, 58))
            for offset in range(0, width, max(120, width // 12)):
                draw.line((offset, 0, offset - int(height * .28), height), fill=(14, 29, 48), width=2)
            draw.rounded_rectangle(
                (int(width*.045), int(height*.055), int(width*.955), int(height*.945)),
                radius=max(28, width//42), fill=(12, 29, 49), outline=(34, 75, 96), width=3
            )
            draw.rounded_rectangle(
                (int(width*.075), int(height*.085), int(width*.925), int(height*.19)),
                radius=28, fill=(17, 45, 65), outline=(35, 87, 105), width=2
            )
            draw.text((width//2, int(height*.12)), "WealthRadar", font=brand_font,
                      fill=(247, 250, 255), anchor="mm")
            draw.text((width//2, int(height*.165)), "MONEY  •  MARKETS  •  BUSINESS",
                      font=english_font, fill=accent, anchor="mm")
            draw.rounded_rectangle(
                (int(width*.25), int(height*.235), int(width*.75), int(height*.30)),
                radius=22, fill=(accent[0]//4, accent[1]//4, accent[2]//4)
            )
            draw.text((width//2, int(height*.267)), heading, font=small_font,
                      fill=accent, anchor="mm", direction="rtl")
            draw.text((width//2, int(height*.325)), english_label, font=english_font,
                      fill=(154, 184, 202), anchor="mm")
            draw.line((int(width*.22), int(height*.365), int(width*.78), int(height*.365)),
                      fill=accent, width=max(3, width//500))

            headline_lines = wrap_text(draw, headline, heading_font, int(width*.78), 4 if short else 3)
            y = int(height * .43) - len(headline_lines) * (heading_font_size + 18) // 2
            for line in headline_lines:
                draw.text((width // 2, y), line, font=heading_font,
                          fill=(255, 255, 255), anchor="mm", direction=("rtl" if re.search(r"[\u0600-\u06ff]", line) else "ltr"))
                y += heading_font_size + 18

            body_lines = wrap_text(draw, summary, body_font, int(width*.76), 5 if short else 4)
            y += int(height*.055)
            for line in body_lines:
                draw.text((width // 2, y), line, font=body_font,
                          fill=(198, 215, 229), anchor="mm", direction=("rtl" if re.search(r"[\u0600-\u06ff]", line) else "ltr"))
                y += body_font_size + (14 if short else 12)

            footer_y = int(height*.86)
            draw.line((int(width*.28), footer_y-int(height*.035), int(width*.72), footer_y-int(height*.035)),
                      fill=(43, 78, 99), width=2)
            draw.text((width // 2, footer_y), "المال والاقتصاد ببساطة",
                      font=small_font, fill=(225, 235, 244), anchor="mm", direction="rtl")
            draw.text((width // 2, int(height*.90)), "FOLLOW WEALTHRADAR  •  KNOW MORE",
                      font=english_font, fill=accent, anchor="mm")
            frame = frame_dir / f"slide-{index:02d}.png"
            image.save(frame)
            frame_paths.append(frame)

        command = [ffmpeg, "-y"]
        for frame, seconds in zip(frame_paths, durations):
            command += ["-loop", "1", "-t", f"{seconds:.3f}", "-i", str(frame)]
        command += ["-i", str(audio)]
        filters = []
        for index in range(len(frame_paths)):
            filters.append(
                f"[{index}:v]scale={width}:{height},setsar=1,format=yuv420p[v{index}]"
            )
        concat_inputs = "".join(f"[v{index}]" for index in range(len(frame_paths)))
        filters.append(f"{concat_inputs}concat=n={len(frame_paths)}:v=1:a=0[v]")
        command += [
            "-filter_complex", ";".join(filters),
            "-map", "[v]", "-map", f"{len(frame_paths)}:a:0",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(output)
        ]
        subprocess.run(command, check=True, capture_output=True)
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)

def validate_video(video_path: Path, audio_path: Path, expected_short: bool = False):
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
    expected_dimensions = (1080, 1920) if expected_short else (1920, 1080)
    if (width, height) != expected_dimensions:
        orientation = "رأسياً" if expected_short else "أفقياً"
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
    if upload_enabled and not editorial_approved:
        parser.error("الرفع محظور: يلزم اعتماد المراجعة التحريرية صراحةً عبر NEWSFLOW_EDITORIAL_APPROVED=true.")
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
    upload_blockers = upload_review_blockers(editorial_report, editorial_approved)
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
    duration = None
    if ffprobe:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            check=True, capture_output=True, text=True
        )
        duration = float(probe.stdout.strip())
        print(f"[AUDIO_DURATION] {duration:.1f} seconds (target: about 180 seconds)")
        if not args.private_test and not 150 <= duration <= 210:
            raise RuntimeError(
                f"مدة التعليق الصوتي {duration:.1f} ثانية خارج النطاق المستهدف 150–210 ثانية؛ "
                "تم إيقاف بناء الفيديو بدلاً من إخراج نشرة بطول غير مناسب."
            )

    single_long_upload = os.getenv("NEWSFLOW_UPLOAD_SINGLE_LONG", "false").lower() == "true"
    video_title, description, tags = build_youtube_metadata(stories, bulletin_script)
    print(f"[YOUTUBE_METADATA] title={video_title} | words={len(video_title.split())} | tags={len(tags)}")

    long_video = bulletin / "long.mp4"
    make_video(video_title, audio, long_video, short=False, stories=stories)
    validate_video(long_video, audio)
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
            short_title, short_description, short_tags = build_youtube_metadata([story], short_script)
            short_title = f"{short_title[:78].rstrip()} #Shorts"
            make_video(short_title, short_audio, short_video, short=True, stories=[story])
            validate_video(short_video, short_audio, expected_short=True)
            print(f"[SHORT_READY] {short_video} duration-specific_story={story['id']}")
            if upload_enabled:
                youtube_upload(
                    short_video, short_title, short_description, short_tags,
                    privacy_override=os.getenv("YOUTUBE_PRIVACY_STATUS", "public"), credentials=auth_credentials
                )


if __name__ == "__main__":
    main()

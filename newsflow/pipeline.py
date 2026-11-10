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
from newsflow.editorial import relevance, review_stories

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def config():
    with (ROOT / "config" / "sources.yml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    selected, source_counts, rejected = [], {}, []
    for story in stories:
        is_relevant, reason = relevance(story)
        if not is_relevant:
            rejected.append({"id": story["id"], "title": story["title"],
                             "source": story["source"], "reasons": [reason]})
            continue
        story["relevance_reason"] = reason
        if source_counts.get(story["source"], 0) >= 3:
            continue
        selected.append(story)
        source_counts[story["source"]] = source_counts.get(story["source"], 0) + 1
        if len(selected) >= max_stories:
            break
    for story in selected:
        story.pop("published_ts", None)
    return selected, rejected

def make_script(stories):
    parts = [
        "أهلاً بكم في أهم الأخبار الاقتصادية والمالية من WealthRadar. "
        "نستعرض معكم أبرز التطورات التي قد تؤثر في الأسواق وأموالكم."
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
    return (
        "أهلاً بكم في WealthRadar. خبر اقتصادي مهم: "
        f"{title}. "
        f"{summary} "
        f"المعلومة دي بحسب {source}. "
        "المهم نفهم إن الخبر وحده مش توصية بالشراء أو البيع؛ راجع التفاصيل والسياق قبل أي قرار مالي. "
        "تابعوا WealthRadar للمزيد من الأخبار الاقتصادية، ولا تنسوا الاشتراك وتفعيل زر الجرس."
    )


def build_youtube_metadata(stories, script):
    title = f"أهم {len(stories)} أخبار اقتصادية اليوم | WealthRadar"
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

async def make_audio(text, path):
    voice = os.getenv("NEWSFLOW_TTS_VOICE", "ar-EG-ShakirNeural")
    rate = os.getenv("NEWSFLOW_TTS_RATE", "+0%")
    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))


def find_font():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for item in candidates:
        if Path(item).exists():
            return item
    return None


def make_video(title, audio, output, short=False, stories=None):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("يجب تثبيت FFmpeg وFFprobe")
    width, height = (1080, 1920) if short else (1920, 1080)
    font_path = find_font()
    heading_font_size = 72 if short else 66
    body_font_size = 48 if short else 44
    small_font_size = 34 if short else 30
    heading_font = ImageFont.truetype(font_path, heading_font_size) if font_path else ImageFont.load_default()
    body_font = ImageFont.truetype(font_path, body_font_size) if font_path else ImageFont.load_default()
    small_font = ImageFont.truetype(font_path, small_font_size) if font_path else ImageFont.load_default()

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True, capture_output=True, text=True
    )
    total_duration = float(probe.stdout.strip())
    story_list = stories or []
    cards = [("نشرة WealthRadar", title, "أهم تطورات المال والاقتصاد في موجز واحد")]
    for index, story in enumerate(story_list, start=1):
        cards.append((
            f"الخبر {index} • {story.get('source', 'المصدر')}",
            story.get("title", ""),
            story.get("summary", "")[:520] or "راجع رابط المصدر لمعرفة التفاصيل الكاملة."
        ))
    cards.append((
        "قبل أي قرار مالي",
        "تابع المصدر الأصلي وقارن المعلومات",
        "اشترك في WealthRadar وفعّل زر الجرس لمتابعة موجز الأخبار القادم"
    ))

    weights = [max(60, len(head) + len(body)) for head, body, _ in cards]
    weight_total = sum(weights)
    durations = [total_duration * weight / weight_total for weight in weights]
    durations[-1] += total_duration - sum(durations)

    frame_dir = output.parent / f"{output.stem}_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []

    def wrap_text(draw, value, font, max_width, limit):
        lines, current = [], ""
        for word in str(value).split():
            trial = (current + " " + word).strip()
            bounds = draw.textbbox((0, 0), trial, font=font, direction="rtl")
            if bounds[2] - bounds[0] > max_width and current:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines[:limit]

    try:
        for index, (heading, headline, summary) in enumerate(cards):
            image = Image.new("RGB", (width, height), (11, 20, 35))
            draw = ImageDraw.Draw(image)
            accent = (35, 183, 174) if index % 2 == 0 else (221, 171, 77)
            draw.rectangle((0, 0, width, 22), fill=accent)
            draw.rounded_rectangle(
                (70, 105, width - 70, height - 105),
                radius=42, fill=(19, 39, 60), outline=accent, width=4
            )
            draw.text(
                (width // 2, 205), "WealthRadar", font=heading_font,
                fill=(255, 255, 255), anchor="mm"
            )
            draw.text(
                (width // 2, 300), heading, font=small_font,
                fill=accent, anchor="mm", direction="rtl"
            )
            draw.line((width // 2 - 180, 365, width // 2 + 180, 365), fill=accent, width=5)

            headline_lines = wrap_text(draw, headline, heading_font, width - 220, 4)
            y = int(height * 0.40) - len(headline_lines) * (heading_font_size + 18) // 2
            for line in headline_lines:
                draw.text((width // 2, y), line, font=heading_font,
                          fill=(255, 255, 255), anchor="mm", direction="rtl")
                y += heading_font_size + 18

            body_lines = wrap_text(draw, summary, body_font, width - 240, 7)
            y += 85
            for line in body_lines:
                draw.text((width // 2, y), line, font=body_font,
                          fill=(202, 216, 229), anchor="mm", direction="rtl")
                y += body_font_size + 22

            draw.text(
                (width // 2, height - 190), "المال والاقتصاد ببساطة",
                font=small_font, fill=(160, 190, 220), anchor="mm", direction="rtl"
            )
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
    if expected_short and not (height > width):
        raise RuntimeError("فشل فحص النسخة القصيرة: يجب أن يكون الفيديو رأسياً")
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
    status = privacy_override or os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
    if status not in {"private", "unlisted", "public"}:
        raise ValueError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public")
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
    if returned_status != status:
        raise RuntimeError("استجابة YouTube لم تؤكد الخصوصية المطلوبة؛ لن نعلن نجاح التحقق.")
    print(f"[UPLOAD_VERIFIED] https://youtu.be/{video_id} privacy={status}")

def main():
    parser = argparse.ArgumentParser(description="WealthRadar Arabic financial news pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Collect and write drafts only")
    parser.add_argument("--max-stories", type=int, default=int(os.getenv("NEWSFLOW_MAX_STORIES", "8")))
    parser.add_argument("--private-test", action="store_true", help="Upload exactly one long video with private privacy")
    args = parser.parse_args()
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
        if not 150 <= duration <= 210:
            print("[WARN] مدة التعليق الصوتي بعيدة عن 3 دقائق؛ راجع النص أو عدد الأخبار قبل النشر.")

    single_long_upload = os.getenv("NEWSFLOW_UPLOAD_SINGLE_LONG", "false").lower() == "true"
    video_title, description, tags = build_youtube_metadata(stories, bulletin_script)
    print(f"[YOUTUBE_METADATA] title={video_title} | words={len(video_title.split())} | tags={len(tags)}")

    long_video = bulletin / "long.mp4"
    make_video(video_title, audio, long_video, short=False, stories=stories)
    validate_video(long_video, audio)
    if args.private_test:
        youtube_upload(
            long_video, video_title, description, tags,
            privacy_override="private", credentials=auth_credentials
        )
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
            short_title = f"{story['title'][:75]} | WealthRadar #Shorts"
            make_video(short_title, short_audio, short_video, short=True, stories=[story])
            validate_video(short_video, short_audio, expected_short=True)
            print(f"[SHORT_READY] {short_video} duration-specific_story={story['id']}")
            if upload_enabled:
                youtube_upload(
                    short_video, short_title, short_description, short_tags,
                    privacy_override="private", credentials=auth_credentials
                )


if __name__ == "__main__":
    main()

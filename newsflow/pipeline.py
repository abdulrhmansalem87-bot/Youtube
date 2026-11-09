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
            for entry in parsed.entries[:30]:
                link = entry.get("link", "").strip()
                title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                published = entry.get("published", entry.get("updated", ""))
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
                summary = re.sub(r"\s+", " ", summary).strip()[:1200]
                stories.append({
                    "id": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title": title, "link": link, "published": published,
                    "summary": summary, "source": source["name"],
                    "category": source.get("category", "عام"),
                })
        except Exception as exc:
            print(f"[WARN] تعذر جلب {source.get('name')}: {exc}")
    stories.sort(key=lambda x: x.get("published", ""), reverse=True)
    return stories[:max_stories]


def make_script(story):
    # Extractive draft only: do not invent facts or imply independent verification.
    summary = story["summary"] or "لا يتوفر ملخص في موجز المصدر؛ يلزم استكمال المعلومات تحريرياً."
    return (
        f"نشرة موجزة من NewsFlow.\n\n"
        f"عنوان الخبر: {story['title']}\n\n"
        f"{summary}\n\n"
        f"المصدر المنشور: {story['source']}. "
        f"يمكنكم الرجوع إلى الرابط الأصلي في وصف الفيديو. "
        f"هذه مسودة آلية أولية وليست تحققاً مستقلاً من صحة الخبر. "
        f"تابعونا للمزيد من التغطيات."
    )


async def make_audio(text, path):
    voice = os.getenv("NEWSFLOW_TTS_VOICE", "ar-EG-SalmaNeural")
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


def make_video(title, audio, output, short=False):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg غير مثبت")
    width, height = (1080, 1920) if short else (1920, 1080)
    image = Image.new("RGB", (width, height), (16, 24, 40))
    draw = ImageDraw.Draw(image)
    font_path = find_font()
    font_size = 66 if short else 58
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    # Simple RTL-friendly title card; font availability varies by runner.
    words, lines, line = title, [], ""
    for word in words.split():
        trial = (line + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] > width - 120:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    y = height // 2 - len(lines) * (font_size + 18) // 2
    for item in lines[:8]:
        draw.text((width // 2, y), item, font=font, fill="white", anchor="mm", direction="rtl")
        y += font_size + 18
    draw.text((width // 2, height - 90), "NewsFlow AI • مسودة آلية للمراجعة", font=font, fill=(160, 190, 220), anchor="mm")
    still = output.with_suffix(".png")
    image.save(still)
    subprocess.run([
        ffmpeg, "-y", "-loop", "1", "-i", str(still), "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
        "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest",
        "-vf", f"scale={width}:{height}", str(output)
    ], check=True, capture_output=True)
    still.unlink(missing_ok=True)


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
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
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
    video_path: Path, title: str, description: str,
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
        "snippet": {"title": title[:100], "description": description[:5000],
                    "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "25"),
                    "defaultLanguage": "ar"},
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
    confirmed = youtube.videos().list(part="status", id=video_id).execute()
    items = confirmed.get("items", [])
    if not items or items[0].get("status", {}).get("privacyStatus") != status:
        raise RuntimeError("تم الرفع لكن تعذر تأكيد حالة الخصوصية المطلوبة من YouTube")
    print(f"[UPLOAD_VERIFIED] https://youtu.be/{video_id} privacy={status}")

def main():
    parser = argparse.ArgumentParser(description="NewsFlow AI Arabic news pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Collect and write drafts only")
    parser.add_argument("--max-stories", type=int, default=int(os.getenv("NEWSFLOW_MAX_STORIES", "5")))
    parser.add_argument("--private-test", action="store_true", help="Upload exactly one long video with private privacy")
    args = parser.parse_args()
    if args.private_test and args.dry_run:
        parser.error("--private-test cannot be combined with --dry-run")
    upload_enabled = os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() == "true"
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
    stories = collect(args.max_stories)
    (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8")
    if not stories:
        print("[INFO] لم يتم العثور على أخبار في المصادر.")
        return
    for index, story in enumerate(stories, start=1):
        script = make_script(story)
        folder = out / story["id"]
        folder.mkdir(exist_ok=True)
        (folder / "script.txt").write_text(script, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DRAFT] {story['title']} — {story['link']}")
        if args.dry_run:
            continue
        audio = folder / "voice.mp3"
        asyncio.run(make_audio(script, audio))
        variants = (("long", False),) if args.private_test else (("long", False), ("short", True))
        for label, short in variants:
            video = folder / f"{label}.mp4"
            make_video(story["title"], audio, video, short=short)
            # Scheduled and dry-run executions never upload. Manual normal runs upload
            # both variants when YOUTUBE_UPLOAD_ENABLED=true; private-test uploads one long video.
            if args.private_test:
                youtube_upload(
                    video, story["title"], f"{script}\n\nالمصدر: {story['link']}",
                    privacy_override="private", credentials=auth_credentials
                )
            elif upload_enabled:
                youtube_upload(
                    video, story["title"], f"{script}\n\nالمصدر: {story['link']}",
                    credentials=auth_credentials
                )


if __name__ == "__main__":
    main()

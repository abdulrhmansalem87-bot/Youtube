from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("مسودة", "نيوزفلو", "newsflow", "draft", "ai-generated")
PEXELS_API = "https://api.pexels.com/videos/search"


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text, flags=re.UNICODE)


def validate_plan(plan: dict) -> list[str]:
    errors: list[str] = []
    title = str(plan.get("title", "")).strip()
    if not title or len(title) > 50 or "#shorts" not in title.lower():
        errors.append("العنوان مطلوب، بحد أقصى 50 حرفاً، ويجب أن يتضمن #shorts.")

    narration = plan.get("narration")
    if not isinstance(narration, list) or not narration:
        errors.append("narration يجب أن تكون قائمة جمل صوتية.")
        narration = []
    for index, sentence in enumerate(narration, 1):
        if not isinstance(sentence, str) or not sentence.strip():
            errors.append(f"الجملة الصوتية رقم {index} فارغة أو غير صالحة.")
            continue
        count = len(_words(sentence))
        if count > 8:
            errors.append(f"الجملة الصوتية رقم {index} تتجاوز 8 كلمات ({count}).")

    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes يجب أن تحتوي على مشاهد B-roll.")
        scenes = []
    total = 0.0
    for index, scene in enumerate(scenes, 1):
        try:
            duration = float(scene["duration"])
            total += duration
            if not 1.5 <= duration <= 2.5:
                errors.append(f"المشهد {index}: المدة يجب أن تكون بين 1.5 و2.5 ثانية.")
        except (KeyError, TypeError, ValueError):
            errors.append(f"المشهد {index}: مدة غير صالحة.")
        query = str(scene.get("query", "")).strip()
        if not query:
            errors.append(f"المشهد {index}: وصف B-roll بالإنجليزية مطلوب.")
        caption = scene.get("caption")
        if not isinstance(caption, list) or any(not isinstance(word, str) or not word.strip() for word in caption):
            errors.append(f"المشهد {index}: الكلمات المفتاحية غير صالحة.")
        elif not 2 <= sum(len(_words(word)) for word in caption) <= 3:
            errors.append(f"المشهد {index}: اكتب كلمتين أو ثلاث كلمات مفتاحية بالضبط.")

    if not 30 <= total <= 45:
        errors.append(f"إجمالي المشاهد {total:.1f} ثانية؛ المطلوب من 30 إلى 45 ثانية.")

    loop_phrase = str(plan.get("loop_phrase", "")).strip()
    if not loop_phrase or len(narration) < 2:
        errors.append("أضف loop_phrase واربط بها أول جملة وآخر جملة.")
    elif loop_phrase not in narration[0] or loop_phrase not in narration[-1]:
        errors.append("يجب أن تظهر loop_phrase في أول جملة وآخر جملة لتحقيق Loop.")

    visible_text = " ".join([title, *[str(x) for x in narration]])
    visible_text += " " + " ".join(
        " ".join(map(str, s.get("caption", []))) for s in scenes if isinstance(s, dict)
    )
    if any(term in visible_text.lower() for term in FORBIDDEN):
        errors.append("النص يحتوي على عبارة تحريرية ممنوعة.")

    if plan.get("brand", "WealthRadar") != "WealthRadar":
        errors.append("اسم العلامة المعتمد هو WealthRadar.")
    return errors


def load_plan(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _request_json(url: str, api_key: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": api_key})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def find_pexels_video(query: str, api_key: str) -> str:
    params = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": 12})
    payload = _request_json(f"{PEXELS_API}?{params}", api_key)
    candidates = []
    for video in payload.get("videos", []):
        for item in video.get("video_files", []):
            width, height = int(item.get("width") or 0), int(item.get("height") or 0)
            link = item.get("link")
            if link and height > width and width >= 720:
                candidates.append((width * height, link))
    if not candidates:
        raise RuntimeError(f"لم يعثر Pexels على مقطع رأسي مناسب لعبارة: {query}")
    candidates.sort(reverse=True)
    return candidates[0][1]


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "WealthRadarShorts/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)


async def _make_voice(text: str, destination: Path, voice: str) -> str:
    """Generate Arabic male narration with retries and automatic voice fallback."""
    voices = list(dict.fromkeys([
        voice,
        "ar-EG-ShakirNeural",
        "ar-SA-HamedNeural",
        "ar-AE-HamdanNeural",
    ]))
    failures: list[str] = []
    for candidate in voices:
        for attempt in range(1, 3):
            try:
                destination.unlink(missing_ok=True)
                await edge_tts.Communicate(text, candidate, rate="+8%").save(str(destination))
                if not destination.is_file() or destination.stat().st_size < 1_000:
                    raise RuntimeError("ملف الصوت الناتج فارغ أو غير مكتمل.")
                print(f"[VOICE_READY] {candidate} | attempt {attempt}")
                return candidate
            except Exception as exc:
                destination.unlink(missing_ok=True)
                failures.append(f"{candidate} (محاولة {attempt}): {type(exc).__name__}")
                print(f"[VOICE_RETRY] {candidate} | attempt {attempt} failed: {type(exc).__name__}")
                if attempt == 1:
                    await asyncio.sleep(2)
    raise RuntimeError(
        "تعذر إنشاء التعليق الصوتي بعد إعادة المحاولة وتجربة الأصوات الرجالية العربية البديلة. "
        + " | ".join(failures)
    )


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _ass_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _write_ass(path: Path, caption: list[str], seconds: float) -> None:
    text = "   ".join(_ass_escape(word) for word in caption)
    content = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Keywords,DejaVu Sans,78,&H0000D7FF,&H000000FF,&H00101010,"
        "&H80000000,-1,0,1,7,2,5,70,70,0,1\n"
        "Style: Brand,DejaVu Sans,34,&H00FFFFFF,&H000000FF,&H00101010,"
        "&H80000000,-1,0,1,3,1,2,40,40,90,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:{seconds:05.2f},Keywords,,0,0,0,,{text}\n"
        f"Dialogue: 1,0:00:00.00,0:00:{seconds:05.2f},Brand,,0,0,0,,WealthRadar\n"
    )
    path.write_text(content, encoding="utf-8-sig")



def validate_video_probe(metadata: dict) -> None:
    """Fail closed unless the rendered MP4 is a valid 1080x1920 short with audio."""
    streams = metadata.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    try:
        duration = float(metadata.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if not video:
        raise RuntimeError("فحص الفيديو فشل: لا يوجد مسار فيديو داخل MP4.")
    if not audio:
        raise RuntimeError("فحص الفيديو فشل: لا يوجد مسار صوت داخل MP4.")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (1080, 1920):
        raise RuntimeError("فحص الفيديو فشل: المقاس المطلوب 1080x1920.")
    if video.get("codec_name") != "h264":
        raise RuntimeError("فحص الفيديو فشل: ترميز الصورة يجب أن يكون H.264.")
    if audio.get("codec_name") != "aac":
        raise RuntimeError("فحص الفيديو فشل: ترميز الصوت يجب أن يكون AAC.")
    if not 30.0 <= duration <= 45.0:
        raise RuntimeError(f"فحص الفيديو فشل: المدة النهائية {duration:.1f}s خارج 30–45 ثانية.")


def validate_rendered_video(path: Path) -> float:
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError("فحص الفيديو فشل: ملف MP4 غير موجود أو حجمه غير صالح.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    metadata = json.loads(result.stdout)
    validate_video_probe(metadata)
    return float(metadata["format"]["duration"])


def render(plan: dict, output: Path, api_key: str) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("يجب تثبيت FFmpeg وFFprobe قبل إنتاج الفيديو.")
    output.mkdir(parents=True, exist_ok=True)
    narration = " ".join(sentence.strip() for sentence in plan["narration"])
    voice_path = output / "voice.mp3"
    voice = os.getenv("WEALTHRADAR_TTS_VOICE", "ar-EG-ShakirNeural")
    asyncio.run(_make_voice(narration, voice_path, voice))
    voice_duration = _duration(voice_path)
    if not 30 <= voice_duration <= 45:
        raise RuntimeError(f"مدة التعليق الصوتي {voice_duration:.1f}s خارج النطاق 30–45 ثانية.")
    scene_total = sum(float(scene["duration"]) for scene in plan["scenes"])
    scale = voice_duration / scene_total
    scene_durations = [float(scene["duration"]) * scale for scene in plan["scenes"]]
    if any(not 1.5 <= seconds <= 2.5 for seconds in scene_durations):
        raise RuntimeError(
            "لا يمكن موازنة مدة المشاهد مع الصوت مع الحفاظ على إيقاع 1.5–2.5 ثانية. "
            "عدّل النص أو مدد المشاهد."
        )

    with tempfile.TemporaryDirectory(prefix="wealthradar-") as temp:
        work = Path(temp)
        segments: list[Path] = []
        for index, (scene, seconds) in enumerate(zip(plan["scenes"], scene_durations), 1):
            source_url = find_pexels_video(scene["query"], api_key)
            raw = work / f"source-{index:02d}.mp4"
            ass = work / f"caption-{index:02d}.ass"
            segment = work / f"segment-{index:02d}.mp4"
            _download(source_url, raw)
            _write_ass(ass, scene["caption"], seconds)
            subtitle_path = str(ass.resolve()).replace("\\", "/").replace(":", r"\:")
            _run([
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(raw), "-t", f"{seconds:.2f}",
                "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,"
                       f"crop=1080:1920,setsar=1,subtitles='{subtitle_path}'",
                "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", str(segment),
            ])
            segments.append(segment)

        concat = work / "concat.txt"
        concat.write_text(
            "".join(f"file '{item.as_posix()}'\n" for item in segments),
            encoding="utf-8",
        )
        silent = work / "visual.mp4"
        _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
              "-c", "copy", str(silent)])
        final = output / "WealthRadar-Short.mp4"
        _run([ffmpeg, "-y", "-i", str(silent), "-i", str(voice_path),
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "192k", "-shortest",
              "-movflags", "+faststart", str(final)])
    final_duration = validate_rendered_video(final)
    print(f"[SHORT_READY] {final} | 1080x1920 | {final_duration:.1f}s | H.264/AAC verified")
    return final



def upload_private_video(video_path: Path, title: str) -> str:
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(
            "لا يمكن الرفع الخاص؛ أسرار GitHub الناقصة: " + ", ".join(missing)
        )
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    try:
        credentials.refresh(Request())
    except Exception as exc:
        raise RuntimeError(
            "فشل تجديد صلاحية YouTube OAuth. راجع Client ID وClient Secret وRefresh Token "
            "وتأكد أنها من مشروع Google OAuth نفسه. لم يتم رفع الفيديو."
        ) from None
    if not credentials.valid:
        raise RuntimeError("لم يؤكد Google صلاحية OAuth؛ لم يتم رفع الفيديو.")

    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": "محتوى مالي تثقيفي من قناة WealthRadar.",
                "categoryId": "27",
                "defaultLanguage": "ar",
                "tags": ["WealthRadar", "التمويل", "الاستثمار", "الثقافة المالية"],
            },
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True),
    )
    response = request.execute()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube لم يُرجع معرّف الفيديو؛ تعذر تأكيد الرفع.")
    confirmed = youtube.videos().list(part="status", id=video_id).execute()
    items = confirmed.get("items", [])
    if not items or items[0].get("status", {}).get("privacyStatus") != "private":
        raise RuntimeError("لم يتم تأكيد أن الفيديو مرفوع بخصوصية Private.")
    url = f"https://youtu.be/{video_id}"
    print(f"[UPLOAD_PRIVATE_VERIFIED] {url}")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="WealthRadar Shorts producer")
    parser.add_argument("--plan", required=True, type=Path, help="JSON production plan")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--upload-private", action="store_true", help="Upload an existing rendered MP4 as private")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "wealthradar")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    errors = validate_plan(plan)
    if errors:
        for error in errors:
            print(f"[INVALID] {error}")
        raise SystemExit(2)
    print("[PLAN_VALID] حزمة WealthRadar اجتازت فحص المواصفات.")
    if args.validate_only:
        return
    if args.upload_private:
        video_path = args.output / "WealthRadar-Short.mp4"
        validate_rendered_video(video_path)
        upload_private_video(video_path, str(plan["title"]))
        return
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("أضف GitHub Secret باسم PEXELS_API_KEY لإنتاج مقاطع B-roll.")
    render(plan, args.output, api_key)


if __name__ == "__main__":
    main()

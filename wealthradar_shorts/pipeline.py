from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("مسودة", "نيوزفلو", "newsflow", "draft", "ai-generated")
PEXELS_API = "https://api.pexels.com/v1/videos/search"


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text, flags=re.UNICODE)


def validate_plan(plan: dict) -> list[str]:
    errors: list[str] = []
    title = str(plan.get("title", "")).strip()
    if not title or len(title) > 50 or "#shorts" not in title.lower():
        errors.append("العنوان مطلوب، بحد أقصى 50 حرفاً، ويجب أن يتضمن #shorts.")

    voiceover_path = str(plan.get("voiceover_path", "")).strip()
    if not voiceover_path:
        errors.append("voiceover_path مطلوب لتسجيل صوت المقدم الأصلي؛ لا يُسمح بتوليد صوت آلي.")
    elif Path(voiceover_path).is_absolute() or ".." in Path(voiceover_path).parts:
        errors.append("voiceover_path يجب أن يكون مساراً نسبياً آمناً داخل المستودع.")
    elif Path(voiceover_path).suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac"}:
        errors.append("voiceover_path يجب أن يشير إلى ملف صوت WAV أو MP3 أو M4A أو AAC.")

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
    if any(key in plan for key in ("description", "tags", "keywords")):
        description = str(plan.get("description", "")).strip()
        tags = plan.get("tags")
        keywords = plan.get("keywords")
        if len(description) < 80:
            errors.append("وصف النشر SEO مطلوب (80 حرفاً على الأقل).")
        if not isinstance(tags, list) or len(tags) < 5 or any(not str(tag).strip() for tag in tags):
            errors.append("أضف 5 وسوم YouTube صالحة على الأقل.")
        elif len(",".join(str(tag) for tag in tags)) > 500:
            errors.append("إجمالي وسوم YouTube يتجاوز حد 500 حرف.")
        if not isinstance(keywords, list) or len(keywords) < 5 or any(not str(word).strip() for word in keywords):
            errors.append("أضف 5 كلمات مفتاحية صالحة على الأقل.")

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
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "WealthRadarShorts/0.2",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Log only safe response diagnostics; never print the API key or request headers.
        try:
            body = exc.read(512).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        body = " ".join(body.split()).replace(api_key, "[REDACTED]")[:400]
        request_id = (
            exc.headers.get("X-Request-Id")
            or exc.headers.get("X-Correlation-Id")
            or "unavailable"
        )
        remaining = exc.headers.get("X-Ratelimit-Remaining", "unavailable")
        print(
            f"[PEXELS_HTTP_ERROR] status={exc.code} request_id={request_id} "
            f"rate_limit_remaining={remaining} response={body or '[empty]'}"
        )
        raise


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

 
def require_pexels_api_key(api_key: str) -> str:
    value = str(api_key or "").strip()
    if not value:
        raise RuntimeError(
            "PEXELS_API_KEY is unavailable; refusing to render without licensed B-roll."
        )
    return value


def stock_footage_error(index: int, exc: Exception) -> RuntimeError:
    status = getattr(exc, "code", None)
    detail = f"HTTP {status}" if status is not None else type(exc).__name__
    reason = getattr(exc, "reason", None)
    if reason:
        detail += f" ({str(reason)[:120]})"
    if status == 401:
        action = "رفض Pexels مفتاح API؛ تحقق من أن PEXELS_API_KEY صحيح ونشط."
    elif status == 403:
        action = (
            "Pexels رفض الوصول؛ تحقق من قيود المفتاح أو حالة الحساب/الحصة "
            "من لوحة Pexels. لا يمكن تجاوز الرفض برمجياً."
        )
    else:
        action = "راجع اتصال Pexels وحالة الخدمة ثم أعد المحاولة."
    return RuntimeError(
        f"تعذر الحصول على B-roll مرخّص للمشهد {index} ({detail}). "
        f"{action} أُوقف إنتاج الفيديو؛ الخلفيات الثابتة غير مسموح بها."
    )


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)


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
    api_key = require_pexels_api_key(api_key)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("يجب تثبيت FFmpeg وFFprobe قبل إنتاج الفيديو.")
    output.mkdir(parents=True, exist_ok=True)
    voiceover_relative = Path(str(plan["voiceover_path"]))
    voice_path = (ROOT / voiceover_relative).resolve()
    try:
        voice_path.relative_to(ROOT.resolve())
    except ValueError:
        raise RuntimeError("مسار تسجيل الصوت خارج المستودع؛ تم إيقاف الإنتاج.") from None
    if not voice_path.is_file() or voice_path.stat().st_size < 8_000:
        raise RuntimeError(
            f"تسجيل صوت المقدم الأصلي غير موجود أو غير صالح: {plan['voiceover_path']}. "
            "لن يتم توليد صوت بديل آلياً."
        )
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
            ass = work / f"caption-{index:02d}.ass"
            segment = work / f"segment-{index:02d}.mp4"
            _write_ass(ass, scene["caption"], seconds)
            try:
                if not api_key:
                    raise RuntimeError("PEXELS_API_KEY is unavailable")
                source_url = find_pexels_video(scene["query"], api_key)
                raw = work / f"source-{index:02d}.mp4"
                _download(source_url, raw)
                subtitle_path = str(ass.resolve()).replace("\\", "/").replace(":", r"\:")
                _run([
                    ffmpeg, "-y", "-stream_loop", "-1", "-i", str(raw), "-t", f"{seconds:.2f}",
                    "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,"
                           f"crop=1080:1920,setsar=1,subtitles='{subtitle_path}'",
                    "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", str(segment),
                ])
            except Exception as exc:
                failure = stock_footage_error(index, exc)
                status = getattr(exc, "code", type(exc).__name__)
                print(f"[STOCK_FOOTAGE_FATAL] scene={index} | {status}")
                raise failure from None
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
    render_metadata = {
        # The plan validator and render() require an actual supplied voice recording.
        "voice_source": "owner_recording",
        # This renderer does not insert the channel owner's on-camera video yet.
        "presenter_source": "none",
        "broll_source": "pexels",
        "broll_scene_count": len(segments),
        "voice_duration_seconds": round(voice_duration, 2),
        "video_duration_seconds": round(final_duration, 2),
    }
    (output / "render_metadata.json").write_text(
        json.dumps(render_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SHORT_READY] {final} | 1080x1920 | {final_duration:.1f}s | H.264/AAC verified")
    return final



def verify_target_channel(youtube, expected_title: str | None = None) -> str:
    """Fail closed unless the OAuth account owns exactly one WealthRadar channel."""
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


def require_owner_identity_metadata(video_path: Path) -> dict:
    """Fail closed unless the MP4 was rendered with owner voice, owner video and licensed B-roll."""
    metadata_path = video_path.parent / "render_metadata.json"
    if not metadata_path.is_file():
        raise RuntimeError(
            "تم منع الرفع: سجل مصادر الرندر غير موجود؛ لا يمكن إثبات استخدام صوت ووجه صاحب القناة."
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("تم منع الرفع: سجل مصادر الرندر غير صالح.") from None

    if metadata.get("voice_source") != "owner_recording":
        raise RuntimeError(
            "تم منع الرفع: التعليق الصوتي ليس تسجيلاً أصلياً لصاحب القناة؛ صوت TTS مسموح للمعاينة فقط."
        )
    if metadata.get("presenter_source") != "owner_video":
        raise RuntimeError(
            "تم منع الرفع: لا يوجد فيديو أصلي لصاحب القناة مدمج في النسخة."
        )
    if metadata.get("broll_source") not in {"pexels", "licensed_video"}:
        raise RuntimeError("تم منع الرفع: مصدر لقطات B-roll المرخصة غير مثبت.")
    try:
        broll_count = int(metadata.get("broll_scene_count", 0))
    except (TypeError, ValueError):
        broll_count = 0
    if broll_count <= 0:
        raise RuntimeError("تم منع الرفع: لا توجد لقطات B-roll مرخصة مثبتة.")
    return metadata


def upload_private_video(video_path: Path, title: str, plan: dict | None = None) -> str:
    plan = plan or {}
    require_owner_identity_metadata(video_path)
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
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
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
    target_channel_id = verify_target_channel(youtube)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": str(plan.get("description", "محتوى مالي تثقيفي من قناة WealthRadar."))[:5000],
                "categoryId": "27",
                "defaultLanguage": "ar",
                "tags": [str(tag)[:100] for tag in plan.get("tags", ["WealthRadar", "التمويل", "الاستثمار", "الثقافة المالية"])][:30],
            },
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True),
    )
    response = request.execute()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube لم يُرجع معرّف الفيديو؛ تعذر تأكيد الرفع.")
    # The insert response already includes the requested status because part="snippet,status".
    # Avoid a follow-up videos.list call: the configured youtube.upload OAuth scope cannot read status.
    returned_status = response.get("status", {}).get("privacyStatus")
    returned_channel_id = response.get("snippet", {}).get("channelId")
    if returned_status != "private":
        raise RuntimeError(
            "استجابة YouTube لم تؤكد أن الفيديو مرفوع بخصوصية Private؛ لن نعلن نجاح الرفع."
        )
    if returned_channel_id != target_channel_id:
        raise RuntimeError("استجابة YouTube لا تطابق القناة التي تم التحقق منها؛ لن نعلن نجاح الرفع.")
    url = f"https://youtu.be/{video_id}"
    print(f"[UPLOAD_PRIVATE_VERIFIED] {url} channel={target_channel_id}")
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
        upload_private_video(video_path, str(plan["title"]), plan)
        return
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    render(plan, args.output, api_key)


if __name__ == "__main__":
    main()

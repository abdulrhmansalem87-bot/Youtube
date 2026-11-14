from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

PEXELS_API = "https://api.pexels.com/videos/search"
MAX_SCENE_SECONDS = 2.5
MIN_SCENE_SECONDS = 1.5


def require_api_key(value: str | None) -> str:
    key = str(value or "").strip()
    if not key:
        raise RuntimeError(
            "PEXELS_API_KEY غير موجود في GitHub Secrets؛ أوقفنا NewsFlow بدلاً من الرجوع إلى البطاقات الثابتة."
        )
    return key


def split_scene_durations(durations: list[float], maximum: float = MAX_SCENE_SECONDS) -> list[tuple[int, float]]:
    if not durations or maximum <= 0:
        raise ValueError("يلزم توفير مدد مشاهد صالحة.")
    result: list[tuple[int, float]] = []
    for index, raw in enumerate(durations):
        total = float(raw)
        if not math.isfinite(total) or total <= 0:
            raise ValueError("مدة المشهد يجب أن تكون أكبر من صفر.")
        count = max(1, int((total + maximum - 0.001) // maximum))
        chunk = round(total / count, 3)
        chunks = [chunk] * count
        chunks[-1] = round(total - sum(chunks[:-1]), 3)
        result.extend((index, seconds) for seconds in chunks if seconds > 0.001)
    if any(seconds > maximum + 0.001 for _, seconds in result):
        raise RuntimeError("فشل تقسيم مشاهد B-roll إلى لقطات قصيرة.")
    return result


def _request_json(url: str, api_key: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": api_key, "Accept": "application/json",
                 "User-Agent": "WealthRadar-NewsFlow/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"تعذر جلب لقطات Pexels (HTTP {exc.code})؛ أوقفنا الرندر دون استخدام صور ثابتة."
        ) from None
    except Exception as exc:
        raise RuntimeError(
            f"تعذر الاتصال بمصدر B-roll المرخّص ({type(exc).__name__})؛ أوقفنا الرندر."
        ) from None


def _english_query(card: dict) -> str:
    text = f"{card.get('title', '')} {card.get('body', '')}".casefold()
    terms = (
        (("ذهب", "gold"), "gold bullion trading"),
        (("دولار", "عملة", "currency", "exchange"), "currency exchange finance"),
        (("تضخم", "أسعار", "inflation", "consumer"), "grocery shopping price inflation"),
        (("بنك", "قرض", "فائدة", "bank", "loan", "interest"), "banking loan finance"),
        (("بورصة", "أسهم", "stocks", "market"), "stock market trading"),
        (("نفط", "طاقة", "oil", "energy"), "oil energy industry"),
        (("شركة", "أرباح", "business", "company"), "corporate business office"),
    )
    for keys, query in terms:
        if any(key in text for key in keys):
            return query
    return "finance economy business office"


def _search_videos(query: str, api_key: str, portrait: bool) -> list[dict]:
    params = urllib.parse.urlencode({
        "query": query,
        "orientation": "portrait" if portrait else "landscape",
        "size": "large",
        "per_page": 15,
    })
    payload = _request_json(f"{PEXELS_API}?{params}", api_key)
    candidates = []
    for video in payload.get("videos", []):
        files = video.get("video_files", [])
        matching = []
        for item in files:
            width, height = int(item.get("width") or 0), int(item.get("height") or 0)
            link = item.get("link")
            if not link or min(width, height) < 720:
                continue
            if portrait and height <= width:
                continue
            if not portrait and width <= height:
                continue
            matching.append((width * height, link))
        if not matching:
            continue
        matching.sort(reverse=True)
        candidates.append({
            "id": video.get("id"),
            "url": matching[0][1],
            "photographer": video.get("user", {}).get("name", ""),
            "page": video.get("url", ""),
        })
    if not candidates:
        raise RuntimeError(
            f"لم يعثر Pexels على لقطات فيديو مناسبة لعبارة: {query}؛ أوقفنا الرندر."
        )
    return candidates[:4]


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "WealthRadar-NewsFlow/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)
    if not destination.is_file() or destination.stat().st_size < 20_000:
        raise RuntimeError("ملف B-roll الذي تم تنزيله غير صالح أو فارغ.")


def _font(bold: bool = False) -> str:
    candidates = (
        ["/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if Path(path).is_file():
            return path
    raise RuntimeError("لم يتم العثور على خط عربي مناسب للكتابة فوق لقطات B-roll.")


def _overlay(card: dict, path: Path, width: int, height: int) -> None:
    if not features.check("raqm"):
        raise RuntimeError("محرك تشكيل العربية RAQM غير متاح؛ أوقفنا إخراج النص.")
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(width * 0.055)
    panel_top = int(height * (0.60 if width > height else 0.68))
    panel_bottom = int(height * 0.94)
    draw.rounded_rectangle(
        (margin, panel_top, width - margin, panel_bottom),
        radius=max(24, width // 45), fill=(5, 17, 31, 218),
        outline=(52, 205, 190, 235), width=max(2, width // 600),
    )
    brand_font = ImageFont.truetype(_font(True), max(26, int(width * 0.027)))
    title_font = ImageFont.truetype(_font(True), max(34, int(width * (0.036 if width > height else 0.048))))
    body_font = ImageFont.truetype(_font(False), max(23, int(width * (0.019 if width > height else 0.029))))
    draw.text((width // 2, int(height * 0.075)), "WealthRadar", font=brand_font,
              fill=(255, 255, 255, 245), anchor="mm")
    title = str(card.get("title") or "").strip()[:125]
    body = str(card.get("body") or "").strip()[:180]
    def lines_for(text: str, font: ImageFont.FreeTypeFont, limit: int) -> list[str]:
        rows, current = [], ""
        for word in text.split():
            trial = f"{current} {word}".strip()
            box = draw.textbbox((0, 0), trial, font=font, direction="rtl", language="ar")
            if box[2] - box[0] <= limit:
                current = trial
            else:
                if current:
                    rows.append(current)
                current = word
        if current:
            rows.append(current)
        return rows
    max_width = width - margin * 3
    title_lines = lines_for(title, title_font, max_width)[:2]
    body_lines = lines_for(body, body_font, max_width)[:2]
    y = panel_top + int((panel_bottom - panel_top) * 0.16)
    for line in title_lines:
        draw.text((width // 2, y), line, font=title_font, fill=(255, 255, 255, 255),
                  anchor="mm", direction="rtl", language="ar")
        y += int(title_font.size * 1.3)
    y += int(body_font.size * 0.45)
    for line in body_lines:
        draw.text((width // 2, y), line, font=body_font, fill=(196, 222, 232, 255),
                  anchor="mm", direction="rtl", language="ar")
        y += int(body_font.size * 1.35)
    image.save(path)


def render_broll_video(cards: list[dict], durations: list[float], audio: Path,
                       output: Path, portrait: bool = False) -> Path:
    """Render real Pexels footage with Arabic overlays; never falls back to static cards."""
    api_key = require_api_key(os.getenv("PEXELS_API_KEY"))
    if not cards or len(cards) != len(durations):
        raise ValueError("يجب توفير مشهد ومدة مستقلة لكل جزء من التعليق الصوتي.")
    if not audio.is_file():
        raise FileNotFoundError(f"ملف الصوت غير موجود: {audio}")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg وFFprobe مطلوبان لإنتاج B-roll.")
    width, height = (1080, 1920) if portrait else (1920, 1080)
    scene_plan = split_scene_durations(durations)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"provider": "Pexels", "license": "Pexels License",
                "orientation": "portrait" if portrait else "landscape",
                "scene_seconds_max": MAX_SCENE_SECONDS, "sources": []}
    with tempfile.TemporaryDirectory(prefix="wealthradar-broll-") as temp_dir:
        work = Path(temp_dir)
        footage_by_card: dict[int, list[Path]] = {}
        for card_index in sorted({index for index, _ in scene_plan}):
            card = cards[card_index]
            query = _english_query(card)
            candidates = _search_videos(query, api_key, portrait)
            paths = []
            for candidate_index, candidate in enumerate(candidates[:3]):
                source = work / f"source-{card_index}-{candidate_index}.mp4"
                _download(candidate["url"], source)
                paths.append(source)
                manifest["sources"].append({
                    "query": query, "video_id": candidate.get("id"),
                    "photographer": candidate.get("photographer"),
                    "source_page": candidate.get("page"),
                })
            footage_by_card[card_index] = paths

        segments: list[Path] = []
        usage: dict[int, int] = {}
        for index, (card_index, seconds) in enumerate(scene_plan):
            sources = footage_by_card[card_index]
            cursor = usage.get(card_index, 0)
            source = sources[cursor % len(sources)]
            usage[card_index] = cursor + 1
            overlay = work / f"overlay-{index:04d}.png"
            segment = work / f"segment-{index:04d}.mp4"
            _overlay(cards[card_index], overlay, width, height)
            offset = ((cursor // len(sources)) * MAX_SCENE_SECONDS) % 12
            filter_graph = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1[bg];[bg][1:v]overlay=0:0:format=auto,"
                "format=yuv420p"
            )
            command = [
                ffmpeg, "-y", "-stream_loop", "-1", "-ss", f"{offset:.2f}",
                "-i", str(source), "-loop", "1", "-i", str(overlay),
                "-t", f"{seconds:.3f}", "-filter_complex", filter_graph,
                "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(segment),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=240)
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "")[-900:]
                raise RuntimeError(f"فشل تركيب لقطة B-roll رقم {index + 1}: {detail}") from None
            segments.append(segment)

        concat = work / "concat.txt"
        concat.write_text(
            "".join(f"file '{item.as_posix()}'\n" for item in segments), encoding="utf-8"
        )
        silent = work / "visual.mp4"
        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
             "-c", "copy", str(silent)],
            check=True, capture_output=True, text=True, timeout=900,
        )
        temporary = output.with_name(output.stem + ".partial.mp4")
        temporary.unlink(missing_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-i", str(silent), "-i", str(audio),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags",
             "+faststart", str(temporary)],
            check=True, capture_output=True, text=True, timeout=1200,
        )
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height",
             "-of", "json", str(temporary)],
            check=True, capture_output=True, text=True,
        )
        metadata = json.loads(probe.stdout)
        streams = metadata.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
        actual = float(metadata.get("format", {}).get("duration", 0))
        if (not video or not has_audio
                or (int(video.get("width", 0)), int(video.get("height", 0))) != (width, height)
                or abs(actual - sum(durations)) > 2.5):
            temporary.unlink(missing_ok=True)
            raise RuntimeError("فشل فحص فيديو B-roll النهائي: الأبعاد أو الصوت أو المدة غير مطابقة.")
        os.replace(temporary, output)
    manifest["scene_count"] = len(scene_plan)
    manifest["output"] = output.name
    manifest_path = output.with_suffix(".broll-manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BROLL_RENDER_OK] provider=Pexels scenes={len(scene_plan)} "
          f"scene_max={MAX_SCENE_SECONDS}s orientation={manifest['orientation']}")
    return output

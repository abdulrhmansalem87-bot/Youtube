from __future__ import annotations

import json
import math
import os
import re
import unicodedata
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
MAX_BROLL_CLIPS_PER_CARD = 4


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
        # Use ceil rather than floor-division plus rounded equal chunks. The old
        # approach accumulated rounding error across many shots and could make
        # the final remainder exceed MAX_SCENE_SECONDS for otherwise valid audio.
        count = max(1, math.ceil(total / maximum - 1e-12))
        chunks = [
            round(total * (part + 1) / count - total * part / count, 6)
            for part in range(count)
        ]
        # Preserve the exact source-card duration after rounding intermediate shots.
        chunks[-1] = round(total - sum(chunks[:-1]), 6)
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
        (("إنفيديا", "رقائق", "أشباه الموصلات", "الذكاء الاصطناعي", "معالجات", "nvidia", "semiconductor", "chip", "artificial intelligence"), "semiconductor chip manufacturing data center"),
        (("ماير", "سفن", "السفن", "أحواض", "بناء السفن", "shipyard", "shipbuilding", "cruise ship"), "shipbuilding shipyard industrial"),
        (("باينانس", "عملات مشفرة", "اختراق", "بيتكوين", "بلوك تشين", "binance", "crypto", "bitcoin", "blockchain", "cybersecurity"), "cryptocurrency cybersecurity bitcoin"),
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
    return candidates[:15]


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "WealthRadar-NewsFlow/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)
    if not destination.is_file() or destination.stat().st_size < 20_000:
        raise RuntimeError("ملف B-roll الذي تم تنزيله غير صالح أو فارغ.")


def _font(bold: bool = False) -> str:
    candidates = (
        ["/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
         "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
         "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if Path(path).is_file():
            return path
    raise RuntimeError("لم يتم العثور على خط عربي مناسب للكتابة فوق لقطات B-roll.")

def _font_for_text(value: str, bold: bool = False) -> str:
    """Choose a font with Latin glyph coverage for mixed Arabic/Latin captions."""
    if re.search(r"[A-Za-z]", str(value or "")):
        latin_path = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        if Path(latin_path).is_file():
            return latin_path
    return _font(bold)



def clean_visual_text(value: str) -> str:
    """Normalize Arabic overlay text and remove invisible bidi/control marks that render as tofu."""
    normalized = unicodedata.normalize("NFC", str(value or ""))
    visible = "".join(
        char for char in normalized
        if unicodedata.category(char) not in {"Cf", "Cc", "Cs"}
    )
    return re.sub(r"\s+", " ", visible).strip()


def _overlay(card: dict, path: Path, width: int, height: int, caption_index: int = 0) -> None:
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
    brand_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not Path(brand_path).is_file():
        brand_path = _font(True)
    brand_font = ImageFont.truetype(brand_path, max(26, int(width * 0.027)))
    brand_x, brand_y = width // 2, int(height * 0.075)
    brand_box = draw.textbbox((brand_x, brand_y), "WealthRadar", font=brand_font, anchor="mm")
    brand_pad_x, brand_pad_y = max(14, width // 100), max(8, height // 180)
    draw.rounded_rectangle(
        (brand_box[0] - brand_pad_x, brand_box[1] - brand_pad_y,
         brand_box[2] + brand_pad_x, brand_box[3] + brand_pad_y),
        radius=max(10, width // 100), fill=(5, 17, 31, 205),
        outline=(52, 205, 190, 220), width=max(1, width // 900),
    )
    draw.text((brand_x, brand_y), "WealthRadar", font=brand_font,
              fill=(255, 255, 255, 255), anchor="mm")
    captions = card.get("captions")
    if isinstance(captions, list) and captions:
        title = clean_visual_text(captions[min(caption_index, len(captions) - 1)])[:90]
        body = ""
    else:
        title = clean_visual_text(card.get("title"))[:125]
        body = clean_visual_text(card.get("body"))[:180]
    title_font = ImageFont.truetype(
        _font_for_text(title, True),
        max(34, int(width * (0.036 if width > height else 0.048))),
    )
    body_font = ImageFont.truetype(
        _font_for_text(body, False),
        max(23, int(width * (0.019 if width > height else 0.029))),
    )
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


def _select_distinct_candidates(candidates: list[dict], count: int,
                               used_ids: set[str] | None = None) -> tuple[list[dict], set[str]]:
    """Choose a fresh Pexels source for each cut; never silently reuse a scene."""
    seen = set(used_ids or ())
    selected = []
    for candidate in candidates:
        key = str(candidate.get("id") or candidate.get("page") or candidate.get("url") or "").strip()
        if not key or key in seen:
            continue
        selected.append(candidate)
        seen.add(key)
        if len(selected) >= count:
            break
    if len(selected) != count:
        raise RuntimeError(
            f"لم يوفر Pexels {count} لقطات مختلفة للمشهد؛ أوقفنا الرندر بدلاً من تكرار نفس اللقطة."
        )
    return selected, seen


def render_broll_video(cards: list[dict], durations: list[float], audio: Path,
                       output: Path, portrait: bool = False) -> Path:
    """Render licensed Pexels footage with a new moving scene and Arabic caption every 2.5s."""
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
    manifest = {
        "provider": "Pexels",
        "license": "Pexels License",
        "orientation": "portrait" if portrait else "landscape",
        "scene_seconds_max": MAX_SCENE_SECONDS,
        "sources": [],
    }
    used_video_ids: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="wealthradar-broll-") as temp_dir:
        work = Path(temp_dir)
        segments: list[Path] = []
        for card_index in sorted({index for index, _ in scene_plan}):
            card = cards[card_index]
            query = _english_query(card)
            candidates = _search_videos(query, api_key, portrait)
            card_shots = [
                (shot_index, seconds)
                for shot_index, (idx, seconds) in enumerate(scene_plan)
                if idx == card_index
            ]
            clip_count = min(MAX_BROLL_CLIPS_PER_CARD, len(card_shots))
            selected, used_video_ids = _select_distinct_candidates(
                candidates, clip_count, used_video_ids
            )

            source_paths: list[Path] = []
            for clip_index, candidate in enumerate(selected):
                source = work / f"source-{card_index}-{clip_index}.mp4"
                _download(candidate["url"], source)
                source_paths.append(source)
                manifest["sources"].append({
                    "card_index": card_index,
                    "scene_index": clip_index + 1,
                    "query": query,
                    "video_id": candidate.get("id"),
                    "photographer": candidate.get("photographer"),
                    "source_page": candidate.get("page"),
                })

            # Build a short loop from distinct Pexels clips. Each clip occupies
            # one 2.5s scene; the loop repeats only after four different shots.
            loop_durations = [seconds for _, seconds in card_shots[:clip_count]]
            loop_duration = sum(loop_durations)
            loop = work / f"broll-loop-{card_index:04d}.mp4"
            filter_parts = []
            for clip_index, seconds in enumerate(loop_durations):
                filter_parts.append(
                    f"[{clip_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},setsar=1,fps=30,trim=duration={seconds:.6f},"
                    f"setpts=PTS-STARTPTS,format=yuv420p[v{clip_index}]"
                )
            concat_inputs = "".join(f"[v{clip_index}]" for clip_index in range(clip_count))
            filter_parts.append(
                f"{concat_inputs}concat=n={clip_count}:v=1:a=0[outv]"
            )
            loop_command = [ffmpeg, "-y"]
            for source in source_paths:
                loop_command.extend(["-stream_loop", "-1", "-i", str(source)])
            loop_command.extend([
                "-filter_complex", ";".join(filter_parts),
                "-map", "[outv]",
                "-t", f"{loop_duration:.3f}",
                "-an", "-r", "30", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(loop),
            ])
            try:
                subprocess.run(
                    loop_command, check=True, capture_output=True, text=True, timeout=900
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "")[-1400:]
                raise RuntimeError(
                    f"فشل تجهيز مشاهد B-roll المختلفة للقصة رقم {card_index + 1}: {detail}"
                ) from None
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"انتهت مهلة تجهيز مشاهد B-roll للقصة رقم {card_index + 1}."
                ) from None
            if not loop.is_file() or loop.stat().st_size < 20_000:
                raise RuntimeError("ملف تسلسل B-roll غير صالح؛ أوقفنا الرندر.")

            # Build one timed Arabic overlay stream. Both the caption and the
            # underlying Pexels source change on every shot boundary.
            overlay_list = work / f"overlays-{card_index:04d}.ffconcat"
            overlay_lines = ["ffconcat version 1.0"]
            for local_index, (shot_index, seconds) in enumerate(card_shots):
                overlay = work / f"overlay-{card_index}-{local_index:04d}.png"
                _overlay(card, overlay, width, height, caption_index=local_index)
                escaped = str(overlay).replace("\\", "\\\\").replace("'", "\\'")
                overlay_lines.extend([f"file '{escaped}'", f"duration {seconds:.6f}"])
            overlay_lines.append(overlay_lines[-2])
            overlay_list.write_text("\\n".join(overlay_lines) + "\\n", encoding="utf-8")

            card_shots_duration = sum(seconds for _, seconds in card_shots)
            segment = work / f"card-{card_index:04d}.mp4"
            command = [
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(loop),
                "-f", "concat", "-safe", "0", "-i", str(overlay_list),
                "-filter_complex",
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1[base];"
                "[1:v]fps=30,format=rgba[caption];"
                "[base][caption]overlay=0:0:format=auto:shortest=1[v]",
                "-map", "[v]", "-t", f"{card_shots_duration:.3f}",
                "-an", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(segment),
            ]
            try:
                subprocess.run(
                    command, check=True, capture_output=True, text=True, timeout=900
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "")[-1400:]
                raise RuntimeError(
                    f"فشل تركيب B-roll للقصة رقم {card_index + 1}: {detail}"
                ) from None
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"انتهت مهلة تركيب B-roll للقصة رقم {card_index + 1}."
                ) from None
            segments.append(segment)

        concat = work / "concat.txt"
        concat.write_text(
            "".join(f"file '{item.as_posix()}'\\n" for item in segments), encoding="utf-8"
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
    manifest["unique_source_count"] = len(used_video_ids)
    manifest["output"] = output.name
    manifest_path = output.with_suffix(".broll-manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[BROLL_RENDER_OK] provider=Pexels scenes={len(scene_plan)} "
        f"unique_sources={len(used_video_ids)} scene_max={MAX_SCENE_SECONDS}s "
        f"orientation={manifest['orientation']}"
    )
    return output

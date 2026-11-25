from __future__ import annotations

import json
import math
import hashlib
import time
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

PEXELS_API = "https://api.pexels.com/v1/videos/search"
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
    """Retry transient Pexels/network failures without retrying permanent client errors."""
    request = urllib.request.Request(
        url,
        headers={"Authorization": api_key, "Accept": "application/json",
                 "User-Agent": "WealthRadar-NewsFlow/1.0"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(
                    f"تعذر جلب لقطات Pexels (HTTP {exc.code})؛ أوقفنا الرندر دون استخدام صور ثابتة."
                ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError(
                    "تعذر الاتصال بمصدر B-roll المرخّص بعد ثلاث محاولات؛ أوقفنا الرندر."
                ) from None
        time.sleep(1.5 * (attempt + 1))


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
        "size": "medium",
        "per_page": 15,
    })
    payload = _request_json(f"{PEXELS_API}?{params}", api_key)
    candidates = []
    for video in payload.get("videos", []):
        video_duration = float(video.get("duration") or 0)
        if video_duration < MAX_SCENE_SECONDS:
            continue
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
            "duration": video_duration,
            "photographer": video.get("user", {}).get("name", ""),
            "page": video.get("url", ""),
        })
    if not candidates:
        raise RuntimeError(
            f"لم يعثر Pexels على لقطات فيديو مناسبة لعبارة: {query}؛ أوقفنا الرندر."
        )
    return candidates[:15]


def _download(url: str, destination: Path) -> None:
    """Download atomically, retry transient failures, and reuse a 30-day local asset cache."""
    cache_root = Path(os.getenv("NEWSFLOW_BROLL_CACHE_DIR", "output/broll-cache"))
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".mp4")

    def valid(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size < 20_000:
            return False
        return (time.time() - path.stat().st_mtime) < 30 * 24 * 60 * 60

    if valid(cache_path):
        shutil.copy2(cache_path, destination)
        print("[BROLL_CACHE_HIT] reused licensed clip")
        return

    request = urllib.request.Request(url, headers={"User-Agent": "WealthRadar-NewsFlow/1.0"})
    last_error = None
    for attempt in range(3):
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target)
            if not valid(temporary):
                raise RuntimeError("ملف B-roll الذي تم تنزيله غير صالح أو فارغ.")
            temporary.replace(destination)
            shutil.copy2(destination, cache_path)
            print("[BROLL_DOWNLOAD_OK] licensed clip downloaded and cached")
            return
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                break
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(
        f"تعذر تنزيل لقطة B-roll بعد ثلاث محاولات ({type(last_error).__name__ if last_error else 'unknown'})."
    ) from None


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


def _draw_receipt(draw, receipt: dict, width: int, height: int, top_limit: int, lines_for) -> None:
    """Before/after card for a settled prediction: prediction, actual, difference, marker, hit-rate counter."""
    portrait = height > width
    hit = receipt.get("verdict") == "hit"
    accent = (52, 205, 190, 255) if hit else (245, 166, 35, 255)
    margin = int(width * (0.07 if portrait else 0.22))
    top = max(top_limit + int(height * 0.03), int(height * (0.17 if portrait else 0.16)))
    bottom = int(height * (0.78 if portrait else 0.88))
    draw.rounded_rectangle((margin, top, width - margin, bottom), radius=24, fill=(5, 17, 31, 225))
    draw.rectangle((margin, top, width - margin, top + 12), fill=accent)
    unit = height if portrait else height * 1.5
    cx = width // 2
    rows = [
        (receipt.get("title_ar", ""), 0.030, False, (255, 255, 255, 255)),
        (receipt.get("speaker_ar", ""), 0.020, False, (190, 205, 220, 255)),
        (receipt.get("before_ar", ""), 0.034, True, (255, 255, 255, 255)),
        (receipt.get("after_ar", ""), 0.034, True, (255, 255, 255, 255)),
        (receipt.get("diff_ar", ""), 0.030, False, accent),
        (receipt.get("marker_ar", ""), 0.044, True, accent),
        (receipt.get("counter_ar", ""), 0.026, False, (255, 255, 255, 255)),
    ]
    rows = [row for row in rows if row[0]]
    weights = [size for _, size, _, _ in rows]
    span = bottom - top - 40
    y = top + 30
    for (text, size, bold, color), weight in zip(rows, weights):
        font_path = _font_for_text(text, bold)
        dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")
        if re.search(r"[%+\-]", text) and Path(dejavu).is_file():
            font_path = dejavu  # the Arabic font has no glyph for these signs
        font = ImageFont.truetype(font_path, max(26, int(unit * size)))
        slot = span * weight / sum(weights)
        wrapped = lines_for(text, font, width - margin * 2 - 60)[:2]
        line_step = int(font.size * 1.3)
        yy = y + slot / 2 - (len(wrapped) - 1) * line_step / 2
        for row in wrapped:
            draw.text((cx, yy), row, font=font, fill=color, anchor="mm", direction="rtl", language="ar")
            yy += line_step
        y += slot


def _overlay(card: dict, path: Path, width: int, height: int, caption_index: int = 0) -> None:
    """Broadcast-style overlay: small brand mark, Arabic headline only at the start of a story,
    big key number in the first seconds, and outlined captions with no boxed panel in mid-screen."""
    if not features.check("raqm"):
        raise RuntimeError("محرك تشكيل العربية RAQM غير متاح؛ أوقفنا إخراج النص.")
    portrait = height > width
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(width * 0.06)
    max_width = width - margin * 2
    teal = (52, 205, 190, 255)

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

    # 1) Small brand mark, top centre (inside the platform-safe area).
    brand_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not Path(brand_path).is_file():
        brand_path = _font(True)
    brand_font = ImageFont.truetype(brand_path, max(24, int(width * (0.034 if portrait else 0.015))))
    brand_x, brand_y = width // 2, int(height * (0.05 if portrait else 0.06))
    brand_box = draw.textbbox((brand_x, brand_y), "WealthRadar", font=brand_font, anchor="mm")
    pad_x, pad_y = max(14, width // 90), max(8, height // 200)
    draw.rounded_rectangle(
        (brand_box[0] - pad_x, brand_box[1] - pad_y, brand_box[2] + pad_x, brand_box[3] + pad_y),
        radius=max(10, width // 100), fill=(5, 17, 31, 190), outline=(52, 205, 190, 220),
        width=max(1, width // 900),
    )
    draw.text((brand_x, brand_y), "WealthRadar", font=brand_font, fill=(255, 255, 255, 255), anchor="mm")
    brand_bottom = brand_box[3] + pad_y

    receipt = card.get("receipt")
    if isinstance(receipt, dict):
        _draw_receipt(draw, receipt, width, height, brand_bottom, lines_for)
        image.save(path)
        return

    # 2) Arabic headline bar: only on the first shot of a story, and only if it is real Arabic.
    headline = clean_visual_text(card.get("headline"))
    arabic = len(re.findall(r"[\u0600-\u06FF]", headline))
    latin = len(re.findall(r"[A-Za-z]", headline))
    if headline and caption_index == 0 and arabic >= 3 and arabic > latin * 3:
        h_font = ImageFont.truetype(_font(True), max(30, int(width * (0.046 if portrait else 0.024))))
        h_lines = lines_for(headline[:90], h_font, max_width - 40)[:2]
        step = int(h_font.size * 1.35)
        top = brand_bottom + int(height * 0.02)
        bottom = top + step * len(h_lines) + int(h_font.size * 0.5)
        draw.rounded_rectangle((margin, top, width - margin, bottom), radius=12, fill=(5, 17, 31, 215))
        draw.rectangle((width - margin - 10, top, width - margin, bottom), fill=teal)
        y = top + int(h_font.size * 0.25) + step // 2
        for line in h_lines:
            draw.text(((margin + width - margin - 10) // 2, y), line, font=h_font, fill=(255, 255, 255, 255),
                      anchor="mm", direction="rtl", language="ar")
            y += step

    # 3) Key number badge in the first ~5 seconds (the hook the viewer should see immediately).
    key_number = clean_visual_text(card.get("key_number"))[:18]
    if key_number and caption_index <= 1:
        k_path = _font_for_text(key_number, True)
        if not re.search(r"[\u0600-\u06FF]", key_number) and Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf").is_file():
            k_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # has %, $, digits
        k_font = ImageFont.truetype(k_path, int(width * (0.17 if portrait else 0.085)))
        cx, cy = width // 2, int(height * (0.30 if portrait else 0.36))
        draw.text((cx, cy), key_number, font=k_font, fill=(255, 255, 255, 255), anchor="mm",
                  stroke_width=max(6, k_font.size // 14), stroke_fill=(5, 17, 31, 255),
                  direction="rtl", language="ar")
        box = draw.textbbox((cx, cy), key_number, font=k_font, anchor="mm")
        draw.rectangle((box[0], box[3] + 10, box[2], box[3] + 18), fill=teal)

    # 4) Outlined captions, lower-middle in portrait, lower third in landscape. No boxed panel.
    captions = card.get("captions")
    if isinstance(captions, list) and captions:
        text = clean_visual_text(captions[min(caption_index, len(captions) - 1)])[:90]
    else:
        text = clean_visual_text(card.get("title"))[:90]
    if text:
        c_font = ImageFont.truetype(_font_for_text(text, True), max(36, int(width * (0.066 if portrait else 0.036))))
        rows = lines_for(text, c_font, max_width)[:2]
        step = int(c_font.size * 1.4)
        center_y = int(height * (0.66 if portrait else 0.85))
        y = center_y - (len(rows) - 1) * step // 2
        for row in rows:
            draw.text((width // 2, y), row, font=c_font, fill=(255, 255, 255, 255), anchor="mm",
                      stroke_width=max(4, c_font.size // 9), stroke_fill=(0, 0, 0, 255),
                      direction="rtl", language="ar")
            y += step
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
    if len(selected) < count and candidates and os.getenv("NEWSFLOW_PRIVATE_STAGING", "false").lower() == "true":
        # Private owner-review render only: when Pexels has too few unused clips,
        # reuse results already found rather than stopping the preview.
        pool = list(selected) + [c for c in candidates if c not in selected]
        index = 0
        while len(selected) < count:
            selected.append(pool[index % len(pool)])
            index += 1
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
            for source, seconds in zip(source_paths, loop_durations):
                loop_command.extend(["-t", f"{seconds:.3f}", "-i", str(source)])
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
            overlay_list.write_text("\n".join(overlay_lines) + "\n", encoding="utf-8")

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


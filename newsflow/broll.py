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

from newsflow.rendering import _SYSTEM_BOLD, _SYSTEM_REGULAR, _first_existing, _thread_args

PEXELS_API = "https://api.pexels.com/v1/videos/search"
# Pacing rule (owner requirement): a new shot or visible motion roughly every 2 seconds,
# never a static shot longer than 2.5 s. Every shot also gets a gentle zoom or pan.
TARGET_SCENE_SECONDS = 2.2
MAX_SCENE_SECONDS = 2.5
MIN_SCENE_SECONDS = 1.5
MAX_BROLL_CLIPS_PER_CARD = 8
MOTION_OVERSCAN = 1.14
MOTION_STYLES = ("zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_in", "pan_up", "zoom_out", "pan_down")


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
        # Aim for ~2.2 s shots (a cut about every 2 seconds) without going below the minimum.
        wanted = min(round(total / TARGET_SCENE_SECONDS), int(total // MIN_SCENE_SECONDS))
        count = max(count, wanted)
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
    names = (("NotoNaskhArabic-Bold.ttf", "NotoSansArabic-Bold.ttf") if bold
             else ("NotoNaskhArabic-Regular.ttf", "NotoSansArabic-Regular.ttf"))
    found = _first_existing(names, _SYSTEM_BOLD if bold else _SYSTEM_REGULAR)
    if found:
        return found
    raise RuntimeError("لم يتم العثور على خط عربي مناسب للكتابة فوق لقطات B-roll.")


def _font_for_text(value: str, bold: bool = False) -> str:
    """Choose a font with Latin glyph coverage for mixed Arabic/Latin captions."""
    if re.search(r"[A-Za-z]", str(value or "")):
        latin_path = _first_existing(("DejaVuSans-Bold.ttf",) if bold else ("DejaVuSans.ttf",),
                                     _SYSTEM_BOLD if bold else _SYSTEM_REGULAR)
        if latin_path:
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


INK = (4, 12, 22)               # the one dark colour: bands, bug and chip are all this ink at different opacity
GOLD = (212, 175, 98, 255)   # brand accent: muted metallic gold
HIT_GREEN = (120, 200, 150, 255)   # semantic only: verdict hit
MISS_CLAY = (222, 128, 108, 255)   # semantic only: verdict miss (not gold, not alarm red)
WHITE = (255, 255, 255, 255)
SOFT = (224, 231, 240, 235)
FAINT = (190, 201, 214, 220)
BAND_MAX_ALPHA = 222


def _brand_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """One typeface for every overlay element (DejaVu Sans covers Arabic, Latin digits, % and +)."""
    path = _first_existing(("DejaVuSans-Bold.ttf",) if bold else ("DejaVuSans.ttf",),
                           _SYSTEM_BOLD if bold else _SYSTEM_REGULAR) or _font(bold)
    return ImageFont.truetype(path, size)


HEAVY_ARABIC_NAMES = ("NotoSansArabic-Black.ttf", "NotoSansArabic-ExtraBold.ttf", "NotoSansArabic-Bold.ttf")
HEAVY_ARABIC = tuple(
    path for path in (_first_existing((name,), ()) for name in HEAVY_ARABIC_NAMES) if path
)


def _heavy_font(size: int, text: str = "") -> ImageFont.FreeTypeFont:
    """Headline-strap face: Noto Sans Arabic Black (broadcast-weight), but only if it has every glyph in `text`;
    otherwise fall back to the single brand face so a % or + never renders as a box."""
    for path in HEAVY_ARABIC:
        if Path(path).is_file():
            font = ImageFont.truetype(path, size)
            if all(ch.isspace() or font.getmask(ch).getbbox() is not None for ch in text):
                return font
            break
    return _brand_font(size, True)


def _wrap(draw, text: str, font, limit: int) -> list[str]:
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


def _text_direction(value: str) -> str:
    """Numbers like "+11.66%" must stay left-to-right; anything with Arabic letters shapes right-to-left."""
    return "rtl" if re.search(r"[\u0600-\u06FF]", value) else "ltr"


def _layout(width: int, height: int) -> dict:
    """Fixed broadcast grid shared by every frame."""
    portrait = height > width
    return {
        "portrait": portrait,
        "margin": int(width * (0.065 if portrait else 0.05)),
        "top": int(height * (0.05 if portrait else 0.055)),
        # Text sits above the Shorts player controls (bottom ~20%); the gradient band runs to the screen edge.
        "text_bottom": int(height * (0.79 if portrait else 0.90)),
        "head": int(width * (0.041 if portrait else 0.021)),
        "body": int(width * (0.034 if portrait else 0.0175)),
        "small": int(width * (0.024 if portrait else 0.0125)),
        "fade": int(height * (0.085 if portrait else 0.16)),
        "gap": int(height * (0.014 if portrait else 0.02)),
    }


def _band(image: Image.Image, text_top: int, grid: dict) -> None:
    """Dark gradient band flush to the screen edges: transparent at the top, darkest at the bottom."""
    width, height = image.size
    band_top = max(0, text_top - grid["gap"] - grid["fade"])
    band_h = height - band_top
    ramp = Image.linear_gradient("L").resize((width, grid["fade"]))
    lut = []
    for value in range(256):
        x = value / 255
        lut.append(int(BAND_MAX_ALPHA * x * x * (3 - 2 * x)))  # smoothstep: no visible edge where the fade starts
    ramp = ramp.point(lut)
    mask = Image.new("L", (width, band_h), BAND_MAX_ALPHA)
    mask.paste(ramp, (0, 0))
    layer = Image.new("RGBA", (width, band_h), INK + (0,))
    layer.putalpha(mask)
    image.alpha_composite(layer, (0, band_top))


def _corner_tag(image: Image.Image, draw, text: str, font, side: str, grid: dict, solid: bool = False) -> None:
    """Flush corner tag. solid=True is the channel bug: a solid gold plate with ink text (the broadcast logo box);
    otherwise a quiet translucent chip with white text and a 2 px gold underline."""
    box = draw.textbbox((0, 0), text, font=font, direction=_text_direction(text), language="ar")
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = int(grid["small"] * 0.9), int(grid["small"] * 0.5)
    tag_w, tag_h = text_w + pad_x * 2, text_h + pad_y * 2
    left = 0 if side == "left" else image.size[0] - tag_w
    top = grid["top"]
    if solid:
        image.alpha_composite(Image.new("RGBA", (tag_w, tag_h), GOLD), (left, top))
        ink = INK + (255,)
    else:
        image.alpha_composite(Image.new("RGBA", (tag_w, tag_h), INK + (140,)), (left, top))
        draw.rectangle((left, top + tag_h - 2, left + tag_w, top + tag_h), fill=GOLD[:3] + (170,))
        ink = WHITE
    draw.text((left + pad_x - box[0], top + pad_y - box[1]), text, font=font, fill=ink,
              direction=_text_direction(text), language="ar")


def _draw_receipt(image: Image.Image, draw, receipt: dict, grid: dict) -> None:
    """Predictions receipt in the same band system: title, hairline, before/after rows, verdict, hit-rate."""
    width = image.size[0]
    hit = receipt.get("verdict") == "hit"
    accent = HIT_GREEN if hit else MISS_CLAY
    margin = grid["margin"]
    right, left = width - margin, margin
    title = receipt.get("title_ar", "")
    title_size = int(grid["head"] * 0.95)
    title_font = _brand_font(title_size, True)
    while title_size > 18:
        box = draw.textbbox((0, 0), title, font=title_font, direction="rtl", language="ar")
        if box[2] - box[0] <= right - left:
            break
        title_size -= 2
        title_font = _brand_font(title_size, True)
    row_font = _brand_font(grid["body"])
    value_font = _brand_font(grid["body"], True)
    small_font = _brand_font(grid["small"])
    rows = receipt.get("rows") or []
    line = int(grid["body"] * 1.9)
    small_line = int(grid["small"] * 1.8)
    title_h = int(title_size * 2.0)
    block_h = title_h + line * len(rows) + int(line * 1.15) + small_line * 2
    top = grid["text_bottom"] - block_h
    _band(image, top, grid)
    y = top
    draw.text((right, y), title, font=title_font, fill=WHITE, anchor="ra", direction="rtl", language="ar")
    rule = y + int(title_size * 1.65)
    draw.line((left, rule, right, rule), fill=(255, 255, 255, 70), width=1)
    y += title_h
    for label, value in rows:
        draw.text((right, y), label, font=row_font, fill=FAINT, anchor="ra", direction="rtl", language="ar")
        draw.text((left, y), value, font=value_font, fill=WHITE, anchor="la",
                  direction=_text_direction(value), language="ar")
        y += line
    tag = receipt.get("marker_ar", "")
    mark = int(grid["body"] * 0.42)
    draw.rectangle((right - mark, y + int(line * 0.28), right, y + int(line * 0.28) + mark), fill=accent)
    draw.text((right - mark - int(mark * 0.8), y), tag, font=value_font, fill=accent, anchor="ra",
              direction="rtl", language="ar")
    y += int(line * 1.15)
    draw.text((right, y), receipt.get("counter_ar", ""), font=small_font, fill=SOFT, anchor="ra",
              direction="rtl", language="ar")
    y += small_line
    draw.text((right, y), receipt.get("speaker_ar", ""), font=small_font, fill=FAINT, anchor="ra",
              direction="rtl", language="ar")


def _overlay(card: dict, path: Path, width: int, height: int, caption_index: int = 0) -> None:
    """Broadcast-style overlay on a fixed grid: a flush gradient band holds the Arabic headline (first shot of
    a story) and the caption; a quiet brand tag sits top-left and a stat chip top-right (first shots only)."""
    if not features.check("raqm"):
        raise RuntimeError("محرك تشكيل العربية RAQM غير متاح؛ أوقفنا إخراج النص.")
    grid = _layout(width, height)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _corner_tag(image, draw, "WealthRadar", _brand_font(grid["small"], True), "left", grid, solid=True)

    receipt = card.get("receipt")
    if isinstance(receipt, dict):
        _draw_receipt(image, draw, receipt, grid)
        image.save(path)
        return

    key_number = clean_visual_text(card.get("key_number"))[:14]
    if key_number and caption_index <= 1:
        _corner_tag(image, draw, key_number, _brand_font(int(grid["small"] * 1.25), True), "right", grid)

    headline = clean_visual_text(card.get("headline"))
    arabic = len(re.findall(r"[\u0600-\u06FF]", headline))
    latin = len(re.findall(r"[A-Za-z]", headline))
    show_headline = bool(headline) and arabic >= 3 and arabic > latin * 3  # strap stays for the whole story
    captions = card.get("captions")
    if isinstance(captions, list) and captions:
        text = clean_visual_text(captions[min(caption_index, len(captions) - 1)])[:100]
    else:
        text = clean_visual_text(card.get("title"))[:100]

    margin = grid["margin"]
    right, limit = width - margin, width - margin * 2
    head_font = _heavy_font(int(grid["head"] * (0.98 if grid["portrait"] else 1.12)), headline[:90])
    body_font = _brand_font(grid["body"])
    head_rows = _wrap(draw, headline[:90], head_font, limit)[:2] if show_headline else []
    body_rows = _wrap(draw, text, body_font, limit)[:2] if text else []
    if not head_rows and not body_rows:
        image.save(path)
        return
    head_size = head_font.size
    head_step, body_step = int(head_size * 1.42), int(grid["body"] * 1.55)
    strap_pad = int(head_size * 0.42)
    strap_h = head_step * len(head_rows) + strap_pad * 2 if head_rows else 0
    body_h = body_step * 2  # always reserve two caption rows so the strap never moves between shots
    body_gap = int(grid["small"] * 0.7) if head_rows and body_rows else 0
    body_gap = int(grid["small"] * 0.7) if head_rows else 0
    block_h = strap_h + body_gap + body_h
    top = grid["text_bottom"] - block_h
    _band(image, top, grid)
    y = top
    if head_rows:
        # Headline strap: solid gold plate, full bleed, heavy ink text (the broadcast headline bar).
        image.alpha_composite(Image.new("RGBA", (width, strap_h), GOLD), (0, y))
        ty = y + strap_pad
        for row in head_rows:
            draw.text((right, ty), row, font=head_font, fill=INK + (255,), anchor="ra", direction="rtl", language="ar")
            ty += head_step
        y += strap_h + body_gap
    for row in body_rows:
        draw.text((right, y), row, font=body_font, fill=WHITE, anchor="ra", direction="rtl", language="ar")
        y += body_step
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


def shot_motion_filter(style: str, width: int, height: int, seconds: float) -> str:
    """Gentle zoom or pan over one shot. The input must already be overscanned (MOTION_OVERSCAN x the frame).
    The text overlay is composited afterwards, so only the footage moves."""
    d = max(seconds, 0.1)
    if style in ("zoom_in", "zoom_out"):
        grow = f"(0.12*t/{d:.3f})" if style == "zoom_in" else f"(0.12-0.12*t/{d:.3f})"
        return (f"scale=w='trunc({width}*(1+{grow})/2)*2':h='trunc({height}*(1+{grow})/2)*2':eval=frame,"
                f"crop={width}:{height}")
    spans = {
        "pan_right": (f"(iw-{width})*t/{d:.3f}", f"(ih-{height})/2"),
        "pan_left": (f"(iw-{width})*(1-t/{d:.3f})", f"(ih-{height})/2"),
        "pan_down": (f"(iw-{width})/2", f"(ih-{height})*t/{d:.3f}"),
        "pan_up": (f"(iw-{width})/2", f"(ih-{height})*(1-t/{d:.3f})"),
    }
    if style not in spans:
        raise ValueError(f"unknown motion style: {style}")
    x, y = spans[style]
    return f"crop={width}:{height}:x='{x}':y='{y}'"


def shot_filter(index: int, seconds: float, width: int, height: int, round_index: int = 0) -> str:
    """Filter chain for one shot: cover-crop with overscan, exact duration, motion, mirrored on repeat rounds."""
    over_w, over_h = (int(width * MOTION_OVERSCAN) // 2 * 2, int(height * MOTION_OVERSCAN) // 2 * 2)
    style = MOTION_STYLES[index % len(MOTION_STYLES)]
    chain = [
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase",
        f"crop={over_w}:{over_h}",
        "setsar=1", "fps=30",
        "tpad=stop_mode=clone:stop_duration=3",  # a clip shorter than the shot is held, never short-changed
        f"trim=duration={seconds:.6f}", "setpts=PTS-STARTPTS",
        shot_motion_filter(style, width, height, seconds),
    ]
    if round_index % 2 == 1:
        chain.append("hflip")
    chain += ["setsar=1", "format=yuv420p"]  # scale/crop can change the SAR; concat needs identical shots
    return ",".join(chain)


def _search_with_fallback(query: str, pexels_key: str, pixabay_key: str, portrait: bool) -> list[dict]:
    """Pexels first (unless NEWSFLOW_BROLL_PROVIDER=pixabay); Pixabay is the licensed fallback when its key is set."""
    prefer_pixabay = os.getenv("NEWSFLOW_BROLL_PROVIDER", "pexels").strip().lower() == "pixabay"
    order = []
    if pexels_key and not (prefer_pixabay and pixabay_key):
        order.append("pexels")
    if pixabay_key:
        order.append("pixabay")
    if prefer_pixabay and pexels_key and "pexels" not in order:
        order.append("pexels")
    last_error = None
    for provider in order:
        try:
            if provider == "pexels":
                found = _search_videos(query, pexels_key, portrait)
                for item in found:
                    item.setdefault("provider", "Pexels")
                return found
            from newsflow import pixabay
            return pixabay.search_videos(query, pixabay_key, portrait)
        except RuntimeError as exc:
            last_error = exc
            print(f"[BROLL_PROVIDER_FALLBACK] {provider} failed for query; trying the next licensed source.")
    raise last_error or RuntimeError("لا يوجد مفتاح B-roll صالح.")


def render_broll_video(cards: list[dict], durations: list[float], audio: Path,
                       output: Path, portrait: bool = False) -> Path:
    """Render licensed Pexels (or Pixabay fallback) footage with a new moving scene and Arabic caption every 2.5s."""
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
    pexels_key = str(os.getenv("PEXELS_API_KEY") or "").strip()
    if not pexels_key and not pixabay_key:
        require_api_key(None)  # raises the standard fail-closed error
    api_key = pexels_key
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
            candidates = _search_with_fallback(query, pexels_key, pixabay_key, portrait)
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
                    "provider": candidate.get("provider", "Pexels"),
                    "photographer": candidate.get("photographer"),
                    "source_page": candidate.get("page"),
                })

            # One shot per ~2.2 s. Distinct clips come first; when a card has more shots than
            # clips, later shots reuse a clip from a different moment, mirrored, with another motion.
            loop_durations = [seconds for _, seconds in card_shots]
            loop_duration = sum(loop_durations)
            loop = work / f"broll-loop-{card_index:04d}.mp4"
            filter_parts = []
            inputs: list[tuple[Path, float, float]] = []
            for shot_number, seconds in enumerate(loop_durations):
                clip_index = shot_number % clip_count
                round_index = shot_number // clip_count
                clip_length = float(selected[clip_index].get("duration") or 0)
                offset = 0.0
                if round_index and clip_length > seconds:
                    offset = min(round_index * seconds * 1.3, max(0.0, clip_length - seconds))
                inputs.append((source_paths[clip_index], offset, seconds))
                filter_parts.append(
                    f"[{shot_number}:v]{shot_filter(shot_number, seconds, width, height, round_index)}[v{shot_number}]"
                )
            concat_inputs = "".join(f"[v{n}]" for n in range(len(loop_durations)))
            filter_parts.append(f"{concat_inputs}concat=n={len(loop_durations)}:v=1:a=0[outv]")
            loop_command = [ffmpeg, "-y"]
            for source, offset, seconds in inputs:
                loop_command.extend(["-ss", f"{offset:.3f}", "-t", f"{seconds + 0.5:.3f}", "-i", str(source)])
            loop_command.extend([
                "-filter_complex", ";".join(filter_parts),
                "-map", "[outv]",
                "-t", f"{loop_duration:.3f}",
                "-an", "-r", "30", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "22", *_thread_args(),
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
                "-crf", "22", *_thread_args(), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
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
    providers = sorted({src.get("provider", "Pexels") for src in manifest["sources"]}) or ["Pexels"]
    licenses = {"Pexels": "Pexels License", "Pixabay": "Pixabay Content License"}
    manifest["provider"] = "+".join(providers)
    manifest["license"] = " + ".join(licenses[name] for name in providers)
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


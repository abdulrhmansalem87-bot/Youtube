from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, features

RENDERER_VERSION = "wealthradar-mobile-safe-v2"
ARABIC_REGULAR = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
ARABIC_BOLD = (
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font_path(bold: bool = False) -> str:
    for candidate in (ARABIC_BOLD if bold else ARABIC_REGULAR):
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("لم يتم العثور على خط عربي مناسب؛ أوقفنا الإنتاج حتى لا تظهر حروف مكسورة.")


def _require_arabic_shaping() -> None:
    if not features.check("raqm"):
        raise RuntimeError(
            "محرك تشكيل العربية RAQM غير متاح في Pillow؛ أوقفنا الإنتاج بدلاً من إخراج نص عربي غير سليم."
        )


def _direction(text: str) -> str:
    return "rtl" if re.search(r"[\u0600-\u06ff]", text) else "ltr"


def _text_kwargs(text: str) -> dict:
    return {"direction": _direction(text), "language": "ar"}


def _clean_visual_text(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace('"', "").replace("'", "")
    text = text.replace("•", "،").replace("%", "٪")
    text = text.replace("چي", "جي").replace("چ", "ج")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([،؛؟.!])\s*", r"\1 ", text)
    return text.strip()


def wrap_text(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap without silently dropping overflow; all width checks use Arabic shaping."""
    text = _clean_visual_text(value)
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        bounds = draw.textbbox((0, 0), trial, font=font, **_text_kwargs(trial))
        width = bounds[2] - bounds[0]
        if width <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
            current = word
        else:
            raise ValueError(f"كلمة أطول من مساحة العرض الآمنة: {word[:32]}")
        bounds = draw.textbbox((0, 0), current, font=font, **_text_kwargs(current))
        if bounds[2] - bounds[0] > max_width:
            raise ValueError(f"كلمة أطول من مساحة العرض الآمنة: {word[:32]}")
    if current:
        lines.append(current)
    return lines


def _shorten_at_word(text: str, max_chars: int) -> str:
    value = _clean_visual_text(text)
    if len(value) <= max_chars:
        return value
    shortened = value[: max_chars - 1].rsplit(" ", 1)[0].rstrip("،؛: ")
    return (shortened or value[: max_chars - 1]).rstrip() + "…"


def _fit_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_height: int,
    max_lines: int,
    line_gap: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    candidate = _clean_visual_text(text)
    for shortening_round in range(3):
        for size in range(max_size, min_size - 1, -2):
            font = ImageFont.truetype(font_path, size)
            lines = wrap_text(draw, candidate, font, max_width)
            if len(lines) > max_lines:
                continue
            line_height = size + line_gap
            if len(lines) * line_height <= max_height:
                return font, lines, line_height
        candidate = _shorten_at_word(candidate, max(48, int(len(candidate) * 0.78)))
    raise RuntimeError("تعذر احتواء النص داخل مساحة آمنة؛ لم نسمح بقصه أو تداخله مع العناصر الأخرى.")


def render_card_image(
    card: dict,
    destination: Path,
    width: int,
    height: int,
    index: int,
    total: int,
    short: bool = False,
) -> dict:
    _require_arabic_shaping()
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), (7, 16, 31))
    draw = ImageDraw.Draw(image)
    accent = (45, 218, 195) if index % 2 == 0 else (245, 183, 83)

    # Soft geometric background, with a strong central safe area for phone screens.
    draw.ellipse((int(width * .70), -int(height * .24), int(width * 1.12), int(height * .18)), fill=(13, 45, 64))
    draw.ellipse((-int(width * .22), int(height * .78), int(width * .25), int(height * 1.18)), fill=(12, 39, 58))
    margin_x = int(width * .055)
    margin_y = int(height * .055)
    draw.rounded_rectangle(
        (margin_x, margin_y, width - margin_x, height - margin_y),
        radius=max(24, width // 48),
        fill=(12, 30, 49),
        outline=(39, 77, 98),
        width=max(2, width // 700),
    )

    brand_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52 if width > height else 62)
    small_ar_font = ImageFont.truetype(_font_path(True), 34 if width > height else 42)
    draw.text((width // 2, int(height * .12)), "WealthRadar", font=brand_font, fill=(248, 251, 255), anchor="mm")
    tagline = "أهم الأخبار المالية والاقتصادية"
    draw.text((width // 2, int(height * .18)), tagline, font=small_ar_font, fill=accent, anchor="mm", **_text_kwargs(tagline))

    if width > height:
        pill_top, pill_bottom = int(height * .25), int(height * .33)
        headline_top, headline_height = int(height * .37), int(height * .29)
        body_top, body_height = int(height * .69), int(height * .19)
        footer_y = int(height * .92)
        headline_sizes, headline_min, headline_lines, headline_gap = 88, 62, 3, 14
        body_sizes, body_min, body_lines, body_gap = 58, 44, 4, 10
        horizontal_width = int(width * .84)
    else:
        pill_top, pill_bottom = int(height * .235), int(height * .295)
        headline_top, headline_height = int(height * .33), int(height * .245)
        body_top, body_height = int(height * .61), int(height * .235)
        footer_y = int(height * .91)
        headline_sizes, headline_min, headline_lines, headline_gap = 92, 68, 4, 18
        body_sizes, body_min, body_lines, body_gap = 62, 48, 5, 14
        horizontal_width = int(width * .82)

    heading = _clean_visual_text(card.get("heading", f"الخبر {index + 1}"))
    draw.rounded_rectangle(
        (int(width * .22), pill_top, int(width * .78), pill_bottom),
        radius=max(18, width // 60),
        fill=(accent[0] // 5, accent[1] // 5, accent[2] // 5),
        outline=(accent[0] // 2, accent[1] // 2, accent[2] // 2),
        width=2,
    )
    draw.text((width // 2, (pill_top + pill_bottom) // 2), heading, font=small_ar_font,
              fill=accent, anchor="mm", **_text_kwargs(heading))

    title = _shorten_at_word(card.get("title", ""), 105 if width > height else 88)
    body = _shorten_at_word(card.get("body", ""), 210 if width > height else 230)
    bold_path, regular_path = _font_path(True), _font_path(False)
    headline_font, headline_wrapped, headline_line_height = _fit_block(
        draw, title, bold_path, headline_sizes, headline_min, horizontal_width,
        headline_height, headline_lines, headline_gap,
    )
    body_font, body_wrapped, body_line_height = _fit_block(
        draw, body, regular_path, int(headline_sizes * .68), body_min,
        horizontal_width, body_height, body_lines, body_gap,
    )

    headline_total = len(headline_wrapped) * headline_line_height
    headline_start = headline_top + (headline_height - headline_total) // 2
    for line_index, line in enumerate(headline_wrapped):
        y = headline_start + line_index * headline_line_height + headline_line_height // 2
        draw.text((width // 2, y), line, font=headline_font, fill=(250, 252, 255),
                  anchor="mm", **_text_kwargs(line))

    body_total = len(body_wrapped) * body_line_height
    body_start = body_top + (body_height - body_total) // 2
    for line_index, line in enumerate(body_wrapped):
        y = body_start + line_index * body_line_height + body_line_height // 2
        draw.text((width // 2, y), line, font=body_font, fill=(190, 211, 227),
                  anchor="mm", **_text_kwargs(line))

    footer = "المال والاقتصاد ببساطة"
    footer_font = ImageFont.truetype(_font_path(True), 32 if width > height else 40)
    draw.line((int(width * .28), footer_y - 48, int(width * .72), footer_y - 48), fill=(48, 82, 103), width=2)
    draw.text((width // 2, footer_y), footer, font=footer_font, fill=(225, 236, 245),
              anchor="mm", **_text_kwargs(footer))
    progress_left, progress_right = int(width * .12), int(width * .88)
    progress_y = int(height * .965)
    draw.rounded_rectangle((progress_left, progress_y, progress_right, progress_y + max(6, height // 280)),
                           radius=8, fill=(33, 56, 76))
    progress_end = progress_left + int((progress_right - progress_left) * ((index + 1) / max(total, 1)))
    draw.rounded_rectangle((progress_left, progress_y, progress_end, progress_y + max(6, height // 280)),
                           radius=8, fill=accent)
    image.save(destination, optimize=True)

    # Return a compact QA record for tests and the render manifest.
    return {
        "headline_lines": len(headline_wrapped),
        "body_lines": len(body_wrapped),
        "headline_font_size": headline_font.size,
        "body_font_size": body_font.size,
        "safe_width": horizontal_width,
        "headline_region": [headline_top, headline_top + headline_height],
        "body_region": [body_top, body_top + body_height],
    }


def _probe_segment(path: Path, duration: float, width: int, height: int, ffprobe: str) -> bool:
    if not path.is_file() or path.stat().st_size < 10_000:
        return False
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    metadata = json.loads(result.stdout)
    video = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video"), None)
    actual = float(metadata.get("format", {}).get("duration", 0))
    return bool(video and int(video.get("width", 0)) == width and int(video.get("height", 0)) == height
                and abs(actual - duration) <= 0.75)


def _render_segment(frame: Path, output: Path, duration: float, width: int, height: int, ffmpeg: str) -> None:
    temporary = output.with_name(output.stem + ".partial.mp4")
    temporary.unlink(missing_ok=True)
    zoom = "min(zoom+0.00025,1.045)"
    command = [
        ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", str(frame),
        "-t", f"{duration:.3f}", "-vf",
        f"zoompan=z='{zoom}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)
        os.replace(temporary, output)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or "")[-1200:]
            raise RuntimeError(f"فشل ترميز المشهد: {detail}") from None
        raise


def _mux_segments(segments: list[Path], audio: Path, output: Path, ffmpeg: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output.with_name(output.stem + ".concat.txt")
    temporary = output.with_name(output.stem + ".muxing.mp4")
    temporary.unlink(missing_ok=True)
    rows = []
    for segment in segments:
        safe_path = segment.resolve().as_posix().replace("'", "'\\''")
        rows.append(f"file '{safe_path}'")
    concat_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    command = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=1200)
        os.replace(temporary, output)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or "")[-1600:]
            raise RuntimeError(f"فشل تجميع المشاهد أو مزامنة الصوت: {detail}") from None
        raise


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def render_video_resumable(
    cards: list[dict],
    durations: list[float],
    audio: Path,
    output: Path,
    width: int,
    height: int,
    cache_dir: Path,
    commit_sha: str = "local",
    short: bool = False,
    frame_renderer: Callable | None = None,
    segment_renderer: Callable | None = None,
    segment_validator: Callable | None = None,
    muxer: Callable | None = None,
) -> Path:
    """Render independent scene segments and safely reuse validated segments on retry."""
    if not cards or len(cards) != len(durations):
        raise ValueError("يجب توفير مشهد واحد على الأقل ومدة مستقلة لكل مشهد.")
    if any(float(seconds) <= 0 for seconds in durations):
        raise ValueError("مدة المشهد يجب أن تكون أكبر من صفر.")
    if not audio.is_file():
        raise FileNotFoundError(f"ملف الصوت غير موجود: {audio}")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not frame_renderer and not ffmpeg:
        raise RuntimeError("FFmpeg غير متاح.")
    if not segment_renderer and not ffmpeg:
        raise RuntimeError("FFmpeg غير متاح.")
    if not segment_validator and not ffprobe:
        raise RuntimeError("FFprobe غير متاح.")
    if not muxer and not ffmpeg:
        raise RuntimeError("FFmpeg غير متاح.")

    frame_renderer = frame_renderer or render_card_image
    segment_renderer = segment_renderer or _render_segment
    segment_validator = segment_validator or _probe_segment
    muxer = muxer or _mux_segments
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = cache_dir / "frames"
    segments_dir = cache_dir / "segments"
    frames_dir.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    manifest.setdefault("segments", {})
    manifest.update({
        "renderer_version": RENDERER_VERSION,
        "commit_sha": commit_sha,
        "width": width,
        "height": height,
        "status": "rendering",
        "segment_count": len(cards),
    })
    _write_manifest(manifest_path, manifest)

    segment_paths: list[Path] = []
    fingerprints: list[str] = []
    audio_settings = {
        "voice": os.getenv("NEWSFLOW_TTS_VOICE", "ar-EG-ShakirNeural"),
        "rate": os.getenv("NEWSFLOW_TTS_RATE", "-6%"),
        "pitch": os.getenv("NEWSFLOW_TTS_PITCH", "-2Hz"),
    }

    for index, (card, seconds) in enumerate(zip(cards, durations)):
        key = f"{index:03d}"
        fingerprint_payload = {
            "renderer": RENDERER_VERSION,
            "commit": commit_sha,
            "card": card,
            "duration": round(float(seconds), 3),
            "width": width,
            "height": height,
            "audio_settings": audio_settings,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        fingerprints.append(fingerprint)
        segment = segments_dir / f"segment-{key}.mp4"
        frame = frames_dir / f"scene-{key}.png"
        previous = manifest["segments"].get(key, {})
        reusable = (
            previous.get("fingerprint") == fingerprint
            and previous.get("status") == "complete"
            and segment_validator(segment, float(seconds), width, height, ffprobe)
        )
        if reusable:
            segment_paths.append(segment)
            continue

        try:
            frame_renderer(card, frame, width, height, index, len(cards), short)
            segment_renderer(frame, segment, float(seconds), width, height, ffmpeg)
            if not segment_validator(segment, float(seconds), width, height, ffprobe):
                raise RuntimeError(f"فشل التحقق من المشهد رقم {index + 1}.")
            manifest["segments"][key] = {
                "fingerprint": fingerprint,
                "status": "complete",
                "file": str(segment.relative_to(cache_dir)),
                "bytes": segment.stat().st_size,
                "duration": round(float(seconds), 3),
            }
            _write_manifest(manifest_path, manifest)
            segment_paths.append(segment)
        except Exception as exc:
            manifest["segments"][key] = {
                "fingerprint": fingerprint,
                "status": "failed",
                "error_type": type(exc).__name__,
            }
            manifest["status"] = "segments_incomplete"
            _write_manifest(manifest_path, manifest)
            raise

    final_fingerprint = hashlib.sha256(
        json.dumps({"segments": fingerprints, "audio_duration": round(sum(durations), 3)},
                   sort_keys=True).encode("utf-8")
    ).hexdigest()
    if output.is_file() and manifest.get("status") == "complete" and manifest.get("final_fingerprint") == final_fingerprint:
        return output

    try:
        muxer(segment_paths, audio, output, ffmpeg)
        manifest["status"] = "complete"
        manifest["final_fingerprint"] = final_fingerprint
        manifest["output_bytes"] = output.stat().st_size if output.is_file() else 0
        _write_manifest(manifest_path, manifest)
    except Exception as exc:
        manifest["status"] = "mux_failed"
        manifest["mux_error_type"] = type(exc).__name__
        _write_manifest(manifest_path, manifest)
        raise
    return output


def render_cards_video(
    cards: list[dict],
    durations: list[float],
    audio: Path,
    output: Path,
    short: bool = False,
    commit_sha: str = "local",
    cache_dir: Path | None = None,
) -> Path:
    width, height = (1080, 1920) if short else (1920, 1080)
    if cache_dir is None:
        cache_dir = output.parent / ".render_cache" / output.stem
    return render_video_resumable(
        cards, durations, audio, output, width, height, cache_dir,
        commit_sha=commit_sha, short=short,
    )

"""Broadcast-style 1280x720 thumbnail: tight-cropped footage frame, solid gold headline strap in a heavy face,
solid gold channel bug, optional stat chip. Built from a frame of the already-rendered video, so it costs nothing."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from newsflow import broll

W, H = 1280, 720


def extract_frame(video: Path, seconds: float = 1.2) -> Image.Image:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg مطلوب لاستخراج لقطة الصورة المصغرة.")
    with tempfile.TemporaryDirectory(prefix="wr-thumb-") as directory:
        frame = Path(directory) / "frame.png"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{seconds}", "-i", str(video), "-frames:v", "1", str(frame)],
                       check=True, timeout=60)
        return Image.open(frame).convert("RGB").copy()


def _cover(image: Image.Image) -> Image.Image:
    """Fill 1280x720 with a slight punch-in (tight crop is the broadcast thumbnail convention)."""
    scale = max(W / image.width, H / image.height) * 1.08
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    left, top = (resized.width - W) // 2, (resized.height - H) // 2
    return resized.crop((left, top, left + W, top + H))


def make_thumbnail(frame: Image.Image, headline: str, out: Path, key_number: str = "") -> Path:
    headline = broll.clean_visual_text(headline)[:70]
    base = _cover(frame).convert("RGBA")
    grid = broll._layout(W, H)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = int(W * 0.05)
    size = 62
    font = broll._heavy_font(size, headline)
    rows = broll._wrap(draw, headline, font, W - margin * 2)
    while len(rows) > 2 and size > 44:
        size -= 4
        font = broll._heavy_font(size, headline)
        rows = broll._wrap(draw, headline, font, W - margin * 2)
    rows = rows[:2]
    step, pad = int(size * 1.4), int(size * 0.4)
    strap_h = step * len(rows) + pad * 2
    top = int(H * 0.90) - strap_h
    broll._band(layer, top - int(H * 0.04), {**grid, "fade": int(H * 0.2), "gap": int(H * 0.04)})
    layer.alpha_composite(Image.new("RGBA", (W, strap_h), broll.GOLD), (0, top))
    y = top + pad
    for row in rows:
        draw.text((W - margin, y), row, font=font, fill=broll.INK + (255,), anchor="ra", direction="rtl", language="ar")
        y += step
    broll._corner_tag(layer, draw, "WealthRadar", broll._brand_font(30, True), "left", {**grid, "top": 28, "small": 30}, solid=True)
    number = broll.clean_visual_text(key_number)[:14]
    if number:
        broll._corner_tag(layer, draw, number, broll._brand_font(44, True), "right", {**grid, "top": 28, "small": 36})
    base.alpha_composite(layer)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, quality=92)
    return out

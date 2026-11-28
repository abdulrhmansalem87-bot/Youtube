"""Chart engine: bar and line charts in the channel's palette A, rendered with Pillow (free, offline).

Charts take values from the verified data module; they never invent numbers. No sources are drawn on
screen (sources go in the video description).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PALETTE = {
    "bg1": (14, 20, 58), "bg2": (5, 8, 26), "gold": (255, 196, 31), "loss": (255, 92, 92),
    "gain": (46, 222, 150), "text": (255, 255, 255), "soft": (206, 214, 240), "card": (24, 32, 82),
}
KUFI = "/usr/share/fonts/truetype/noto/NotoKufiArabic-%s.ttf"
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf"
_NO_KUFI_GLYPHS = ",.%:()"


def _font(size: int, text: str = "", bold: bool = True) -> ImageFont.FreeTypeFont:
    kufi = KUFI % ("Bold" if bold else "Regular")
    if Path(kufi).is_file() and not any(c in text for c in _NO_KUFI_GLYPHS):
        return ImageFont.truetype(kufi, size)
    path = DEJAVU % ("-Bold" if bold else "")
    return ImageFont.truetype(path, int(size * 0.92))


def _text(draw, xy, text, size, fill, anchor="mm", bold=True):
    draw.text(xy, text, font=_font(size, text, bold), fill=fill, anchor=anchor, direction="rtl", language="ar")


def _canvas(size):
    w, h = size
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        px.line([(0, y), (w, y)], fill=tuple(int(PALETTE["bg1"][i] * (1 - k) + PALETTE["bg2"][i] * k) for i in range(3)))
    return img, px


def bar_chart(path, title: str, labels: list[str], values: list[float], *, value_fmt=lambda v: f"{v:g}",
              colors: list | None = None, size=(1920, 1080), unit_note: str = "") -> str:
    if len(labels) != len(values) or not values:
        raise ValueError("labels and values must be the same non-zero length")
    if any(v is None for v in values):
        raise ValueError("chart values must not contain None (blocked scenario?)")
    w, h = size
    img, d = _canvas(size)
    _text(d, (w // 2, int(h * .11)), title, int(h * .07), PALETTE["text"])
    left, right, top, base = int(w * .08), int(w * .92), int(h * .24), int(h * .80)
    n = len(values)
    slot = (right - left) / n
    bw = slot * .6
    vmax = max(values)
    for i, (lab, v) in enumerate(zip(labels, values)):
        x0 = left + i * slot + (slot - bw) / 2
        bh = (base - top) * (v / vmax) if vmax > 0 else 0
        col = (colors[i] if colors else PALETTE["gold"])
        d.rounded_rectangle([x0, base - bh, x0 + bw, base], radius=int(bw * .08), fill=col)
        _text(d, (x0 + bw / 2, base - bh - h * .04), value_fmt(v), int(h * .05), PALETTE["text"])
        _text(d, (x0 + bw / 2, base + h * .05), lab, int(h * .045), PALETTE["soft"], bold=False)
    d.line([left - 10, base, right + 10, base], fill=PALETTE["soft"], width=2)
    if unit_note:
        _text(d, (w // 2, int(h * .93)), unit_note, int(h * .036), PALETTE["soft"], bold=False)
    img.save(path)
    return str(path)


def line_chart(path, title: str, labels: list[str], values: list[float], *, value_fmt=lambda v: f"{v:g}",
               size=(1920, 1080), unit_note: str = "") -> str:
    if len(labels) != len(values) or len(values) < 2:
        raise ValueError("need at least two points with matching labels")
    w, h = size
    img, d = _canvas(size)
    _text(d, (w // 2, int(h * .11)), title, int(h * .07), PALETTE["text"])
    left, right, top, base = int(w * .1), int(w * .9), int(h * .26), int(h * .78)
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0
    pts = [(left + i * (right - left) / (len(values) - 1), base - (base - top) * (v - vmin) / span) for i, v in enumerate(values)]
    d.line(pts, fill=PALETTE["gold"], width=8, joint="curve")
    for (x, y), lab, v in zip(pts, labels, values):
        d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=PALETTE["gold"])
        _text(d, (x, y - h * .05), value_fmt(v), int(h * .045), PALETTE["text"])
        _text(d, (x, base + h * .07), lab, int(h * .042), PALETTE["soft"], bold=False)
    if unit_note:
        _text(d, (w // 2, int(h * .93)), unit_note, int(h * .036), PALETTE["soft"], bold=False)
    img.save(path)
    return str(path)


def scenario_charts(results, out_dir, start_year: int, end_year: int) -> list[str]:
    """Render the standard episode charts for ok results only. Blocked scenarios are never drawn."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ok = [r for r in results if r.status == "ok"]
    colors = [PALETTE["loss"] if r.key == "cash" else PALETTE["gold"] for r in ok]
    note = f"قيمة المبلغ بالجنيه في {end_year} (من {start_year})"
    p1 = bar_chart(out / "scenario_nominal.png", "كام بقت الفلوس؟", [r.name_ar for r in ok],
                   [r.end_value for r in ok], value_fmt=lambda v: f"{v:,.0f}", colors=colors, unit_note=note)
    p2 = bar_chart(out / "scenario_real.png", "بعد خصم التضخم", [r.name_ar for r in ok],
                   [r.real_end_value for r in ok], value_fmt=lambda v: f"{v:,.0f}",
                   colors=[PALETTE["loss"] if r.real_end_value < r.start_value else PALETTE["gain"] for r in ok],
                   unit_note=f"القوة الشرائية بقيمة {start_year}")
    return [p1, p2]

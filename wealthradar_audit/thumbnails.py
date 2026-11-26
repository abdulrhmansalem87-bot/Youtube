"""Thumbnail A/B pair for a Money Audit episode, in palette A, 1280x720 JPEG (free, offline, Pillow).

Both variants use only the verified calculator numbers and the episode question; nothing is invented.
A is result-first (the big number), B is curiosity-first (the starting amount and an open question,
the answer is left for the video). They differ in layout and emphasis so YouTube's Test & Compare
has a real difference to measure. No sources on screen, one idea per image, readable at phone size.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from PIL import ImageFont

from .charts import DEJAVU, PALETTE, _canvas, _font

W, H = 1280, 720
MAX_BYTES = 2_000_000  # YouTube thumbnail limit is 2 MB
HYPOTHESES = {
    "A": "result-first: the big real-return number leads, the question sits under it",
    "B": "curiosity-first: the starting amount and an open question, the answer stays in the video",
}


def key_figures(brief: dict) -> dict:
    """Pick the thumbnail numbers from the brief. Prefers the cash scenario; falls back to the worst ok result."""
    amount = float(brief["amount"])
    ok = [r for r in brief["results"] if r.get("status", "ok") == "ok" and r.get("real_return_pct") is not None]
    if not ok:
        raise ValueError("no verified scenario result to put on a thumbnail")
    pick = next((r for r in ok if r["key"] == "cash"), min(ok, key=lambda r: r["real_return_pct"]))
    pct = float(pick["real_return_pct"])
    return {
        "amount": amount, "start_year": int(brief["start_year"]), "end_year": int(brief["end_year"]),
        "pct": pct, "loss": pct < 0, "scenario_ar": pick.get("name_ar", ""),
    }


def _amount_ar(amount: float) -> str:
    return f"{amount:,.0f}"


def _fit(draw, text: str, max_width: int, start: int, bold: bool = True, floor: int = 40):
    size = start
    while size > floor:
        font = _font(size, text, bold)
        if draw.textlength(text, font=font, direction="rtl", language="ar") <= max_width:
            return size
        size -= 6
    return floor


def _bug(draw, name: str) -> None:
    font = ImageFont.truetype(DEJAVU % "-Bold", 30) if name.isascii() else _font(34, name, True)
    width = int(draw.textlength(name, font=font))
    draw.rounded_rectangle([40, 36, 40 + width + 36, 36 + 62], radius=14, fill=PALETTE["gold"])
    draw.text((40 + 18, 36 + 31), name, font=font, fill=(5, 8, 26), anchor="lm")


def variant_a(figs: dict, out: Path, channel: str = "WealthRadar") -> Path:
    img, d = _canvas((W, H))
    accent = PALETTE["loss"] if figs["loss"] else PALETTE["gain"]
    sign = "\u2212" if figs["loss"] else "+"
    number = f"{sign}{abs(figs['pct']):.0f}%"
    size = _fit(d, number, W - 160, 400)
    d.text((W // 2, 275), number, font=_font(size, number), fill=accent, anchor="mm", direction="ltr")
    label = "قوة شراء فلوسك"
    d.text((W // 2, 505), label, font=_font(_fit(d, label, W - 400, 70), label), fill=PALETTE["gold"], anchor="mm",
           direction="rtl", language="ar")
    line = f"{_amount_ar(figs['amount'])} جنيه في {figs['start_year']}"
    d.text((W // 2, 623), line, font=_font(_fit(d, line, W - 160, 76), line), fill=PALETTE["text"], anchor="mm",
           direction="rtl", language="ar")
    _bug(d, channel)
    return _save(img, out)


def variant_b(figs: dict, out: Path, channel: str = "WealthRadar") -> Path:
    img, d = _canvas((W, H))
    # Left card: the starting amount. Right: the open question. Gold edge splits them.
    d.rounded_rectangle([60, 170, 560, 560], radius=36, fill=PALETTE["card"], outline=PALETTE["gold"], width=6)
    amount = _amount_ar(figs["amount"])
    d.text((310, 300), amount, font=_font(_fit(d, amount, 440, 150), amount), fill=PALETTE["text"], anchor="mm",
           direction="ltr")
    d.text((310, 415), "جنيه", font=_font(96, "جنيه"), fill=PALETTE["gold"], anchor="mm", direction="rtl", language="ar")
    d.text((310, 512), str(figs["start_year"]), font=_font(64, "2021"), fill=PALETTE["soft"], anchor="mm", direction="ltr")
    q1, q2 = "بقوا كام", "دلوقتي؟"
    for text, y, colour in ((q1, 290, PALETTE["text"]), (q2, 470, PALETTE["gold"])):
        d.text((1210, y), text, font=_font(_fit(d, text, 600, 190), text), fill=colour, anchor="rm", direction="rtl",
               language="ar")
    _bug(d, channel)
    return _save(img, out)


def _save(img: Image.Image, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    quality = 92
    while True:
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.stat().st_size <= MAX_BYTES or quality <= 60:
            break
        quality -= 8
    if out.stat().st_size > MAX_BYTES:
        raise RuntimeError("thumbnail is over the 2 MB YouTube limit")
    return out


def make_pair(brief: dict, out_dir, channel: str = "WealthRadar") -> dict:
    """Write thumb_A.jpg, thumb_B.jpg and thumbnails.json. Returns {A: path, B: path, figures, hypotheses}."""
    out = Path(out_dir)
    figs = key_figures(brief)
    paths = {"A": str(variant_a(figs, out / "thumb_A.jpg", channel)), "B": str(variant_b(figs, out / "thumb_B.jpg", channel))}
    meta = {
        "variants": paths, "hypotheses": HYPOTHESES, "figures": figs,
        "how_to_test": "Upload thumb_A.jpg and thumb_B.jpg in YouTube Studio under Test & Compare. "
                       "Studio picks the winner by watch time share.",
    }
    (out / "thumbnails.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta

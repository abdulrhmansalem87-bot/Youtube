"""Thumbnail A/B pair for a Money Audit episode, in palette A, 1280x720 JPEG (free, offline, Pillow).

Both variants use only the verified calculator numbers and the episode question; nothing is invented.
A is result-first (a banknote with the lost part torn away and the big number), B is curiosity-first (the whole
banknote, a question mark and an open question, the answer is left for the video). Brand-led: the same navy
background, gold bar and small radar wordmark on every thumbnail; no face is needed. They differ in layout and emphasis so YouTube's Test & Compare
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
    "A": "result-first: a torn banknote shows what is left, the big real-return number leads",
    "B": "curiosity-first: the whole banknote and an open question, the answer stays in the video",
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


def _wordmark(img: Image.Image, name: str) -> None:
    """Subtle brand mark: a small radar ring and the channel name in soft text, bottom-left. No box."""
    d = ImageDraw.Draw(img)
    cx, cy = 62, H - 52
    d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], outline=PALETTE["gold"], width=4)
    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], outline=PALETTE["gold"], width=3)
    d.ellipse([cx + 5, cy - 14, cx + 13, cy - 6], fill=PALETTE["gold"])
    font = ImageFont.truetype(DEJAVU % "-Bold", 30) if name.isascii() else _font(34, name, True)
    d.text((cx + 34, cy), name.upper() if name.isascii() else name, font=font, fill=(150, 160, 205), anchor="lm")
    d.rectangle([0, H - 12, W, H], fill=PALETTE["gold"])  # the brand bar, the same on every thumbnail


def _note(amount: float, year: int, kept: float = 1.0, size=(720, 340)) -> Image.Image:
    """A drawn banknote (RGBA). kept < 1 tears away the right part, leaving a ghost outline of what is gone."""
    nw, nh = size
    note = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(note)
    d.rounded_rectangle([0, 0, nw - 1, nh - 1], radius=26, fill=(36, 112, 84))
    d.rounded_rectangle([14, 14, nw - 15, nh - 15], radius=18, outline=(120, 206, 164), width=4)
    for r in range(40, 200, 26):  # faint guilloche rings
        d.ellipse([nw * .72 - r, nh * .5 - r, nw * .72 + r, nh * .5 + r], outline=(52, 134, 102), width=3)
    for cx, cy in ((46, 46), (nw - 46, 46), (46, nh - 46), (nw - 46, nh - 46)):
        d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], outline=(150, 220, 184), width=4)
    amt = f"{amount:,.0f}"
    tx = nw // 2 if kept >= 0.999 else int(nw * kept) // 2 - 6
    room = (nw - 90) if kept >= 0.999 else int(nw * kept) - 80
    size_amt = 112
    while size_amt > 30 and d.textlength(amt, font=_font(size_amt, amt)) > room:
        size_amt -= 4
    d.text((tx, int(nh * .40)), amt, font=_font(size_amt, amt), fill=(255, 255, 255), anchor="mm", direction="ltr")
    sub = f"جنيه  {year}"
    size_sub = 52
    while size_sub > 24 and d.textlength(sub, font=_font(size_sub, sub), direction="rtl", language="ar") > room:
        size_sub -= 4
    d.text((tx, int(nh * .72)), sub, font=_font(size_sub, sub), fill=(214, 244, 228), anchor="mm",
           direction="rtl", language="ar")
    if kept >= 0.999:
        return note
    cut = int(nw * kept)
    import random
    rnd = random.Random(7)
    pts = [(cut, 0)]
    y = 0
    while y < nh:
        y = min(nh, y + rnd.randint(18, 34))
        pts.append((cut + rnd.randint(-16, 16), y))
    mask = Image.new("L", size, 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(0, 0)] + pts + [(0, nh)], fill=255)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    ghost = ImageDraw.Draw(out)
    for x in range(cut + 30, nw - 4, 26):  # dashed ghost of the missing part
        ghost.line([(x, 6), (min(x + 12, nw - 4), 6)], fill=(110, 125, 180), width=4)
        ghost.line([(x, nh - 7), (min(x + 12, nw - 4), nh - 7)], fill=(110, 125, 180), width=4)
    ghost.line([(nw - 5, 30), (nw - 5, nh - 30)], fill=(110, 125, 180), width=4)
    edge = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).polygon([(0, 0)] + [(x + 7, yy) for x, yy in pts] + [(0, nh)], fill=(244, 240, 226, 255))
    edge.putalpha(Image.eval(edge.getchannel("A"), lambda v: v))
    out.alpha_composite(edge)
    note.putalpha(mask)
    out.alpha_composite(note)
    out.info_alpha = Image.eval(mask, lambda v: v)  # note-only silhouette for the shadow
    return out


def _place(img: Image.Image, note: Image.Image, center, angle: float) -> None:
    rot = note.rotate(angle, expand=True, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", rot.size, (0, 0, 0, 0))
    sil = getattr(note, "info_alpha", None)
    if sil is not None:
        full = Image.new("L", note.size, 0)
        full.paste(sil)
        sh = full.rotate(angle, expand=True, resample=Image.BICUBIC)
    else:
        sh = rot.getchannel("A")
    shadow.putalpha(sh.point(lambda v: int(v * .45)))
    x, y = int(center[0] - rot.width / 2), int(center[1] - rot.height / 2)
    img.paste(shadow, (x + 10, y + 16), shadow)
    img.paste(rot, (x, y), rot)


def variant_a(figs: dict, out: Path, channel: str = "WealthRadar") -> Path:
    """Result-first. Three elements: the torn note (what is left of the money), the big number, one label."""
    img, d = _canvas((W, H))
    accent = PALETTE["loss"] if figs["loss"] else PALETTE["gain"]
    kept = max(0.2, min(0.95, 1 + figs["pct"] / 100)) if figs["loss"] else 1.0
    _place(img, _note(figs["amount"], figs["start_year"], kept, size=(630, 300)), (345, 360), -4)
    d = ImageDraw.Draw(img)
    sign = "\u2212" if figs["loss"] else "+"
    number = f"{sign}{abs(figs['pct']):.0f}%"
    size = _fit(d, number, 560, 330)
    d.text((955, 285), number, font=_font(size, number), fill=accent, anchor="mm", direction="ltr")
    label = "قوة شراء فلوسك"
    d.text((955, 500), label, font=_font(_fit(d, label, 540, 96), label), fill=PALETTE["text"], anchor="mm",
           direction="rtl", language="ar")
    _wordmark(img, channel)
    return _save(img, out)


def variant_b(figs: dict, out: Path, channel: str = "WealthRadar") -> Path:
    """Curiosity-first. Three elements: the whole note, a big question mark over it, the open question."""
    img, d = _canvas((W, H))
    _place(img, _note(figs["amount"], figs["start_year"], 1.0, size=(600, 290)), (335, 450), 5)
    d = ImageDraw.Draw(img)
    qm = "؟"
    d.text((470, 190), qm, font=_font(330, qm), fill=PALETTE["gold"], anchor="mm", direction="rtl", language="ar",
           stroke_width=10, stroke_fill=(5, 8, 26))
    for text, y, colour in (("بقوا كام", 250, PALETTE["text"]), ("دلوقتي؟", 450, PALETTE["gold"])):
        d.text((1230, y), text, font=_font(_fit(d, text, 560, 200), text), fill=colour, anchor="rm", direction="rtl",
               language="ar")
    _wordmark(img, channel)
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

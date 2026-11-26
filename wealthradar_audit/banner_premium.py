"""Premium channel banner: dark navy + metallic gold, radar mark, rising market line, Arabic-only tagline.

Run: python -m wealthradar_audit.banner_premium OUT.png [NAME] [TAGLINE]
2560x1440 (16:9). Logo, name and tagline sit inside the 1544x423 safe area (the part every device shows).
The channel name is a parameter. Everything is drawn here, so there are no assets and no fees.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 2560, 1440
CX, CY = W // 2, H // 2
KUFI = "/usr/share/fonts/truetype/noto/NotoKufiArabic-%s.ttf"
SERIF = "/usr/share/fonts/opentype/urw-base35/C059-Bold.otf"
GOLD_HI, GOLD_MID, GOLD_LO = (255, 232, 160), (222, 172, 70), (150, 104, 34)


def _serif() -> str:
    for p in (SERIF, "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"):
        if Path(p).is_file():
            return p
    raise FileNotFoundError("no serif font")


def _background() -> Image.Image:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - CX) / (W * .62)) ** 2 + ((yy - CY * 0.95) / (H * .78)) ** 2)
    t = np.clip(d, 0, 1.4)
    inner = np.array([20, 36, 78], np.float32)
    outer = np.array([3, 6, 18], np.float32)
    a = np.clip(1 - t, 0, 1)[..., None] ** 1.35
    img = outer * (1 - a) + inner * a
    # faint horizontal floor glow so the bottom is not dead black
    floor = np.exp(-((yy - H * .93) / 90.0) ** 2)[..., None] * np.array([10, 16, 34], np.float32)
    img = np.clip(img + floor, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def _gold_gradient(size, top=GOLD_HI, mid=GOLD_MID, bot=GOLD_LO) -> Image.Image:
    w, h = size
    col = np.zeros((h, 3), np.float32)
    for i in range(h):
        t = i / max(1, h - 1)
        if t < .5:
            u = t / .5
            c = [top[k] * (1 - u) + mid[k] * u for k in range(3)]
        else:
            u = (t - .5) / .5
            c = [mid[k] * (1 - u) + bot[k] * u for k in range(3)]
        col[i] = c
    return Image.fromarray(np.repeat(col[:, None, :], w, axis=1).astype(np.uint8), "RGB")


def _gold_fill(mask: Image.Image, bbox=None) -> Image.Image:
    """Metallic gold gradient clipped to a mask (L), graded over the mask's bounding box."""
    bb = bbox or mask.getbbox()
    layer = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    g = _gold_gradient((bb[2] - bb[0], bb[3] - bb[1])).convert("RGBA")
    layer.paste(g, (bb[0], bb[1]))
    layer.putalpha(mask)
    return layer


def _glow(layer: Image.Image, radius: int, strength: float) -> Image.Image:
    g = layer.filter(ImageFilter.GaussianBlur(radius))
    a = g.getchannel("A").point(lambda v: min(255, int(v * strength)))
    g.putalpha(a)
    return g


def _market_line(base: Image.Image) -> None:
    pts = []
    for i in range(0, W + 1, 8):
        x = i / W
        y = 0.80 - 0.50 * x ** 1.6 + 0.035 * math.sin(x * 21) + 0.02 * math.sin(x * 47 + 1)
        pts.append((i, y * H))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).line(pts, fill=255, width=5, joint="curve")
    fade = Image.linear_gradient("L").rotate(90).resize((W, H))  # left=dark? ensure left faint -> right bright
    fade = fade.transpose(Image.FLIP_LEFT_RIGHT)
    mask = ImageChops.multiply(mask, fade.point(lambda v: int(40 + v * .6)))
    line = _gold_fill(mask, (0, 0, W, H))
    base.alpha_composite(_glow(line, 14, 1.2))
    base.alpha_composite(line)


def _candles(base: Image.Image) -> None:
    rnd = random.Random(11)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for side in (0, 1):
        x = 70 if side == 0 else 2140
        price = 1020 if side == 0 else 980
        for i in range(10):
            o = price
            c = o + rnd.randint(-70, 60) * (1 if side == 1 else 1) - (25 if side == 1 else -5)
            hi, lo = min(o, c) - rnd.randint(15, 60), max(o, c) + rnd.randint(15, 60)
            fill = (222, 172, 70, 150) if c < o else (120, 150, 210, 110)
            xc = x + i * 40
            d.line([(xc, hi), (xc, lo)], fill=(222, 172, 70, 120), width=3)
            d.rectangle([xc - 11, min(o, c), xc + 11, max(o, c)], fill=fill)
            price = c
    edge = Image.linear_gradient("L").resize((W, H))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rectangle([0, 0, 520, H], fill=255)
    ImageDraw.Draw(mask).rectangle([2040, 0, W, H], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(120))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    base.alpha_composite(layer)


def _rings(base: Image.Image) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for r, a, wd in ((330, 70, 2), (470, 52, 2), (640, 40, 2), (840, 30, 2), (1060, 22, 2)):
        d.ellipse([CX - r, CY - r * .62 - 10, CX + r, CY + r * .62 - 10], outline=(222, 172, 70, a), width=wd)
    # tick marks on the second ring
    for k in range(0, 360, 6):
        ang = math.radians(k)
        r0, r1 = 470, 484 if k % 30 else 500
        x0, y0 = CX + r0 * math.cos(ang), CY - 10 + r0 * .62 * math.sin(ang)
        x1, y1 = CX + r1 * math.cos(ang), CY - 10 + r1 * .62 * math.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=(222, 172, 70, 60), width=2)
    base.alpha_composite(layer)


def _particles(base: Image.Image) -> None:
    rnd = random.Random(5)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(260):
        side = rnd.random()
        x = rnd.gauss(0, 330) + (80 if side < .5 else W - 80)
        y = rnd.gauss(H * .62, 330)
        r = rnd.choice((1.5, 2, 2, 3, 4))
        a = rnd.randint(70, 210)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 214, 120, a))
    base.alpha_composite(_glow(layer, 6, 1.4))
    base.alpha_composite(layer)


def _logo(size: int) -> Image.Image:
    """Radar ring with a rising arrow, metallic gold, transparent background."""
    s = size * 3
    c = s / 2
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    R = s * .47
    d.ellipse([c - R, c - R, c + R, c + R], outline=255, width=int(s * .05))
    r2 = s * .31
    d.ellipse([c - r2, c - r2, c + r2, c + r2], outline=255, width=int(s * .028))
    d.pieslice([c - r2, c - r2, c + r2, c + r2], -88, -38, fill=150)  # radar sweep
    pts = [(c - s * .27, c + s * .17), (c - s * .09, c - s * .02), (c + s * .02, c + s * .09), (c + s * .24, c - s * .17)]
    d.line(pts, fill=255, width=int(s * .075), joint="curve")
    hx, hy = pts[-1]
    d.polygon([(hx + s * .07, hy - s * .07), (hx - s * .075, hy - s * .02), (hx - s * .0, hy + s * .075)], fill=255)
    m = m.resize((size, size), Image.LANCZOS)
    return _gold_fill(m, (0, 0, size, size))


def build(out: Path, name: str = "WealthRadar", tagline: str = "فلوسك بتقدر بكام فعلاً؟ بنحسبها بأرقام رسمية") -> Path:
    img = _background()
    _rings(img)
    _candles(img)
    _market_line(img)
    _particles(img)

    # --- safe-area content (centre 1544x423: x 508..2052, y 508..931)
    logo = _logo(160)
    lx, ly = CX - logo.width // 2, 520
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    halo.alpha_composite(logo, (lx, ly))
    img.alpha_composite(_glow(halo, 26, 1.6))
    img.alpha_composite(halo)

    font = ImageFont.truetype(_serif(), 128)
    probe = ImageDraw.Draw(img)
    tb = probe.textbbox((0, 0), name, font=font, anchor="ls")
    nx, ny = CX - (tb[2] - tb[0]) // 2 - tb[0], 812  # baseline y
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((nx + 4, ny + 8), name, font=font, fill=(0, 0, 0, 200), anchor="ls")
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((nx, ny), name, font=font, fill=255, anchor="ls")
    gold = _gold_fill(mask)
    img.alpha_composite(_glow(gold, 20, .8))
    img.alpha_composite(gold)

    # tagline with fine rules either side
    tf = ImageFont.truetype(KUFI % "Medium", 54)
    ty = 885
    while probe.textbbox((0, 0), tagline, font=tf, anchor="mm", direction="rtl", language="ar")[2] > 940 and tf.size > 30:
        tf = ImageFont.truetype(KUFI % "Medium", tf.size - 2)
    tbb = probe.textbbox((CX, ty), tagline, font=tf, anchor="mm", direction="rtl", language="ar")
    tmask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(tmask).text((CX, ty), tagline, font=tf, fill=255, anchor="mm", direction="rtl", language="ar")
    tg = _gold_fill(tmask, (tbb[0], tbb[1], tbb[2], tbb[3]))
    img.alpha_composite(_glow(tg, 8, .7))
    img.alpha_composite(tg)
    rules = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rules)
    gap = 36
    for x0, x1 in ((tbb[0] - gap - 150, tbb[0] - gap), (tbb[2] + gap, tbb[2] + gap + 150)):
        rd.line([(x0, ty), (x1, ty)], fill=(222, 172, 70, 150), width=2)
        rd.ellipse([(x1 if x0 < CX else x0) - 4, ty - 4, (x1 if x0 < CX else x0) + 4, ty + 4], fill=(255, 226, 150, 230))
    img.alpha_composite(rules)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    build(Path(args[0]), *(args[1:3]))

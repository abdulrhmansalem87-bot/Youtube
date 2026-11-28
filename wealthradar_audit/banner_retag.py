"""Re-tag the channel's existing banner: keep the artwork, replace only the Arabic tagline under the wordmark.

Run: python -m wealthradar_audit.banner_retag SOURCE.jpg OUT.png
The source is the banner already on the channel. The old tagline row is rebuilt from the rows above and below it,
then the new tagline is set in gold with the same soft glow. Free, offline, Pillow only.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

TAGLINE = "فلوسك بتقدر بكام فعلاً؟ بنحسبها بأرقام رسمية"
KUFI = "/usr/share/fonts/truetype/noto/NotoKufiArabic-%s.ttf"


def retag(src: Path, out: Path, tagline: str = TAGLINE) -> Path:
    im = Image.open(src).convert("RGB")
    s = im.width / 1429  # coordinates below were measured on a 1429 px wide view
    x0, x1, y0, y1 = int(556 * s), int(884 * s), int(468 * s), int(503 * s)
    top, bot = y0 - 6, int(542 * s)  # also clears the small English strip below the tagline (owner dropped it)
    px = im.load()
    rnd = random.Random(7)
    patch = Image.new("RGB", (x1 - x0, bot - top))
    pp = patch.load()
    def row_avg(y):
        """Colours along row y, averaged over a wide window so map dots and candle bars do not streak down."""
        cols = [px[x, y] for x in range(x0, x1)]
        k = int(40 * s)
        out_row = []
        for i in range(len(cols)):
            seg = cols[max(0, i - k):i + k + 1]
            out_row.append(tuple(sum(c[j] for c in seg) // len(seg) for j in range(3)))
        return out_row

    ra, rb = row_avg(top), row_avg(bot - 1)
    for xi in range(x1 - x0):
        a, b = ra[xi], rb[xi]
        for y in range(top, bot):
            t = (y - top) / max(1, bot - 1 - top)
            pp[xi, y - top] = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
    patch = patch.filter(ImageFilter.GaussianBlur(4))
    # keep the soft edge: blend the patch in with a feathered mask
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).rectangle([14, 5, patch.width - 15, patch.height - 6], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(7))
    im.paste(patch, (x0, top), mask)
    # new tagline
    size = int(26 * s)
    font = ImageFont.truetype(KUFI % "Medium", size)
    probe = ImageDraw.Draw(im)
    maxw = int(400 * s)

    def width(f):
        b = probe.textbbox((0, 0), tagline, font=f, anchor="mm", direction="rtl", language="ar")
        return b[2] - b[0]

    while width(font) > maxw and size > 20:
        size -= 2
        font = ImageFont.truetype(KUFI % "Medium", size)
    cx, cy = im.width // 2 + int(6 * s), (y0 + y1) // 2 + int(3 * s)
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((cx, cy), tagline, font=font, fill=(214, 168, 80, 255), anchor="mm",
                              direction="rtl", language="ar")
    halo = glow.filter(ImageFilter.GaussianBlur(10))
    base = im.convert("RGBA")
    base.alpha_composite(halo)
    # vertical gold gradient inside the glyphs, light top to deeper bottom, like the wordmark
    text = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(text).text((cx, cy), tagline, font=font, fill=(255, 255, 255, 255), anchor="mm",
                              direction="rtl", language="ar")
    grad = Image.new("RGB", im.size)
    gd = ImageDraw.Draw(grad)
    for y in range(cy - size, cy + size):
        t = min(1, max(0, (y - (cy - size // 2)) / size))
        gd.line([(0, y), (im.width, y)], fill=(int(236 - 38 * t), int(200 - 50 * t), int(120 - 40 * t)))
    gold = grad.convert("RGBA")
    gold.putalpha(text.getchannel("A"))
    base.alpha_composite(gold)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    retag(Path(sys.argv[1]), Path(sys.argv[2]))

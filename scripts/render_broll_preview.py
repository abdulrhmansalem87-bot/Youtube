from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from newsflow.broll import render_broll_video
OUT = ROOT / "output" / "broll-preview"


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for the B-roll preview.")
    OUT.mkdir(parents=True, exist_ok=True)
    audio = OUT / "preview-tone.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
         "-codec:a", "libmp3lame", "-q:a", "5", str(audio)],
        check=True, capture_output=True,
    )
    cards = [{
        "heading": "اختبار B-roll",
        "title": "حركة الأسواق والاقتصاد",
        "body": "لقطات فيديو حقيقية متغيرة مع نص عربي واضح وصوت تجريبي",
        "captions": [
            "حركة الأسواق اليوم",
            "ما أثر الخبر على الأسعار؟",
            "راقب الأرقام قبل القرار",
        ],
    }]
    for portrait, name in ((False, "landscape"), (True, "portrait")):
        target = OUT / f"{name}-broll-preview.mp4"
        render_broll_video(cards, [7.0], audio, target, portrait=portrait)
        print(f"[BROLL_PREVIEW_READY] {target}")


if __name__ == "__main__":
    main()

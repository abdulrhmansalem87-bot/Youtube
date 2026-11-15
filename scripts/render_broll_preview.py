from __future__ import annotations

import json
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
        "title": "حركة الأسهم والاقتصاد",
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
        manifest_path = target.with_suffix(".broll-manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_ids = [str(item.get("video_id")) for item in manifest.get("sources", [])]
        if manifest.get("scene_count") != 3 or len(source_ids) != 3 or len(set(source_ids)) != 3:
            raise RuntimeError("B-roll preview must prove three distinct Pexels scenes within seven seconds.")
        print(f"[BROLL_PREVIEW_READY] {target} unique_scenes={len(set(source_ids))}")


if __name__ == "__main__":
    main()

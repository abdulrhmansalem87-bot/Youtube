from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from newsflow.pipeline import validate_video
from newsflow.rendering import render_cards_video


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "mobile-preview"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for the mobile preview.")
    OUT.mkdir(parents=True, exist_ok=True)
    audio = OUT / "preview-silence.mp3"
    run([
        ffmpeg, "-y", "-f", "lavfi", "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000",
        "-t", "8", "-codec:a", "libmp3lame", "-q:a", "4", str(audio),
    ])
    cards = [{
        "heading": "معاينة تصميم، بيانات تجريبية",
        "title": "الدولار يتحرك مع ترقب قرارات الفائدة",
        "body": "هذا نص تجريبي لا يمثل خبراً أو سعراً حقيقياً. نختبر وضوح الخط العربي وترتيب العناوين على شاشة الهاتف.",
    }]
    for name, short in (("landscape", False), ("portrait", True)):
        video = OUT / f"{name}.mp4"
        cache = OUT / ".render_cache" / name
        render_cards_video(
            cards, [8.0], audio, video, short=short,
            commit_sha="mobile-preview", cache_dir=cache,
        )
        validate_video(video, audio, expected_short=short)
        image = OUT / f"{name}.png"
        run([ffmpeg, "-y", "-ss", "3", "-i", str(video), "-frames:v", "1", str(image)])
        print(f"[MOBILE_PREVIEW_OK] {name} {video.stat().st_size} bytes {image.stat().st_size} bytes")
    print(f"[MOBILE_PREVIEW_READY] {OUT}")


if __name__ == "__main__":
    main()

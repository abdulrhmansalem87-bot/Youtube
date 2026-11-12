from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Running this file directly sets sys.path[0] to scripts/, not the repository root.
# Add the root explicitly so imports work identically in local runs and GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newsflow.pipeline import validate_video
from newsflow.rendering import render_cards_video


OUT = ROOT / "output" / "mobile-preview"
SCENE_SECONDS = 8.0
SCENE_TIMES = (3, 11, 19)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for the mobile preview.")
    OUT.mkdir(parents=True, exist_ok=True)
    audio = OUT / "preview-silence.mp3"
    total_duration = SCENE_SECONDS * 3
    run([
        ffmpeg, "-y", "-f", "lavfi", "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000",
        "-t", str(total_duration), "-codec:a", "libmp3lame", "-q:a", "4", str(audio),
    ])
    # Three synthetic examples exercise headline, market figures, and a concise takeaway.
    cards = [
        {
            "heading": "عنوان الخبر",
            "title": "التضخم يضغط على توقعات أسعار الفائدة",
            "body": "تتابع الأسواق أثر بيانات الأسعار على قرارات البنوك المركزية وتكلفة الاقتراض.",
        },
        {
            "heading": "أرقام السوق",
            "title": "ماذا تعني حركة العائد للمستثمر؟",
            "body": "الأرقام هنا تجريبية لا تمثل أسعاراً حقيقية. نختبر وضوح النسب وترتيبها على الهاتف.",
        },
        {
            "heading": "الخلاصة",
            "title": "افهم الخبر قبل اتخاذ القرار",
            "body": "نوضح ما حدث، ولماذا يهمك، ونفصل الوقائع عن التوقعات مع الإشارة إلى المصدر.",
        },
    ]
    for name, short in (("landscape", False), ("portrait", True)):
        video = OUT / f"{name}.mp4"
        cache = OUT / ".render_cache" / name
        render_cards_video(
            cards, [SCENE_SECONDS] * len(cards), audio, video, short=short,
            commit_sha="mobile-preview", cache_dir=cache,
        )
        validate_video(video, audio, expected_short=short)
        for index, second in enumerate(SCENE_TIMES, start=1):
            image = OUT / f"{name}-{index:02d}.png"
            run([ffmpeg, "-y", "-ss", str(second), "-i", str(video), "-frames:v", "1", str(image)])
            print(f"[MOBILE_FRAME_OK] {name}-{index:02d} {image.stat().st_size} bytes")
        print(f"[MOBILE_PREVIEW_OK] {name} {video.stat().st_size} bytes")
    print(f"[MOBILE_PREVIEW_READY] {OUT}")


if __name__ == "__main__":
    main()

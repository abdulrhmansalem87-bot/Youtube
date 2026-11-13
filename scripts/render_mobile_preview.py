from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newsflow.pipeline import validate_video
from newsflow.rendering import render_cards_video

OUT = ROOT / "output" / "mobile-preview"
PHONE_SIZE = (390, 844)
SCENE_SECONDS = 6.0


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)


def phone_view(frame_path: Path, destination: Path) -> None:
    frame = Image.open(frame_path).convert("RGB")
    target_height = round(frame.height * PHONE_SIZE[0] / frame.width)
    frame = frame.resize((PHONE_SIZE[0], target_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", PHONE_SIZE, (0, 0, 0))
    canvas.paste(frame, (0, (PHONE_SIZE[1] - target_height) // 2))
    canvas.save(destination, optimize=True)


def build_phone_comparison(paths: list[tuple[str, Path]]) -> Path:
    label_height = 34
    cell_w, cell_h = PHONE_SIZE
    sheet = Image.new("RGB", (cell_w * 3, (cell_h + label_height) * 2), (18, 24, 32))
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(paths):
        row, col = divmod(index, 3)
        x, y = col * cell_w, row * (cell_h + label_height)
        draw.text((x + 10, y + 8), label, fill=(245, 245, 245))
        image = Image.open(path).convert("RGB").resize(PHONE_SIZE, Image.Resampling.LANCZOS)
        sheet.paste(image, (x, y + label_height))
    output = OUT / "phone-comparison.png"
    sheet.save(output, optimize=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Render real-story 16:9 and 9:16 phone previews.")
    parser.add_argument(
        "--stories",
        default=str(ROOT / "tests" / "fixtures" / "mobile_preview_stories.json"),
        help="JSON list of stories with title, summary, source, and link",
    )
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for the mobile preview.")
    stories = json.loads(Path(args.stories).read_text(encoding="utf-8"))
    if not isinstance(stories, list) or len(stories) < 2:
        raise RuntimeError("The mobile preview needs at least two story records.")

    cards = [{
        "heading": "المقدمة",
        "title": "أهم تطورات المال والأسواق",
        "body": "نوضح ما حدث، ولماذا يهمك، ونفصل الوقائع عن التوقعات.",
    }]
    for index, story in enumerate(stories[:3], start=1):
        cards.append({
            "heading": f"الخبر {index:02d}، {story.get('source', 'المصدر')}",
            "title": story["title"],
            "body": story["summary"],
        })
    cards.append({
        "heading": "الخلاصة",
        "title": "افهم الخبر قبل اتخاذ القرار",
        "body": "تابع المصدر الأصلي، واشترك في WealthRadar وفعّل زر الجرس.",
    })

    OUT.mkdir(parents=True, exist_ok=True)
    total_duration = SCENE_SECONDS * len(cards)
    audio = OUT / "preview-silence.mp3"
    run([
        ffmpeg, "-y", "-f", "lavfi", "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000",
        "-t", str(total_duration), "-codec:a", "libmp3lame", "-q:a", "4", str(audio),
    ])

    phone_frames: list[tuple[str, Path]] = []
    cases = (("landscape", False), ("portrait-long", True))
    sample_times = (SCENE_SECONDS / 2, total_duration / 2, total_duration - SCENE_SECONDS / 2)
    for name, portrait in cases:
        video = OUT / f"{name}.mp4"
        cache = OUT / ".render_cache" / name
        render_cards_video(
            cards, [SCENE_SECONDS] * len(cards), audio, video,
            short=False, portrait=portrait,
            commit_sha="mobile-preview", cache_dir=cache,
        )
        validate_video(video, audio, expected_short=False, expected_portrait=portrait)
        for index, second in enumerate(sample_times, start=1):
            frame = OUT / f"{name}-{index:02d}.png"
            run([ffmpeg, "-y", "-ss", str(second), "-i", str(video), "-frames:v", "1", str(frame)])
            if not frame.is_file() or frame.stat().st_size < 10_000:
                raise RuntimeError(f"Preview frame missing or too small: {frame}")
            phone = OUT / f"{name}-phone-{index:02d}.png"
            phone_view(frame, phone)
            phone_frames.append((f"{name} {index}/3", phone))
        print(f"[MOBILE_PREVIEW_OK] {name} bytes={video.stat().st_size} frames=3")

    comparison = build_phone_comparison(phone_frames)
    print(f"[MOBILE_PHONE_COMPARISON] {comparison} bytes={comparison.stat().st_size}")
    print("[MOBILE_PREVIEW_READY] landscape and portrait previews are artifacts only; no upload.")


if __name__ == "__main__":
    main()

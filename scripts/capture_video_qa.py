from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture actual WealthRadar MP4 frames for phone QA.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", default="output/mobile-qa")
    args = parser.parse_args()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for visual QA.")
    video = Path(args.video)
    if not video.is_file() or video.stat().st_size < 100_000:
        raise RuntimeError("The rendered MP4 is missing or too small for visual QA.")
    metadata = json.loads(run([
        ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", str(video)
    ]))
    duration = float(metadata.get("format", {}).get("duration", 0))
    streams = metadata.get("streams", [])
    if duration <= 0 or not any(s.get("codec_type") == "video" for s in streams):
        raise RuntimeError("The MP4 has no usable video stream.")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise RuntimeError("The MP4 has no audio stream.")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    times = (min(1.0, duration / 4), duration / 2, max(0.0, duration - 1.0))
    phone_size = (390, 844)
    labels = ("start", "middle", "end")
    phones = []
    for label, second in zip(labels, times):
        frame_path = out / f"{label}.png"
        subprocess.run([
            ffmpeg, "-y", "-ss", f"{second:.3f}", "-i", str(video),
            "-frames:v", "1", str(frame_path)
        ], check=True, capture_output=True, text=True, timeout=300)
        if not frame_path.is_file() or frame_path.stat().st_size < 10_000:
            raise RuntimeError(f"Could not capture {label} frame from final MP4.")
        frame = Image.open(frame_path).convert("RGB")
        scaled_h = round(frame.height * phone_size[0] / frame.width)
        frame = frame.resize((phone_size[0], scaled_h), Image.Resampling.LANCZOS)
        phone = Image.new("RGB", phone_size, (0, 0, 0))
        phone.paste(frame, (0, (phone_size[1] - scaled_h) // 2))
        phone_path = out / f"phone-{label}.png"
        phone.save(phone_path, optimize=True)
        phones.append((label, phone_path))
    sheet = Image.new("RGB", (phone_size[0] * 3, 878), (18, 24, 32))
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(phones):
        x = index * phone_size[0]
        draw.text((x + 10, 8), label, fill=(245, 245, 245))
        sheet.paste(Image.open(path).convert("RGB"), (x, 34))
    contact = out / "phone-contact.png"
    sheet.save(contact, optimize=True)
    print(f"[ACTUAL_VIDEO_QA_FRAMES] duration={duration:.2f}s screenshots=3 contact={contact}")


if __name__ == "__main__":
    main()

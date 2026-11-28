"""Render a predictions-receipt Short from the ledger (code path only; not part of the NewsFlow workflow).

    python -m newsflow.receipt_video [--today YYYY-MM-DD] [--out DIR] [--limit 1] [--mark-made]

Settles due predictions, then for each settled prediction without a video: writes Arabic
narration, free Edge TTS audio, a portrait Short with the before/after card and hit-rate counter,
and a metadata JSON (Arabic title, description with sources, disclaimer). Needs PEXELS_API_KEY,
ffmpeg and network access. Never uploads.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path

from . import predictions as pred


def build_short(entry: dict, counter: dict, out_dir: Path) -> dict:
    from .broll import render_broll_video
    from .pipeline import make_audio

    out_dir.mkdir(parents=True, exist_ok=True)
    audio = out_dir / f"{entry['id']}.mp3"
    video = out_dir / f"{entry['id']}.mp4"
    script = pred.receipt_script(entry, counter)
    asyncio.run(make_audio(script, audio))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True, capture_output=True, text=True)
    render_broll_video([pred.video_card(entry, counter)], [float(probe.stdout.strip())], audio, video, portrait=True)
    meta = pred.receipt_metadata({"predictions": [entry]})
    meta["counter"] = counter
    meta["script"] = script
    meta["video"] = str(video)
    (out_dir / f"{entry['id']}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--out", default="receipt_output")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--mark-made", action="store_true")
    args = parser.parse_args(argv)
    ledger = pred.load_ledger()
    pred.settle_due(ledger, date.fromisoformat(args.today))
    counter = pred.hit_rate(ledger)
    todo = pred.pending_for_video(ledger)[: args.limit]
    if not todo:
        print("no settled predictions waiting for a video")
        pred.save_ledger(ledger)
        return 0
    for entry in todo:
        build_short(entry, counter, Path(args.out))
        if args.mark_made:
            entry["video_made"] = True
    pred.save_ledger(ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

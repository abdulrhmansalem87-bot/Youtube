#!/usr/bin/env python3
"""Validate BookFlow silent-video plans. Standard-library only; no media or network access."""
import argparse
import json
import sys
from pathlib import Path

SHORT = {"count": (6, 8), "scene_seconds": (6, 10), "ratio": "9:16", "resolution": "1080x1920"}
LONG = {"min_scenes": 20, "max_scene_seconds": 15, "ratio": "16:9", "resolution": "1920x1080", "total_seconds": (290, 310)}

def validate(plan):
    errors = []
    required = ("title", "video_type", "duration_seconds", "aspect_ratio", "resolution", "audio", "book_reference", "scenes")
    for key in required:
        if key not in plan:
            errors.append("missing top-level field: " + key)
    if errors:
        return errors
    kind = plan["video_type"]
    if kind not in ("short", "long"):
        return ["video_type must be 'short' or 'long'"]
    audio = plan["audio"]
    if not isinstance(audio, dict) or audio.get("enabled") is not False or audio.get("mode") != "silent":
        errors.append("audio must explicitly declare enabled=false and mode='silent'")
    scenes = plan["scenes"]
    if not isinstance(scenes, list):
        return errors + ["scenes must be a JSON array"]
    if kind == "short":
        if not SHORT["count"][0] <= len(scenes) <= SHORT["count"][1]:
            errors.append("short requires 6-8 scenes; found " + str(len(scenes)))
        if plan["aspect_ratio"] != SHORT["ratio"] or plan["resolution"] != SHORT["resolution"]:
            errors.append("short must be 9:16 at 1080x1920")
    else:
        if len(scenes) < LONG["min_scenes"]:
            errors.append("long requires at least 20 scenes; found " + str(len(scenes)))
        if plan["aspect_ratio"] != LONG["ratio"] or plan["resolution"] != LONG["resolution"]:
            errors.append("long must be 16:9 at 1920x1080")
    durations = []
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            errors.append(f"scene {i} must be an object")
            continue
        for key in ("duration_seconds", "visual", "text_en", "translation_ar", "source_note"):
            if not scene.get(key):
                errors.append(f"scene {i}: missing {key}")
        try:
            duration = float(scene["duration_seconds"])
            durations.append(duration)
            if duration <= 0:
                errors.append(f"scene {i}: duration must be positive")
            if kind == "short" and not SHORT["scene_seconds"][0] <= duration <= SHORT["scene_seconds"][1]:
                errors.append(f"scene {i}: short scene duration must be 6-10 seconds")
            if kind == "long" and duration > LONG["max_scene_seconds"]:
                errors.append(f"scene {i}: long scene duration must not exceed 15 seconds")
        except (KeyError, TypeError, ValueError):
            errors.append(f"scene {i}: duration_seconds must be numeric")
        if isinstance(scene.get("text_en"), str) and len(scene["text_en"]) > 120:
            errors.append(f"scene {i}: English overlay exceeds 120 characters")
        if isinstance(scene.get("translation_ar"), str) and len(scene["translation_ar"]) > 180:
            errors.append(f"scene {i}: Arabic translation exceeds 180 characters")
        quote = scene.get("direct_quote", "")
        if quote and len(str(quote).split()) > 25:
            errors.append(f"scene {i}: direct quote exceeds 25 words")
        if quote and not scene.get("quote_attribution"):
            errors.append(f"scene {i}: direct quote requires quote_attribution")
    total = sum(durations)
    try:
        declared = float(plan["duration_seconds"])
        if abs(total - declared) > 0.01:
            errors.append(f"declared duration {declared:g}s does not match scene total {total:g}s")
    except (TypeError, ValueError):
        errors.append("duration_seconds must be numeric")
    if kind == "long" and not LONG["total_seconds"][0] <= total <= LONG["total_seconds"][1]:
        errors.append("long scene total must be 290-310 seconds (5-minute target)")
    if kind == "short" and not 48 <= total <= 80:
        errors.append("short total must be 48-80 seconds for 6-8 scenes")
    book = plan["book_reference"]
    if not isinstance(book, dict) or not book.get("title") or not book.get("author") or not book.get("edition_or_url"):
        errors.append("book_reference must include title, author and edition_or_url")
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[BOOKFLOW_INVALID] cannot read valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("[BOOKFLOW_INVALID] plan root must be a JSON object", file=sys.stderr)
        return 2
    errors = validate(plan)
    if errors:
        for error in errors:
            print("[BOOKFLOW_ERROR] " + error, file=sys.stderr)
        return 1
    print(f"[BOOKFLOW_VALID] type={plan['video_type']} scenes={len(plan['scenes'])} duration={plan['duration_seconds']}s silent=true")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

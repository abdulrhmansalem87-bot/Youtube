"""Fail-closed YouTube upload checks shared by WealthRadar workflows."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CONTENT_MARKER_PREFIX = "WealthRadar-Content-ID:"


def content_marker(content_id: str) -> str:
    value = str(content_id).strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError("A non-empty, whitespace-free content ID is required.")
    return f"{CONTENT_MARKER_PREFIX} {value}"


def verify_wealthradar_channel(youtube) -> tuple[str, str]:
    """Resolve the authenticated channel and fail unless its title is WealthRadar."""
    response = youtube.channels().list(
        part="id,snippet,contentDetails", mine=True
    ).execute()
    matches = [
        item for item in response.get("items", [])
        if str(item.get("snippet", {}).get("title", "")).strip().casefold() == "wealthradar"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "تعذر تأكيد القناة المستهدفة: يجب أن يعيد YouTube قناة واحدة باسم WealthRadar بالضبط. لم يتم الرفع."
        )
    channel = matches[0]
    channel_id = str(channel.get("id", "")).strip()
    uploads_playlist = str(
        channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
    ).strip()
    if not channel_id or not uploads_playlist:
        raise RuntimeError("استجابة YouTube لا تحتوي معرّف القناة وقائمة الرفع. لم يتم الرفع.")
    return channel_id, uploads_playlist


def ensure_not_duplicate(youtube, uploads_playlist_id: str, content_id: str) -> None:
    """Scan the authenticated channel's uploads playlist for the stable content marker."""
    marker = content_marker(content_id)
    page_token = None
    while True:
        kwargs = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        page = youtube.playlistItems().list(**kwargs).execute()
        video_ids = [
            str(item.get("contentDetails", {}).get("videoId", "")).strip()
            for item in page.get("items", [])
        ]
        video_ids = [value for value in video_ids if value]
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start:start + 50]
            response = youtube.videos().list(
                part="snippet", id=",".join(batch)
            ).execute()
            for video in response.get("items", []):
                description = str(video.get("snippet", {}).get("description", ""))
                if marker in description:
                    raise RuntimeError(
                        "تم العثور على نسخة سابقة من المحتوى نفسه في القناة. أُوقف الرفع لمنع التكرار."
                    )
        page_token = page.get("nextPageToken")
        if not page_token:
            break


def verify_private_video(youtube, video_id: str, expected_channel_id: str) -> dict:
    response = youtube.videos().list(
        part="snippet,status", id=video_id
    ).execute()
    items = response.get("items", [])
    if len(items) != 1:
        raise RuntimeError("لم يتمكن YouTube من إعادة الفيديو للتحقق بعد الرفع.")
    video = items[0]
    privacy = str(video.get("status", {}).get("privacyStatus", ""))
    channel_id = str(video.get("snippet", {}).get("channelId", ""))
    if privacy != "private":
        raise RuntimeError(
            f"YouTube لم يؤكد خصوصية PRIVATE؛ الحالة المعادة هي {privacy or 'غير معروفة'}."
        )
    if channel_id != expected_channel_id:
        raise RuntimeError("الفيديو لا ينتمي إلى قناة WealthRadar التي تم التحقق منها.")
    return video


def upsert_upload_record(output_dir: Path | str, record: dict) -> Path:
    """Persist an append/update upload ledger inside the workflow artifact directory."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "upload_log.json"
    records = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("ملف سجل الرفع موجود لكنه غير صالح؛ أُوقف تحديث السجل.") from exc
        if not isinstance(loaded, list):
            raise RuntimeError("ملف سجل الرفع ليس قائمة صالحة؛ أُوقف تحديث السجل.")
        records = loaded
    item = dict(record)
    item.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
    video_id = str(item.get("video_id", "")).strip()
    if video_id:
        for index, old in enumerate(records):
            if str(old.get("video_id", "")).strip() == video_id:
                records[index] = item
                break
        else:
            records.append(item)
    else:
        records.append(item)
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path

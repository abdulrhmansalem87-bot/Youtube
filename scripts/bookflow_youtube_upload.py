from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
LONG = ROOT / "output/bookflow/episode-01-long.mp4"
SHORT = ROOT / "output/bookflow/episode-01-short.mp4"
PLAN = ROOT / "bookflow/episodes/episode-01-psychology-of-money.json"
SHORT_PLAN = ROOT / "bookflow/episodes/episode-01-companion-short.json"
PACKAGE = ROOT / "bookflow/episodes/episode-01-production-package.md"

def credentials():
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing YouTube OAuth secrets: " + ", ".join(missing))
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )
    creds.refresh(Request())
    if not creds.valid:
        raise RuntimeError("YouTube OAuth refresh did not produce valid credentials")
    return creds

def verify_channel(youtube):
    expected = os.getenv("YOUTUBE_EXPECTED_CHANNEL_TITLE", "WealthRadar").strip().casefold()
    response = youtube.channels().list(part="snippet", mine=True, maxResults=50).execute()
    matches = [
        item for item in response.get("items", [])
        if str(item.get("snippet", {}).get("title", "")).strip().casefold() == expected
    ]
    if len(matches) != 1 or not matches[0].get("id"):
        raise RuntimeError("Authenticated YouTube channel is not uniquely verified as WealthRadar")
    channel_id = str(matches[0]["id"])
    print(f"[CHANNEL_VERIFIED] channel_id={channel_id}", flush=True)
    return channel_id

def upload(youtube, channel_id, path, title, description, tags):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty video file: {path.name}")
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "27",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "zxx",
        },
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = request.execute()
    video_id = response.get("id")
    status = response.get("status", {}).get("privacyStatus")
    returned_channel = response.get("snippet", {}).get("channelId")
    if not video_id or status != "private" or returned_channel != channel_id:
        raise RuntimeError(f"YouTube did not confirm the expected PRIVATE upload for {path.name}")
    url = f"https://youtu.be/{video_id}"
    print(f"[UPLOAD_VERIFIED] file={path.name} url={url} privacy=private channel={channel_id}", flush=True)
    return url

def main():
    for path in (LONG, SHORT, PLAN, SHORT_PLAN, PACKAGE):
        if not path.is_file():
            raise RuntimeError(f"Required BookFlow input missing: {path}")
    long_plan = json.loads(PLAN.read_text(encoding="utf-8"))
    short_plan = json.loads(SHORT_PLAN.read_text(encoding="utf-8"))
    package = PACKAGE.read_text(encoding="utf-8")
    start = package.find("## Description")
    end = package.find("\n## Chapters", start)
    description = package[start:end].replace("## Description", "", 1).strip() if start >= 0 else (
        "An original visual breakdown of The Psychology of Money by Morgan Housel. "
        "Educational explanation, not investment advice or a reproduction of book pages."
    )
    # Keep the complete, authored episode description and chapter list, not internal production notes.
    description = description.split("\n## Editorial corrections applied")[0].strip()
    short_description = (
        "A powerful lesson from The Psychology of Money: income is not wealth; "
        "what you keep matters. Original educational paraphrase.\n\n"
        "#shorts #PersonalFinance #MoneyMindset #WealthRadar"
    )
    youtube = build("youtube", "v3", credentials=credentials(), cache_discovery=False)
    channel_id = verify_channel(youtube)
    long_url = upload(
        youtube, channel_id, LONG, long_plan["title"],
        description + "\n\n#PersonalFinance #MoneyMindset #BookSummary #WealthBuilding",
        ["The Psychology of Money", "Morgan Housel", "personal finance", "money mindset", "wealth building", "WealthRadar"],
    )
    short_url = upload(
        youtube, channel_id, SHORT, short_plan["title"],
        short_description + f"\n\nWatch the full episode: {long_url}",
        ["shorts", "The Psychology of Money", "money mindset", "personal finance", "WealthRadar"],
    )
    print(f"[BOOKFLOW_UPLOAD_COMPLETE] long={long_url} short={short_url}", flush=True)

if __name__ == "__main__":
    main()

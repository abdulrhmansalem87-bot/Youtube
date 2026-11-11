import json
import tempfile
import unittest

from newsflow.youtube_safety import (
    content_marker, ensure_not_duplicate, upsert_upload_record,
    verify_private_video, verify_wealthradar_channel,
)


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeResource:
    def __init__(self, response):
        self.response = response

    def list(self, **kwargs):
        return FakeRequest(self.response)


class FakeYouTube:
    def __init__(self, channel_title="WealthRadar", video_description=""):
        self.channel_title = channel_title
        self.video_description = video_description

    def channels(self):
        return FakeResource({
            "items": [{
                "id": "channel-123",
                "snippet": {"title": self.channel_title},
                "contentDetails": {"relatedPlaylists": {"uploads": "uploads-123"}},
            }]
        })

    def playlistItems(self):
        return FakeResource({
            "items": [{"contentDetails": {"videoId": "old-video"}}],
        })

    def videos(self):
        return FakeResource({
            "items": [{
                "id": "old-video",
                "snippet": {
                    "description": self.video_description,
                    "channelId": "channel-123",
                },
                "status": {"privacyStatus": "private"},
            }]
        })


class YouTubeSafetyTests(unittest.TestCase):
    def test_resolves_only_exact_wealthradar_channel(self):
        channel_id, playlist_id = verify_wealthradar_channel(FakeYouTube())
        self.assertEqual(channel_id, "channel-123")
        self.assertEqual(playlist_id, "uploads-123")

    def test_rejects_wrong_channel(self):
        with self.assertRaisesRegex(RuntimeError, "WealthRadar"):
            verify_wealthradar_channel(FakeYouTube(channel_title="Personal Channel"))

    def test_blocks_duplicate_content_marker(self):
        marker = content_marker("abc123")
        youtube = FakeYouTube(video_description=f"Older description\n{marker}")
        with self.assertRaisesRegex(RuntimeError, "نسخة سابقة"):
            ensure_not_duplicate(youtube, "uploads-123", "abc123")

    def test_allows_content_without_existing_marker(self):
        youtube = FakeYouTube(video_description="different content")
        ensure_not_duplicate(youtube, "uploads-123", "new-content")

    def test_verifies_private_video_on_expected_channel(self):
        video = verify_private_video(FakeYouTube(), "old-video", "channel-123")
        self.assertEqual(video["status"]["privacyStatus"], "private")

    def test_upload_record_is_upserted_by_video_id(self):
        with tempfile.TemporaryDirectory() as directory:
            first = {"video_id": "v1", "title": "first", "upload_status": "pending"}
            second = {"video_id": "v1", "title": "first", "upload_status": "verified_private"}
            path = upsert_upload_record(directory, first)
            upsert_upload_record(directory, second)
            records = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["upload_status"], "verified_private")


if __name__ == "__main__":
    unittest.main()

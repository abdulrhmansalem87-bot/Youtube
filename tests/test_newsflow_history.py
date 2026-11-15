import unittest
from pathlib import Path
from unittest.mock import patch

from newsflow.pipeline import upload_short_and_record_story


class PrivateShortHistoryTests(unittest.TestCase):
    def setUp(self):
        self.video = Path("short.mp4")
        self.story = {
            "id": "story-123",
            "title": "خبر مالي موثق",
            "link": "https://example.com/story-123",
        }
        self.tags = ["WealthRadar", "Shorts"]
        self.credentials = "test-credentials"

    def test_verified_private_short_upload_records_story_history(self):
        url = "https://youtu.be/private-short-id"
        with patch("newsflow.pipeline.youtube_upload", return_value=url) as upload, \
             patch("newsflow.pipeline.record_story_as_used") as record:
            result = upload_short_and_record_story(
                self.video, "عنوان", "وصف", self.tags,
                self.story, credentials=self.credentials,
            )
        self.assertEqual(result, url)
        upload.assert_called_once_with(
            self.video, "عنوان", "وصف", self.tags,
            privacy_override="private", credentials=self.credentials,
        )
        record.assert_called_once_with(self.story, url)

    def test_unverified_short_upload_does_not_record_story_history(self):
        with patch("newsflow.pipeline.youtube_upload", return_value=None), \
             patch("newsflow.pipeline.record_story_as_used") as record:
            result = upload_short_and_record_story(
                self.video, "عنوان", "وصف", self.tags,
                self.story, credentials=self.credentials,
            )
        self.assertIsNone(result)
        record.assert_not_called()

    def test_companion_short_does_not_overwrite_history_after_long_upload(self):
        url = "https://youtu.be/private-short-id"
        with patch("newsflow.pipeline.youtube_upload", return_value=url), \
             patch("newsflow.pipeline.record_story_as_used") as record:
            result = upload_short_and_record_story(
                self.video, "عنوان", "وصف", self.tags,
                self.story, credentials=self.credentials, record_history=False,
            )
        self.assertEqual(result, url)
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()

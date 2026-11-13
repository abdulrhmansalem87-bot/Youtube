import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from newsflow.pipeline import create_youtube_credentials
from wealthradar_shorts.pipeline import upload_private_video


OAUTH_ENV = {
    "YOUTUBE_CLIENT_ID": "test-client-id",
    "YOUTUBE_CLIENT_SECRET": "test-client-secret",
    "YOUTUBE_REFRESH_TOKEN": "test-refresh-token",
}


class YouTubeOAuthScopeTests(unittest.TestCase):
    @patch("google.oauth2.credentials.Credentials")
    def test_newsflow_channel_verification_scope_is_present(self, credentials_class):
        with patch.dict(os.environ, OAUTH_ENV):
            create_youtube_credentials()

        scopes = set(credentials_class.call_args.kwargs["scopes"])
        self.assertIn("https://www.googleapis.com/auth/youtube.upload", scopes)
        self.assertIn("https://www.googleapis.com/auth/youtube.readonly", scopes)

    @patch("google.oauth2.credentials.Credentials")
    @patch("googleapiclient.discovery.build")
    @patch("googleapiclient.http.MediaFileUpload")
    @patch("wealthradar_shorts.pipeline.validate_rendered_video")
    @patch("wealthradar_shorts.pipeline.verify_target_channel", return_value="UC-WEALTHRADAR-TEST")
    def test_shorts_private_upload_uses_channel_read_scope(
        self, verify_channel, validate_video, media_file_upload, build, credentials_class
    ):
        credentials_class.return_value.valid = True
        fake_request = MagicMock()
        fake_request.execute.return_value = {
            "id": "private-test-video-id",
            "status": {"privacyStatus": "private"},
            "snippet": {"channelId": "UC-WEALTHRADAR-TEST"},
        }
        build.return_value.videos.return_value.insert.return_value = fake_request

        with patch.dict(os.environ, OAUTH_ENV):
            upload_private_video(Path("unused.mp4"), "WealthRadar private smoke test")

        scopes = set(credentials_class.call_args.kwargs["scopes"])
        self.assertIn("https://www.googleapis.com/auth/youtube.upload", scopes)
        self.assertIn("https://www.googleapis.com/auth/youtube.readonly", scopes)
        verify_channel.assert_called_once()
        validate_video.assert_called_once()


if __name__ == "__main__":
    unittest.main()

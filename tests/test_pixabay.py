import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from newsflow import broll, pixabay
from newsflow.pipeline import append_broll_attribution

HITS = {"hits": [
    {"id": 1, "duration": 12, "pageURL": "https://pixabay.com/videos/a-1/", "user": "Ann",
     "videos": {"large": {"url": "https://cdn.pixabay.com/v1.mp4", "width": 1920, "height": 1080},
                "small": {"url": "https://cdn.pixabay.com/s1.mp4", "width": 640, "height": 360}}},
    {"id": 2, "duration": 1.0, "pageURL": "https://pixabay.com/videos/b-2/", "user": "Bo",
     "videos": {"large": {"url": "https://cdn.pixabay.com/v2.mp4", "width": 1920, "height": 1080}}},
    {"id": 3, "duration": 9, "pageURL": "https://evil.example/c", "user": "Cy",
     "videos": {"large": {"url": "https://cdn.pixabay.com/v3.mp4", "width": 1920, "height": 1080}}},
    {"id": 4, "duration": 9, "pageURL": "https://pixabay.com/videos/d-4/", "user": "Di",
     "videos": {"large": {"url": "", "width": 0, "height": 0}, "small": {"url": "https://cdn.pixabay.com/s4.mp4", "width": 640, "height": 360}}},
]}


class PixabayTests(unittest.TestCase):
    def test_search_filters_and_shapes_candidates(self):
        seen = {}
        def fake(url):
            seen["url"] = url
            return HITS
        found = pixabay.search_videos("gold bullion", "KEY", True, request_json=fake)
        self.assertEqual([c["id"] for c in found], ["pixabay-1"])
        self.assertEqual(found[0]["provider"], "Pixabay")
        self.assertEqual(found[0]["url"], "https://cdn.pixabay.com/v1.mp4")
        self.assertIn("key=KEY", seen["url"])
        self.assertTrue(seen["url"].startswith(pixabay.PIXABAY_API))

    def test_no_usable_clip_fails_closed(self):
        with self.assertRaises(RuntimeError):
            pixabay.search_videos("x", "KEY", False, request_json=lambda url: {"hits": []})

    def test_http_error_message_does_not_leak_key(self):
        err = urllib.error.HTTPError("https://pixabay.com/api/videos/?key=SECRETKEY", 403, "no", {}, None)
        with patch("newsflow.pixabay.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                pixabay._request_json("https://pixabay.com/api/videos/?key=SECRETKEY")
        self.assertNotIn("SECRETKEY", str(ctx.exception))

    def test_falls_back_to_pixabay_when_pexels_fails(self):
        good = [{"id": "pixabay-9", "url": "u", "duration": 5, "photographer": "A", "page": "https://pixabay.com/videos/z/", "provider": "Pixabay"}]
        with patch.object(broll, "_search_videos", side_effect=RuntimeError("down")), \
             patch.object(pixabay, "search_videos", return_value=good) as pb:
            out = broll._search_with_fallback("q", "PEX", "PIX", False)
        self.assertEqual(out, good)
        pb.assert_called_once()

    def test_pexels_only_failure_still_raises(self):
        with patch.object(broll, "_search_videos", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                broll._search_with_fallback("q", "PEX", "", False)

    def test_provider_env_prefers_pixabay_but_keeps_pexels_as_backup(self):
        calls = []
        with patch.object(pixabay, "search_videos", side_effect=lambda *a: calls.append("pixabay") or (_ for _ in ()).throw(RuntimeError("x"))), \
             patch.object(broll, "_search_videos", side_effect=lambda *a: calls.append("pexels") or [{"id": 1}]), \
             patch.dict("os.environ", {"NEWSFLOW_BROLL_PROVIDER": "pixabay"}):
            broll._search_with_fallback("q", "PEX", "PIX", False)
        self.assertEqual(calls, ["pixabay", "pexels"])

    def _attr(self, manifest):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "long.mp4"
            video.with_suffix(".broll-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return append_broll_attribution("وصف\n\n#WealthRadar #Egypt #Finance #Money", video)

    def test_attribution_mixed_providers(self):
        text = self._attr({"provider": "Pexels+Pixabay", "license": "Pexels License + Pixabay Content License", "sources": [
            {"provider": "Pexels", "photographer": "P", "source_page": "https://www.pexels.com/video/x/"},
            {"provider": "Pixabay", "photographer": "Q", "source_page": "https://pixabay.com/videos/y/"}]})
        self.assertIn("Pexels (Pexels License) + Pixabay (Pixabay Content License)", text)
        self.assertIn("Q / Pixabay: https://pixabay.com/videos/y/", text)

    def test_legacy_pexels_manifest_still_valid(self):
        text = self._attr({"provider": "Pexels", "license": "Pexels License", "sources": [
            {"photographer": "P", "source_page": "https://www.pexels.com/video/x/"}]})
        self.assertIn("P / Pexels: https://www.pexels.com/video/x/", text)

    def test_provider_license_mismatch_and_wrong_domain_rejected(self):
        with self.assertRaises(RuntimeError):
            self._attr({"provider": "Pixabay", "license": "Pexels License", "sources": []})
        with self.assertRaises(RuntimeError):
            self._attr({"provider": "Pixabay", "license": "Pixabay Content License", "sources": [
                {"provider": "Pixabay", "photographer": "Q", "source_page": "https://www.pexels.com/video/y/"}]})


if __name__ == "__main__":
    unittest.main()

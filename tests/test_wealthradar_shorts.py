import unittest

from urllib.error import HTTPError

from wealthradar_shorts.pipeline import (
    require_pexels_api_key,
    PEXELS_API,
    stock_footage_error,
    validate_plan,
    validate_video_probe,
    verify_target_channel,
)

def valid_plan():
    return {
        "brand": "WealthRadar",
        "title": "سرّ لا يخبرك به البنك #shorts",
        "loop_phrase": "سر البنك",
        "narration": [
            "سر البنك قد يغيّر طريقة تفكيرك.",
            "لا تنظر إلى القسط وحده.",
            "احسب الفائدة والرسوم قبل التوقيع.",
            "سر البنك قد يغيّر قرارك."
        ],
        "scenes": [
            {"duration": 2.0, "query": "modern bank vault cinematic", "caption": ["سر البنك"]},
            {"duration": 2.0, "query": "financial advisor office portrait", "caption": ["فكّر", "جيداً"]},
            {"duration": 2.0, "query": "calculator money closeup portrait", "caption": ["الفائدة", "والرسوم"]},
            {"duration": 2.0, "query": "businessman reviewing contract portrait", "caption": ["قرار مالي", "ذكي"]}
        ] * 4
    }


class WealthRadarPlanTests(unittest.TestCase):
    def test_valid_plan_has_no_errors(self):
        self.assertEqual(validate_plan(valid_plan()), [])

    def test_rejects_long_sentence(self):
        plan = valid_plan()
        plan["narration"][0] = "هذه جملة طويلة للغاية وتتجاوز الحد المسموح به من الكلمات"
        self.assertTrue(any("تتجاوز 8 كلمات" in item for item in validate_plan(plan)))

    def test_rejects_editorial_branding(self):
        plan = valid_plan()
        plan["title"] = "مسودة WealthRadar #shorts"
        self.assertTrue(any("عبارة تحريرية ممنوعة" in item for item in validate_plan(plan)))

    def test_rejects_scenes_outside_pacing(self):
        plan = valid_plan()
        plan["scenes"][0]["duration"] = 4
        self.assertTrue(any("بين 1.5 و2.5" in item for item in validate_plan(plan)))

    def test_rejects_missing_loop(self):
        plan = valid_plan()
        plan["narration"][-1] = "وهكذا تنتهي الحكاية."
        self.assertTrue(any("أول جملة وآخر جملة" in item for item in validate_plan(plan)))


class WealthRadarChannelVerificationTests(unittest.TestCase):
    def test_verifies_exact_wealthradar_channel(self):
        class Request:
            def execute(self):
                return {"items": [{"id": "UC123", "snippet": {"title": "WealthRadar"}}]}
        class Channels:
            def list(self, **kwargs):
                self.kwargs = kwargs
                return Request()
        class Service:
            def __init__(self):
                self.channel_service = Channels()
            def channels(self):
                return self.channel_service
        service = Service()
        self.assertEqual(verify_target_channel(service), "UC123")
        self.assertTrue(service.channel_service.kwargs["mine"])

    def test_refuses_wrong_channel_or_insufficient_read_scope(self):
        class Request:
            def execute(self):
                raise RuntimeError("403 insufficientPermissions")
        class Service:
            def channels(self):
                return type("Channels", (), {"list": lambda self, **kwargs: Request()})()
        with self.assertRaisesRegex(RuntimeError, "لن يتم رفع أي فيديو"):
            verify_target_channel(Service())


class WealthRadarBrollSafetyTests(unittest.TestCase):
    def test_uses_current_pexels_v1_video_search_endpoint(self):
        self.assertEqual(PEXELS_API, "https://api.pexels.com/v1/videos/search")

    def test_missing_pexels_key_blocks_rendering(self):
        with self.assertRaisesRegex(RuntimeError, "licensed B-roll"):
            require_pexels_api_key("")

    def test_http_401_explains_invalid_or_inactive_api_key(self):
        exc = HTTPError("https://api.pexels.com/v1/videos/search", 401, "Unauthorized", None, None)
        error = stock_footage_error(3, exc)
        self.assertIn("HTTP 401", str(error))
        self.assertIn("PEXELS_API_KEY", str(error))
        self.assertIn("الخلفيات الثابتة غير مسموح بها", str(error))

    def test_http_403_explains_account_or_key_restrictions(self):
        exc = HTTPError("https://api.pexels.com/videos/search", 403, "Forbidden", None, None)
        error = stock_footage_error(1, exc)
        self.assertIn("HTTP 403", str(error))
        self.assertIn("قيود المفتاح", str(error))
        self.assertIn("لا يمكن تجاوز الرفض برمجياً", str(error))


class WealthRadarRenderedVideoTests(unittest.TestCase):
    def valid_probe(self):
        return {
            "format": {"duration": "39.8"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"}
            ]
        }

    def test_accepts_valid_short_mp4_metadata(self):
        validate_video_probe(self.valid_probe())

    def test_rejects_missing_audio(self):
        metadata = self.valid_probe()
        metadata["streams"] = metadata["streams"][:1]
        with self.assertRaisesRegex(RuntimeError, "لا يوجد مسار صوت"):
            validate_video_probe(metadata)

    def test_rejects_wrong_video_dimensions(self):
        metadata = self.valid_probe()
        metadata["streams"][0]["height"] = 1080
        with self.assertRaisesRegex(RuntimeError, "1080x1920"):
            validate_video_probe(metadata)

    def test_rejects_duration_outside_shorts_range(self):
        metadata = self.valid_probe()
        metadata["format"]["duration"] = "67.5"
        with self.assertRaisesRegex(RuntimeError, "خارج 30–45"):
            validate_video_probe(metadata)



if __name__ == "__main__":
    unittest.main()

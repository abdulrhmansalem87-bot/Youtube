import unittest

from wealthradar_shorts.pipeline import validate_plan


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
            {"duration": 2.0, "query": "financial advisor office portrait", "caption": ["فكّر جيداً", "قبل التوقيع"]},
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


if __name__ == "__main__":
    unittest.main()

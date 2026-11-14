import unittest

from newsflow.broll import MAX_SCENE_SECONDS, clean_visual_text, require_api_key, split_scene_durations, _english_query


class BrollPlanningTests(unittest.TestCase):
    def test_long_audio_is_split_into_short_moving_shots(self):
        plan = split_scene_durations([12.0, 7.0, 2.0])
        self.assertTrue(all(seconds <= MAX_SCENE_SECONDS for _, seconds in plan))
        self.assertEqual(sum(seconds for _, seconds in plan), 21.0)
        self.assertEqual([index for index, _ in plan].count(0), 5)
        self.assertEqual([index for index, _ in plan].count(1), 3)

    def test_scene_split_preserves_source_card_order(self):
        plan = split_scene_durations([5.0, 3.0])
        self.assertEqual([index for index, _ in plan], [0, 0, 1, 1])

    def test_long_fractional_scenes_do_not_accumulate_rounding_overflow(self):
        for duration in (182.38164302254532, 232.501, 317.5):
            with self.subTest(duration=duration):
                plan = split_scene_durations([duration])
                self.assertTrue(all(seconds <= MAX_SCENE_SECONDS for _, seconds in plan))
                self.assertAlmostEqual(sum(seconds for _, seconds in plan), duration, places=3)

    def test_invalid_scene_durations_are_rejected(self):
        for values in ([], [0], [-1], [float("nan")]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    split_scene_durations(values)

    def test_visual_text_removes_invisible_directional_and_control_marks(self):
        self.assertEqual(clean_visual_text("إنفيديا\u2066 80%\u2069"), "إنفيديا 80%")
        self.assertEqual(clean_visual_text("  خبر\u200f   مالي  "), "خبر مالي")

    def test_broll_queries_match_specific_story_subjects(self):
        self.assertEqual(_english_query({"title": "إنفيديا والذكاء الاصطناعي", "body": ""}),
                         "semiconductor chip manufacturing data center")
        self.assertEqual(_english_query({"title": "باينانس واختراق العملات المشفرة", "body": ""}),
                         "cryptocurrency cybersecurity bitcoin")
        self.assertEqual(_english_query({"title": "الاستحواذ على شركة بناء السفن ماير فيرفت", "body": ""}),
                         "shipbuilding shipyard industrial")

    def test_missing_pexels_key_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "PEXELS_API_KEY"):
            require_api_key("")


if __name__ == "__main__":
    unittest.main()

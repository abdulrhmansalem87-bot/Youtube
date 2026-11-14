import unittest

from newsflow.broll import MAX_SCENE_SECONDS, require_api_key, split_scene_durations


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

    def test_invalid_scene_durations_are_rejected(self):
        for values in ([], [0], [-1], [float("nan")]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    split_scene_durations(values)

    def test_missing_pexels_key_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "PEXELS_API_KEY"):
            require_api_key("")


if __name__ == "__main__":
    unittest.main()

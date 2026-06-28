import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "follow_heal_navigation",
    ROOT / "utils" / "follow_heal_navigation.py",
)
NAVIGATION_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NAVIGATION_MODULE)
direction_for_center_adjustment = NAVIGATION_MODULE.direction_for_center_adjustment
direction_to_base = NAVIGATION_MODULE.direction_to_base
is_outside_anchor_band = NAVIGATION_MODULE.is_outside_anchor_band
next_center_adjust_interval = NAVIGATION_MODULE.next_center_adjust_interval


class FollowHealNavigationTests(unittest.TestCase):
    def test_direction_to_base_matches_anchor_center(self):
        self.assertEqual(direction_to_base(104, 100), "left")
        self.assertEqual(direction_to_base(96, 100), "right")
        self.assertIsNone(direction_to_base(102.5, 100))

    def test_anchor_band_allows_plus_minus_seven(self):
        self.assertFalse(is_outside_anchor_band(106.5, 100))
        self.assertFalse(is_outside_anchor_band(93.5, 100))
        self.assertFalse(is_outside_anchor_band(107, 100))
        self.assertFalse(is_outside_anchor_band(93, 100))
        self.assertTrue(is_outside_anchor_band(107.5, 100))

    def test_center_adjust_moves_toward_base_or_right_when_centered(self):
        self.assertEqual(direction_for_center_adjustment(104, 100), "left")
        self.assertEqual(direction_for_center_adjustment(96, 100), "right")
        self.assertEqual(direction_for_center_adjustment(102.5, 100), "right")

    def test_center_adjust_interval_is_frequent(self):
        for _ in range(20):
            interval = next_center_adjust_interval()
            self.assertGreaterEqual(interval, 12)
            self.assertLessEqual(interval, 15)


if __name__ == "__main__":
    unittest.main()

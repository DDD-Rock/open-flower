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
is_outside_anchor_band = NAVIGATION_MODULE.is_outside_anchor_band
next_center_adjust_interval = NAVIGATION_MODULE.next_center_adjust_interval
teleport_direction_to_base = NAVIGATION_MODULE.teleport_direction_to_base


class FollowHealNavigationTests(unittest.TestCase):
    def test_teleport_always_points_toward_exact_anchor(self):
        self.assertEqual(teleport_direction_to_base(104, 100), "left")
        self.assertEqual(teleport_direction_to_base(96, 100), "right")
        self.assertIsNone(teleport_direction_to_base(100, 100))

    def test_anchor_band_uses_configured_tolerance(self):
        self.assertFalse(is_outside_anchor_band(109.5, 100, 9.5))
        self.assertFalse(is_outside_anchor_band(90.5, 100, 9.5))
        self.assertTrue(is_outside_anchor_band(109.6, 100, 9.5))
        self.assertTrue(is_outside_anchor_band(90.4, 100, 9.5))

    def test_center_adjust_interval_is_frequent(self):
        for _ in range(20):
            interval = next_center_adjust_interval()
            self.assertGreaterEqual(interval, 10)
            self.assertLessEqual(interval, 13)


if __name__ == "__main__":
    unittest.main()

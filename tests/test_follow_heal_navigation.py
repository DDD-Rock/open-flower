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
TeleportExcursionGuard = NAVIGATION_MODULE.TeleportExcursionGuard
updated_center_adjust_deadline = NAVIGATION_MODULE.updated_center_adjust_deadline


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
            self.assertGreaterEqual(interval, 4)
            self.assertLessEqual(interval, 7)

    def test_collision_correction_does_not_reset_scheduled_adjustment(self):
        self.assertEqual(
            updated_center_adjust_deadline(105.0, 102.0, False),
            105.0,
        )

    def test_scheduled_adjustment_advances_its_own_deadline(self):
        deadline = updated_center_adjust_deadline(100.0, 102.0, True)
        self.assertGreaterEqual(deadline, 106.0)
        self.assertLessEqual(deadline, 109.0)

    def test_heal_hold_and_gap_ranges_match_follow_policy(self):
        self.assertEqual(NAVIGATION_MODULE.HEAL_HOLD_RANGE, (8.0, 12.0))
        self.assertEqual(NAVIGATION_MODULE.HEAL_GAP_RANGE, (0.25, 0.60))

    def test_new_excursion_is_corrected_immediately(self):
        guard = TeleportExcursionGuard()

        self.assertTrue(guard.should_correct(108, 100, 6))

    def test_crossing_anchor_does_not_immediately_reverse(self):
        guard = TeleportExcursionGuard()
        guard.record_teleport("right")

        self.assertFalse(guard.should_correct(108, 100, 6))
        self.assertFalse(guard.should_correct(108.5, 100, 6))

    def test_new_collision_breaks_reverse_guard_immediately(self):
        guard = TeleportExcursionGuard()
        guard.record_teleport("right")
        self.assertFalse(guard.should_correct(108, 100, 6))

        self.assertTrue(guard.should_correct(109.1, 100, 6))

    def test_same_direction_can_retry_after_marker_settles(self):
        guard = TeleportExcursionGuard()
        guard.record_teleport("right")

        self.assertTrue(guard.should_correct(92, 100, 6))

    def test_returning_inside_resets_reverse_guard(self):
        guard = TeleportExcursionGuard()
        guard.record_teleport("right")
        self.assertFalse(guard.should_correct(108, 100, 6))
        self.assertFalse(guard.should_correct(104, 100, 6))

        self.assertTrue(guard.should_correct(108, 100, 6))


if __name__ == "__main__":
    unittest.main()

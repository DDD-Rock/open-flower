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
protective_anchor_tolerance = NAVIGATION_MODULE.protective_anchor_tolerance
requires_immediate_left_recovery = NAVIGATION_MODULE.requires_immediate_left_recovery
is_near_anchor = NAVIGATION_MODULE.is_near_anchor
outward_teleport_direction = NAVIGATION_MODULE.outward_teleport_direction
opposite_direction = NAVIGATION_MODULE.opposite_direction
opposite_walking_direction = NAVIGATION_MODULE.opposite_walking_direction
walking_direction_to_base = NAVIGATION_MODULE.walking_direction_to_base
is_outside_walking_boundary = NAVIGATION_MODULE.is_outside_walking_boundary
next_walking_keepalive_interval = NAVIGATION_MODULE.next_walking_keepalive_interval


class FollowHealNavigationTests(unittest.TestCase):
    def test_teleport_always_points_toward_exact_anchor(self):
        self.assertEqual(teleport_direction_to_base(104, 100), "left")
        self.assertEqual(teleport_direction_to_base(96, 100), "right")
        self.assertIsNone(teleport_direction_to_base(100, 100))

    def test_walking_plan_has_independent_direction_and_boundary_rules(self):
        self.assertEqual(walking_direction_to_base(104, 100), "left")
        self.assertEqual(walking_direction_to_base(96, 100), "right")
        self.assertIsNone(walking_direction_to_base(100, 100))
        self.assertEqual(opposite_walking_direction("left"), "right")
        self.assertEqual(opposite_walking_direction("right"), "left")
        self.assertFalse(is_outside_walking_boundary(106, 100, 6))
        self.assertTrue(is_outside_walking_boundary(106.1, 100, 6))

    def test_walking_keepalive_uses_historical_timing(self):
        self.assertEqual(
            NAVIGATION_MODULE.WALKING_KEEPALIVE_FIRST_STEP_RANGE,
            (0.18, 0.24),
        )
        self.assertEqual(
            NAVIGATION_MODULE.WALKING_KEEPALIVE_SECOND_STEP_REDUCTION_RANGE,
            (0.03, 0.05),
        )
        self.assertEqual(NAVIGATION_MODULE.WALKING_RECOVERY_MAXIMUM_ATTEMPTS, 3)
        for _ in range(20):
            interval = next_walking_keepalive_interval()
            self.assertGreaterEqual(interval, 5)
            self.assertLessEqual(interval, 8)

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

    def test_protective_boundary_triggers_before_hard_boundary(self):
        self.assertEqual(protective_anchor_tolerance(6), 4.5)
        self.assertEqual(protective_anchor_tolerance(10), 7.5)

    def test_left_protective_boundary_forces_immediate_recovery(self):
        self.assertTrue(requires_immediate_left_recovery(93.9, 100, 6))
        self.assertTrue(requires_immediate_left_recovery(94, 100, 6))
        self.assertFalse(requires_immediate_left_recovery(108, 100, 6))

    def test_left_risk_bypasses_reverse_teleport_guard(self):
        guard = TeleportExcursionGuard()
        guard.record_teleport("left")

        self.assertTrue(
            guard.should_correct(
                95.5,
                100,
                4.5,
                priority_left_recovery_tolerance=4.5,
            )
        )

    def test_near_anchor_excursion_uses_half_boundary(self):
        self.assertTrue(is_near_anchor(101.9, 100, 4))
        self.assertTrue(is_near_anchor(102, 100, 4))
        self.assertFalse(is_near_anchor(102.1, 100, 4))

    def test_near_anchor_excursion_points_away_then_back(self):
        self.assertEqual(outward_teleport_direction(99, 100), "left")
        self.assertEqual(outward_teleport_direction(101, 100), "right")
        self.assertEqual(opposite_direction("left"), "right")
        self.assertEqual(opposite_direction("right"), "left")

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

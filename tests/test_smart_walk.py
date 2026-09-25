import unittest

from utils.smart_walk import (
    next_smart_walk_deadline,
    normalize_interval_range,
    smart_walk_can_continue,
    smart_walk_direction,
)


class SmartWalkTests(unittest.TestCase):
    def test_direction_always_points_toward_center(self):
        self.assertEqual(smart_walk_direction(40, 50), "right")
        self.assertEqual(smart_walk_direction(60, 50), "left")
        self.assertEqual(smart_walk_direction(50, 50), "left")

    def test_walk_crosses_center_but_stops_at_selected_boundaries(self):
        self.assertTrue(smart_walk_can_continue("right", 40, 50, 6))
        self.assertTrue(smart_walk_can_continue("right", 50, 50, 6))
        self.assertTrue(smart_walk_can_continue("right", 55, 50, 6))
        self.assertFalse(smart_walk_can_continue("right", 56, 50, 6))
        self.assertFalse(smart_walk_can_continue("right", 57, 50, 6))
        self.assertTrue(smart_walk_can_continue("left", 60, 50, 6))
        self.assertTrue(smart_walk_can_continue("left", 50, 50, 6))
        self.assertTrue(smart_walk_can_continue("left", 45, 50, 6))
        self.assertFalse(smart_walk_can_continue("left", 44, 50, 6))
        self.assertFalse(smart_walk_can_continue("left", 43, 50, 6))

    def test_deadline_uses_configured_random_minute_range(self):
        chosen = []

        def choose(minimum, maximum):
            chosen.append((minimum, maximum))
            return 22.5

        deadline = next_smart_walk_deadline(100.0, 15, 30, choose=choose)

        self.assertEqual(chosen, [(15.0, 30.0)])
        self.assertEqual(deadline, 100.0 + 22.5 * 60.0)

    def test_invalid_interval_order_is_normalized(self):
        self.assertEqual(normalize_interval_range(30, 15), (30, 30))
        self.assertEqual(normalize_interval_range(0, 2000), (1, 1440))


if __name__ == "__main__":
    unittest.main()

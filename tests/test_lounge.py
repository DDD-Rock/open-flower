import importlib.util
import sys
import unittest
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "utils" / "lounge.py"
spec = importlib.util.spec_from_file_location("lounge_test_helper", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
LoungeMarkerCounts = module.LoungeMarkerCounts
LoungePopulationTracker = module.LoungePopulationTracker


class LoungePopulationTrackerTests(unittest.TestCase):
    def test_requires_two_frames_and_ignores_initial_baseline(self):
        tracker = LoungePopulationTracker()
        one = LoungeMarkerCounts(1, 0)
        two = LoungeMarkerCounts(1, 1)
        self.assertIsNone(tracker.observe(one))
        self.assertIsNone(tracker.observe(one))
        self.assertIsNone(tracker.observe(two))
        change = tracker.observe(two)
        self.assertIsNotNone(change)
        self.assertTrue(change.increased)

    def test_decrease_then_same_count_increase_triggers_again(self):
        tracker = LoungePopulationTracker()
        three = LoungeMarkerCounts(1, 2)
        two = LoungeMarkerCounts(1, 1)
        for value in (three, three, two, two):
            tracker.observe(value)
        self.assertIsNone(tracker.observe(three))
        change = tracker.observe(three)
        self.assertTrue(change.increased)

    def test_single_dropped_frame_does_not_change_baseline(self):
        tracker = LoungePopulationTracker()
        normal = LoungeMarkerCounts(1, 2)
        dropped = LoungeMarkerCounts(0, 1)
        tracker.observe(normal)
        tracker.observe(normal)
        self.assertIsNone(tracker.observe(dropped))
        self.assertIsNone(tracker.observe(normal))
        self.assertEqual(tracker.baseline, normal)


if __name__ == "__main__":
    unittest.main()

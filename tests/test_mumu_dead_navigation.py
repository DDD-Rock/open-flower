"""Navigation timing checks with occlusion, frozen maps, and interrupted holds."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from workers.mumu_dead_flower_worker import MumuDeadFlowerWorker


class Clock:
    def __init__(self):
        self.now = 100.0
        self.stopped = False
        self.stop_at = None

    def wait(self, seconds):
        self.now += seconds
        if self.stop_at is not None and self.now >= self.stop_at:
            self.stopped = True
        return self.stopped

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


class DeadNavigationTests(unittest.TestCase):
    def worker(self):
        worker = MumuDeadFlowerWorker("test", "adb", Mock(), snapshot_provider=Mock())
        clock = Clock()
        worker._stop = clock
        worker._get_window_handle = Mock(return_value=99)
        worker._virtual_key = lambda key: key
        worker._post_key = Mock()
        worker._navigation_ground_y = 75
        worker._walk_speeds = {"left": 10, "right": 10}
        return worker, clock

    def observation(self, clock, position, sequence=None):
        return ({"frame_sequence": int((clock.now - 100) * 1000) if sequence is None else sequence},
                SimpleNamespace(player_position=position))

    def test_occluded_path_is_one_continuous_hold_for_remaining_travel_time(self):
        worker, clock = self.worker()
        worker._navigation_observation = lambda: self.observation(clock, None)
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertEqual(worker._walk_to_portal((20, 75), (40, 75)), "estimated")
        self.assertAlmostEqual(clock.now - 100, 1.95, delta=0.03)
        self.assertEqual([c.args for c in worker._post_key.call_args_list],
                         [(99, "Left", True), (99, "Left", False)])
        self.assertTrue(worker._verify_portal_position)

    def test_frozen_minimap_does_not_extend_press_forever(self):
        for same_sequence in (False, True):
            worker, clock = self.worker()
            worker._navigation_observation = lambda: self.observation(clock, (40, 75), 1 if same_sequence else None)
            with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
                self.assertEqual(worker._walk_to_portal((20, 75), (40, 75)), "estimated")
            self.assertLess(clock.now - 100, 2.0)
            self.assertEqual(worker._post_key.call_count, 2)

    def test_visible_portal_dot_releases_key_before_estimated_deadline(self):
        worker, clock = self.worker()
        worker._navigation_observation = lambda: self.observation(clock, (40 - round((clock.now - 100) * 10), 75))
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertEqual(worker._walk_to_portal((20, 75), (40, 75)), "observed")
        self.assertFalse(worker._verify_portal_position)
        self.assertEqual(worker._post_key.call_args.args, (99, "Left", False))

    def test_lost_video_releases_direction_immediately(self):
        worker, clock = self.worker()
        worker._navigation_observation = Mock(return_value=None)
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertEqual(worker._walk_to_portal((20, 75), (40, 75)), "unavailable")
        self.assertEqual(clock.now, 100)
        self.assertEqual(worker._post_key.call_args.args, (99, "Left", False))

    def test_stop_and_analysis_exception_both_release_held_key(self):
        worker, clock = self.worker()
        clock.stop_at = 100.2
        worker._navigation_observation = lambda: self.observation(clock, None)
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertEqual(worker._walk_to_portal((20, 75), (40, 75)), "stopped")
        self.assertLess(clock.now, 100.3)
        self.assertEqual(worker._post_key.call_args.args, (99, "Left", False))
        clock.stopped = False
        worker._navigation_observation = Mock(side_effect=RuntimeError("decode error"))
        with self.assertRaises(RuntimeError):
            worker._walk_to_portal((20, 75), (40, 75))
        self.assertEqual(worker._post_key.call_args.args, (99, "Left", False))

    def test_jump_stays_held_through_frozen_frames_until_vertical_motion_then_lands(self):
        worker, clock = self.worker()
        release_times = []
        worker._post_key.side_effect = lambda hwnd, key, down: release_times.append((down, clock.now))

        def observation():
            elapsed = clock.now - 100
            point = (40, 65) if elapsed < 1 else (40, 62)
            return self.observation(clock, point)

        worker._navigation_observation = observation
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertIsNotNone(worker._find_position_with_jump())
        self.assertGreaterEqual(release_times[1][1] - release_times[0][1], 1)
        self.assertGreaterEqual(clock.now - release_times[1][1], 0.8)
        self.assertEqual([c.args for c in worker._post_key.call_args_list],
                         [(99, "Alt", True), (99, "Alt", False)])

    def test_repeated_frame_cannot_establish_jumping_dot(self):
        worker, clock = self.worker()
        worker.POSITION_SEARCH_SECONDS = 0.3
        worker._navigation_observation = lambda: self.observation(clock, (40, 65 if clock.now < 100.1 else 62), 1)
        with patch("workers.mumu_dead_flower_worker.time.monotonic", lambda: clock.now):
            self.assertIsNone(worker._find_position_with_jump())
        self.assertEqual(worker._post_key.call_args.args, (99, "Alt", False))

    def test_estimated_arrival_requires_jump_confirmation_before_up(self):
        worker, clock = self.worker()
        worker._verify_portal_position = True
        worker._navigation_observation = lambda: self.observation(clock, (20, 75))
        worker._find_position_with_jump = Mock(return_value=None)
        worker._press_key = Mock()
        worker._leave_step({"portal_anchor": (20, 75)})
        worker._find_position_with_jump.assert_called_once()
        worker._press_key.assert_not_called()
        worker._find_position_with_jump.return_value = (24, 63)
        worker._walk_to_portal = Mock(return_value="estimated")
        worker._leave_step({"portal_anchor": (20, 75)})
        worker._walk_to_portal.assert_called_once_with((20, 75), (24, 63))
        worker._press_key.assert_not_called()

    def test_speed_uses_each_instances_own_observations(self):
        worker, _ = self.worker()
        worker._learn_walk_speed("left", [(0, 40), (0.5, 34), (1, 28)])
        self.assertAlmostEqual(worker._walk_speeds["left"], 12)
        self.assertEqual(worker._walk_speeds["right"], 10)
        other, _ = self.worker()
        self.assertEqual(other._walk_speeds["left"], 10)

    def test_overshoot_after_key_release_repositions_instead_of_pressing_up(self):
        worker, clock = self.worker()
        worker._navigation_observation = lambda: self.observation(clock, (18, 75))
        worker._press_key = Mock()
        worker._enter_portal((22, 75))
        worker._press_key.assert_not_called()
        self.assertTrue(worker._verify_portal_position)

    def test_confirmed_jump_x_can_enter_when_dot_is_hidden_again_at_rest(self):
        worker, clock = self.worker()
        worker._navigation_observation = lambda: self.observation(clock, None)
        worker._press_key = Mock(return_value=True)
        worker._enter_portal((22, 75), confirmed_x=22)
        worker._press_key.assert_called_once_with("Up", (180, 260))
        self.assertEqual(worker._phase, "leaving")


if __name__ == "__main__":
    unittest.main()

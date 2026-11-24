import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication
from pynput.keyboard import Key

from models.map_topology import MapPlatform, MapTopology, NormalizedMapPoint
from ui.taunt_panel import TauntPanel
from ui.modern_main_window import MainWindow
from utils.account_manager import AccountManager
from utils.settings_manager import SettingsManager
from workers.taunt_worker import TauntWorker


def make_map(name="乌鲁庄园2", left=0.1, right=0.9):
    return MapTopology(name, 200, 100, platforms=[MapPlatform([
        NormalizedMapPoint(right, 0.8), NormalizedMapPoint(left, 0.2),
    ])])


class TauntMovementTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.controller = self.patches.enter_context(patch("workers.taunt_worker.Controller"))
        self.monitor_type = self.patches.enter_context(patch("workers.taunt_worker.MinimapMonitor"))
        self.clock = self.patches.enter_context(patch("workers.taunt_worker.time.monotonic", return_value=10.0))
        self.topology = make_map()
        self.selector = Mock()
        self.worker = TauntWorker(101, self.topology, self.topology.platforms[0].id,
                                  jump_key="Space", window_selector=self.selector)
        self.addCleanup(self.worker.stop)
        self.keyboard = self.controller.return_value
        self.monitor = self.monitor_type.return_value
        self.monitor.capture_minimap.return_value = np.zeros((100, 200, 3), dtype=np.uint8)
        self.worker._wait = Mock(return_value=True)

    def run_at_frame_times(self, times):
        times = iter(times)
        def capture():
            self.clock.return_value = next(times)
            return self.monitor.capture_minimap.return_value
        self.monitor.capture_minimap.side_effect = capture
        self.worker.run()

    def test_holds_direction_then_jump_without_repeated_presses_or_releases(self):
        for _ in range(20):
            self.worker._hold_movement("right")

        self.assertEqual(self.keyboard.method_calls, [call.press(Key.right), call.press(Key.space)])

    def test_turn_releases_both_keys_then_presses_the_opposite_direction_and_jump(self):
        self.worker._hold_movement("right")
        self.keyboard.reset_mock()
        with patch.object(self.worker, "_wait_for_input", wraps=self.worker._wait_for_input) as wait_input:
            self.worker._hold_movement("left")

        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space),
            call.press(Key.left), call.press(Key.space),
        ])
        delays = [args.args[0] for args in wait_input.call_args_list]
        self.assertTrue(any(0.05 <= delay <= 0.10 for delay in delays))

    def test_crossing_the_midpoint_does_not_turn_until_near_the_boundary(self):
        self.worker.direction = "right"
        self.assertEqual(self.worker._next_direction(0.3, 200), "right")
        self.assertEqual(self.worker._next_direction(0.8, 200), "right")
        self.assertEqual(self.worker._next_direction(0.89, 200), "left")
        self.worker.direction = "left"
        self.assertEqual(self.worker._next_direction(0.5, 200), "left")
        self.assertEqual(self.worker._next_direction(0.11, 200), "right")

    def test_turns_inside_the_platform_before_reaching_the_corners(self):
        self.worker.direction = "right"
        self.assertEqual(self.worker._next_direction(0.83, 200), "right")
        self.assertEqual(self.worker._next_direction(0.84, 200), "left")
        self.worker.direction = "left"
        self.assertEqual(self.worker._next_direction(0.17, 200), "left")
        self.assertEqual(self.worker._next_direction(0.16, 200), "right")

    def test_turning_range_scales_with_the_map_and_keeps_narrow_platforms_open(self):
        for width in (100, 200, 400):
            left, right = self.worker._turn_bounds(width)
            self.assertAlmostEqual(left, 0.164)
            self.assertAlmostEqual(right, 0.836)
        self.worker.left, self.worker.right = 0.1, 0.12
        left, right = self.worker._turn_bounds(200)
        self.assertTrue(0.1 < left < right < 0.12)

    def test_starting_outside_the_platform_moves_toward_its_horizontal_range(self):
        self.assertEqual(self.worker._next_direction(0.01, 200), "right")
        self.assertEqual(self.worker._next_direction(0.99, 200), "left")

    def test_stop_during_turn_never_presses_the_new_direction(self):
        self.worker._hold_movement("right")
        self.keyboard.reset_mock()

        def stop_during_wait(_seconds):
            self.worker.stop()
            return False

        self.worker._wait.side_effect = stop_during_wait
        self.worker._hold_movement("left")

        self.keyboard.press.assert_not_called()
        self.keyboard.release.assert_any_call(Key.right)
        self.keyboard.release.assert_any_call(Key.space)

    def test_stop_between_direction_and_jump_releases_direction_and_does_not_jump(self):
        self.worker._wait.side_effect = lambda _: (self.worker.stop() or False)

        self.worker._hold_movement("right")

        self.assertEqual(self.keyboard.method_calls, [call.press(Key.right), call.release(Key.right)])

    def test_main_loop_ignores_y_and_preserves_the_hold_across_frames(self):
        positions = [(60, 10), (120, 95), (160, 40), (178, 1), (120, 99), (22, 50)]
        self.monitor_type.find_player_position_in_image.side_effect = [(point, "") for point in positions]
        updates = []

        def position(x, direction):
            updates.append((x, direction))
            if len(updates) == len(positions):
                self.worker._stop_event.set()

        self.worker.position_update.connect(position)
        self.worker.run()

        self.assertEqual([item[1] for item in updates], ["right", "right", "right", "left", "left", "right"])
        self.assertEqual(self.keyboard.press.call_args_list, [
            call(Key.right), call(Key.space), call(Key.left), call(Key.space),
            call(Key.right), call(Key.space),
        ])
        self.assertIsNone(self.worker._held_direction)
        self.assertFalse(self.worker._jump_held)
        self.monitor.close_capture.assert_called_once_with()

    def test_two_seconds_without_horizontal_movement_releases_then_restarts_jump_walk(self):
        positions = [(60, 20), (60, 40), (60, 10)]
        self.monitor_type.find_player_position_in_image.side_effect = [(point, "") for point in positions]
        updates, messages, errors = [], [], []
        self.worker.log_update.connect(messages.append)
        self.worker.error_signal.connect(errors.append)
        def position(*_):
            updates.append(True)
            if len(updates) == len(positions):
                self.worker._stop_event.set()
        self.worker.position_update.connect(position)
        self.run_at_frame_times([0.0, 1.999, 2.0])
        self.assertEqual(errors, [])
        self.assertEqual(sum("连续 2 秒未移动" in message for message in messages), 1)
        self.assertEqual(self.keyboard.method_calls, [
            call.press(Key.right), call.press(Key.space),
            call.release(Key.space), call.release(Key.right),
            call.press(Key.right), call.press(Key.space),
            call.release(Key.right), call.release(Key.space),
        ])

    def test_stuck_detection_tolerates_one_pixel_jitter_and_resets_on_cumulative_movement(self):
        self.worker._hold_movement("right")
        with patch("workers.taunt_worker.time.monotonic") as now:
            now.return_value = 0.0
            self.assertFalse(self.worker._movement_stalled(0.3, 200))
            now.return_value = 1.0
            self.assertFalse(self.worker._movement_stalled(0.303, 200))
            now.return_value = 1.9
            self.assertFalse(self.worker._movement_stalled(0.306, 200))
            now.return_value = 2.1
            self.assertFalse(self.worker._movement_stalled(0.311, 200))
            now.return_value = 3.901
            self.assertTrue(self.worker._movement_stalled(0.301, 200))

    def test_resizing_does_not_reset_the_stuck_timer_for_the_same_relative_position(self):
        self.worker._hold_movement("right")
        with patch("workers.taunt_worker.time.monotonic", side_effect=[0.0, 1.99, 2.0]):
            self.assertFalse(self.worker._movement_stalled(0.3, 200))
            self.assertFalse(self.worker._movement_stalled(0.3, 400))
            self.assertTrue(self.worker._movement_stalled(0.3, 400))

    def test_remaining_stuck_retries_only_after_a_new_two_second_window(self):
        self.monitor_type.find_player_position_in_image.return_value = ((60, 20), "")
        updates, messages = [], []
        self.worker.log_update.connect(messages.append)
        def position(*_):
            updates.append(True)
            if len(updates) == 5:
                self.worker._stop_event.set()
        self.worker.position_update.connect(position)
        self.run_at_frame_times([0.0, 2.0, 2.1, 4.099, 4.101])
        self.assertEqual(sum("连续 2 秒未移动" in message for message in messages), 2)
        self.assertEqual(self.keyboard.press.call_args_list,
                         [call(Key.right), call(Key.space)] * 3)

    def test_a_missing_marker_pauses_stuck_tracking_until_detection_recovers(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), ((60, 20), ""), (None, ""), ((60, 20), ""),
        ]
        updates, messages, errors = [], [], []
        self.worker.log_update.connect(messages.append)
        self.worker.error_signal.connect(errors.append)
        def position(*_):
            updates.append(True)
            if len(updates) == 3:
                self.worker._stop_event.set()
        self.worker.position_update.connect(position)
        self.run_at_frame_times([0.0, 1.9, 1.95, 100.0])
        self.assertEqual(errors, [])
        self.assertFalse(any("连续 2 秒未移动" in message for message in messages))
        self.assertEqual(self.keyboard.press.call_args_list, [call(Key.right), call(Key.space)])

    def test_brief_marker_flicker_does_not_prevent_two_seconds_of_stillness_from_triggering(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), ((60, 20), ""), (None, ""),
            ((60, 20), ""), ((60, 20), ""), ((60, 20), ""),
        ]
        updates, messages, errors = [], [], []
        self.worker.log_update.connect(messages.append)
        self.worker.error_signal.connect(errors.append)
        def position(*_):
            updates.append(True)
            if len(updates) < 5:
                self.assertFalse(any("连续 2 秒未移动" in message for message in messages))
            else:
                self.worker._stop_event.set()
        self.worker.position_update.connect(position)
        self.run_at_frame_times([0.0, 1.90, 1.95, 1.99, 2.03, 2.05])
        self.assertEqual(errors, [])
        self.assertEqual(sum("连续 2 秒未移动" in message for message in messages), 1)
        self.assertEqual(self.keyboard.press.call_args_list, [call(Key.right), call(Key.space)] * 2)

    def test_focus_loss_clears_the_stuck_timer(self):
        self.worker._hold_movement("right")
        with patch("workers.taunt_worker.time.monotonic", return_value=0.0):
            self.assertFalse(self.worker._movement_stalled(0.3, 200))
        self.selector.is_window_foreground.return_value = False
        self.assertFalse(self.worker._input_allowed())
        self.assertIsNone(self.worker._movement_since)
        self.assertIsNone(self.worker._movement_anchor_x)
        with patch("workers.taunt_worker.time.monotonic", return_value=100.0):
            self.assertFalse(self.worker._movement_stalled(0.3, 200))

    def test_brief_marker_flicker_does_not_interrupt_continuous_movement(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), (None, ""), ((120, 95), ""),
        ]
        frames = []
        self.worker.position_update.connect(lambda *_: frames.append(True))
        messages = []
        self.worker.log_update.connect(messages.append)

        def wait(_):
            if len(frames) == 2:
                self.worker._stop_event.set()
            return True

        self.worker._wait.side_effect = wait
        self.worker.run()

        self.assertNotIn("未识别到玩家黄点，已松键等待重新定位", messages)
        self.assertEqual(self.keyboard.press.call_args_list, [call(Key.right), call(Key.space)])

    def test_sustained_marker_loss_keeps_moving_and_turns_when_detection_recovers(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), (None, ""), (None, ""), (None, ""),
            ((178, 20), ""),
        ]
        messages, errors, positions = [], [], []
        self.worker.log_update.connect(messages.append)
        self.worker.error_signal.connect(errors.append)
        def position(x, direction):
            positions.append((x, direction))
            if len(positions) == 2:
                self.worker._stop_event.set()
        def wait(_):
            if 2 <= self.monitor_type.find_player_position_in_image.call_count <= 4:
                self.assertEqual(self.worker._held_direction, Key.right)
                self.assertNotIn(call(Key.right), self.keyboard.release.call_args_list)
            return True
        self.worker.position_update.connect(position)
        self.worker._wait.side_effect = wait
        self.run_at_frame_times([0.0, 1.0, 1.2, 60.0, 60.1])
        self.assertEqual(errors, [])
        self.assertEqual(positions, [(60.0, "right"), (178.0, "left")])
        self.assertEqual(sum("沿用原方向" in message for message in messages), 1)
        self.assertEqual(self.keyboard.press.call_args_list.count(call(Key.right)), 1)
        self.assertEqual(self.keyboard.press.call_args_list.count(call(Key.left)), 1)

    def test_marker_loss_near_the_boundary_keeps_the_same_direction(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), ((165, 20), ""), (None, ""),
        ]
        def wait(_):
            if self.monitor_type.find_player_position_in_image.call_count == 3:
                self.keyboard.release.assert_not_called()
                self.assertEqual(self.worker._held_direction, Key.right)
                self.worker._stop_event.set()
            return True
        self.worker._wait.side_effect = wait
        self.worker.run()
        self.assertEqual(self.keyboard.method_calls, [
            call.press(Key.right), call.press(Key.space),
            call.release(Key.right), call.release(Key.space),
        ])

    def test_initial_marker_loss_waits_without_guessing_a_direction(self):
        self.monitor_type.find_player_position_in_image.return_value = (None, "")
        errors = []
        self.worker.error_signal.connect(errors.append)
        self.run_at_frame_times([0.0, 5.1])
        self.keyboard.press.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assertIn("初始定位", errors[0])

    def test_marker_loss_still_casts_due_buffs_and_resumes_the_same_direction(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), ""), (None, ""), (None, ""),
        ]
        errors = []
        self.worker.error_signal.connect(errors.append)
        def cast_due_buffs():
            if self.monitor_type.find_player_position_in_image.call_count == 2:
                self.worker._release_keys()
                return True
            return False
        def wait(_):
            if self.monitor_type.find_player_position_in_image.call_count == 3:
                self.assertEqual(self.worker._held_direction, Key.right)
                self.worker._stop_event.set()
            return True
        self.worker._wait.side_effect = wait
        with patch.object(self.worker, "_cast_due_buffs", side_effect=cast_due_buffs) as cast:
            self.run_at_frame_times([0.0, 1.0, 6.1])
        self.assertEqual(errors, [])
        self.assertEqual(cast.call_count, 3)
        self.assertEqual(self.keyboard.press.call_args_list.count(call(Key.right)), 2)

    def test_focus_loss_pauses_without_error_and_stop_while_paused_never_resumes(self):
        self.worker._hold_movement("right")
        self.keyboard.reset_mock()
        self.selector.is_window_foreground.return_value = False
        errors, messages = [], []
        self.worker.error_signal.connect(errors.append)
        self.worker.log_update.connect(messages.append)

        def paused_wait(_):
            self.assertIsNone(self.worker._held_direction)
            self.assertFalse(self.worker._jump_held)
            self.monitor.capture_minimap.assert_not_called()
            self.monitor.auto_detect_dark_region.assert_not_called()
            self.keyboard.press.assert_not_called()
            self.worker.stop()
            return False

        self.worker._wait.side_effect = paused_wait
        self.worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(sum("失去焦点" in message for message in messages), 1)
        self.assertEqual(self.keyboard.method_calls, [call.release(Key.right), call.release(Key.space)])
        self.monitor.close_capture.assert_called_once_with()

    def test_focus_regain_relocates_and_restarts_direction_then_jump(self):
        self.monitor_type.find_player_position_in_image.side_effect = [((60, 20), ""), ((140, 20), "")]
        updates, messages, errors = [], [], []
        self.worker.log_update.connect(messages.append)
        self.worker.error_signal.connect(errors.append)

        def position(x, direction):
            updates.append((x, direction))
            if len(updates) == 1:
                self.selector.is_window_foreground.return_value = False
            else:
                self.worker._stop_event.set()

        def wait(_):
            if self.worker._focus_paused:
                self.assertIsNone(self.worker.direction)
                self.assertFalse(self.worker._jump_held)
                self.selector.is_window_foreground.return_value = True
            return True

        self.worker.position_update.connect(position)
        self.worker._wait.side_effect = wait
        self.worker.run()

        self.assertEqual(updates, [(60.0, "right"), (140.0, "left")])
        self.assertEqual(errors, [])
        self.assertTrue(any("恢复焦点" in message for message in messages))
        self.assertEqual(self.monitor.auto_detect_dark_region.call_count, 2)
        self.selector.ensure_window_focus.assert_called_once_with(101)
        self.assertEqual(self.keyboard.method_calls, [
            call.press(Key.right), call.press(Key.space),
            call.release(Key.right), call.release(Key.space),
            call.press(Key.left), call.press(Key.space),
            call.release(Key.left), call.release(Key.space),
        ])

    def test_focus_pause_resets_the_missing_marker_timeout(self):
        self.monitor_type.find_player_position_in_image.side_effect = [
            (None, ""), (None, ""), ((140, 20), ""),
        ]
        self.worker.position_update.connect(lambda *_: self.worker._stop_event.set())
        errors = []
        self.worker.error_signal.connect(errors.append)

        def wait(_):
            if self.worker._focus_paused:
                self.selector.is_window_foreground.return_value = True
            elif self.monitor_type.find_player_position_in_image.call_count == 1:
                self.selector.is_window_foreground.return_value = False
            return True

        self.worker._wait.side_effect = wait
        self.run_at_frame_times([1.0, 100.0, 100.1])

        self.assertEqual(errors, [])
        self.assertEqual(self.keyboard.press.call_args_list, [call(Key.left), call(Key.space)])

    def test_focus_loss_between_direction_and_jump_releases_without_jumping(self):
        def lose_focus(_):
            self.selector.is_window_foreground.return_value = False
            return True

        self.worker._wait.side_effect = lose_focus
        self.worker._hold_movement("right")

        self.assertEqual(self.keyboard.method_calls, [call.press(Key.right), call.release(Key.right)])
        self.assertTrue(self.worker._focus_paused)

    def test_focus_loss_during_capture_discards_the_frame_and_relocates_on_resume(self):
        captures = []
        def capture():
            captures.append(True)
            if len(captures) == 1:
                self.selector.is_window_foreground.return_value = False
            return np.zeros((100, 200, 3), dtype=np.uint8)
        self.monitor.capture_minimap.side_effect = capture
        self.monitor_type.find_player_position_in_image.return_value = ((60, 20), "")
        self.worker.position_update.connect(lambda *_: self.worker._stop_event.set())
        def wait(_):
            if self.worker._focus_paused:
                self.keyboard.press.assert_not_called()
                self.monitor_type.find_player_position_in_image.assert_not_called()
                self.selector.is_window_foreground.return_value = True
            return True
        self.worker._wait.side_effect = wait
        self.worker.run()
        self.assertEqual(len(captures), 2)
        self.assertEqual(self.monitor.auto_detect_dark_region.call_count, 2)
        self.monitor_type.find_player_position_in_image.assert_called_once()

    def test_focus_loss_during_turn_never_presses_the_opposite_keys(self):
        self.worker._hold_movement("right")
        self.keyboard.reset_mock()

        def lose_focus(_):
            self.selector.is_window_foreground.return_value = False
            return True

        self.worker._wait.side_effect = lose_focus
        self.worker._hold_movement("left")

        self.assertEqual(self.keyboard.method_calls, [call.release(Key.right), call.release(Key.space)])
        self.assertIsNone(self.worker.direction)

    def test_failed_initial_activation_waits_for_focus_without_a_dialog_error(self):
        self.selector.ensure_window_focus.return_value = False
        self.selector.is_window_foreground.return_value = False
        self.worker._wait.side_effect = lambda _: (self.worker.stop() or False)
        errors = []
        self.worker.error_signal.connect(errors.append)
        self.worker.run()
        self.assertEqual(errors, [])
        self.keyboard.press.assert_not_called()

    def test_closed_window_stops_and_releases_keys(self):
        self.worker._hold_movement("right")
        self.selector.is_window_valid.return_value = False
        errors = []
        self.worker.error_signal.connect(errors.append)

        self.worker.run()

        self.assertIn("游戏窗口已关闭", errors[0])
        self.keyboard.release.assert_any_call(Key.right)
        self.keyboard.release.assert_any_call(Key.space)
        self.monitor.close_capture.assert_called_once_with()

    def enable_skill(self, **kwargs):
        self.worker = TauntWorker(101, self.topology, self.topology.platforms[0].id,
                                  jump_key="Space", skill_key="C", window_selector=self.selector,
                                  **kwargs)
        self.worker._wait = Mock(return_value=True)
        self.addCleanup(self.worker.stop)

    def test_stuck_recovery_restarts_with_a_fresh_jump_before_pressing_skill(self):
        self.enable_skill(interval_min_ms=250, interval_max_ms=250,
                          hold_min_ms=90, hold_max_ms=90)
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.keyboard.reset_mock()
        self.clock.return_value = 100.0
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._restart_movement("right")
            self.assertEqual(self.keyboard.method_calls, [
                call.release(Key.right), call.release(Key.space), call.release("c"),
                call.press(Key.right), call.press(Key.space),
            ])
            self.assertAlmostEqual(self.worker._action_deadline, 100.11)
            self.clock.return_value = 100.111
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.method_calls[-1], call.press("c"))
            self.assertAlmostEqual(self.worker._skill_release_at, 100.201)

    def test_stop_during_stuck_recovery_does_not_repress_any_key(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.keyboard.reset_mock()
        self.worker._wait.side_effect = lambda _: (self.worker.stop() or False)
        self.worker._restart_movement("right")
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c")])

    def test_losing_focus_during_stuck_recovery_does_not_repress_any_key(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.keyboard.reset_mock()
        def lose_focus(_):
            self.selector.is_window_foreground.return_value = False
            return True
        self.worker._wait.side_effect = lose_focus
        self.worker._restart_movement("right")
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c")])
        self.assertTrue(self.worker._focus_paused)

    def test_short_jump_skill_and_releases_follow_recorded_order_without_blocking_movement(self):
        self.enable_skill()
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._hold_movement("right")
            self.worker._wait.reset_mock()
            self.assertAlmostEqual(self.worker._action_deadline, 10.11)
            self.clock.return_value = 10.109
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.method_calls, [call.press(Key.right), call.press(Key.space)])
            self.clock.return_value = 10.111
            self.worker._tick_actions()
            self.assertAlmostEqual(self.worker._action_deadline, 10.191)
            self.assertAlmostEqual(self.worker._skill_release_at, 10.271)
            self.clock.return_value = 10.192
            self.worker._tick_actions()
            self.assertFalse(self.worker._jump_held)
            self.assertTrue(self.worker._skill_held)
            self.clock.return_value = 10.272
            self.worker._tick_actions()
            self.assertAlmostEqual(self.worker._action_deadline, 10.672)
            self.clock.return_value = 10.671
            self.worker._tick_actions()
            self.assertFalse(self.worker._jump_held)
            self.clock.return_value = 10.673
            self.worker._tick_actions()
        self.assertEqual(self.keyboard.method_calls, [
            call.press(Key.right), call.press(Key.space), call.press("c"),
            call.release(Key.space), call.release("c"), call.press(Key.space),
        ])
        self.worker._wait.assert_not_called()
        self.assertEqual(self.worker._held_direction, Key.right)
        self.assertTrue(self.worker._jump_held)

    def test_every_cycle_resamples_jump_delay_jump_hold_skill_hold_and_gap(self):
        self.enable_skill()
        lead_times, jump_holds, skill_holds, gaps = [], [], [], []
        with patch("workers.taunt_worker.random.uniform", side_effect=[
            0.04, 0.09, 0.15, 0.075, 0.35, 0.14, 0.175, 0.085, 0.48,
        ]) as choose:
            self.worker._hold_movement("right")
            for cycle in range(2):
                start = self.worker._jump_started_at
                lead_times.append(self.worker._action_deadline - start)
                self.clock.return_value = self.worker._action_deadline + 0.000001
                skill_start = self.clock.return_value
                self.worker._tick_actions()
                skill_holds.append(self.worker._skill_release_at - skill_start)
                jump_holds.append(self.worker._action_deadline - start)
                self.clock.return_value = self.worker._action_deadline + 0.000001
                self.worker._tick_actions()
                self.clock.return_value = self.worker._action_deadline + 0.000001
                self.worker._tick_actions()
                gaps.append(self.worker._action_deadline - self.clock.return_value)
                if cycle == 0:
                    self.clock.return_value = self.worker._action_deadline + 0.000001
                    self.worker._tick_actions()
        self.assertEqual(choose.call_args_list, [
            call(0.025, 0.055), call(0.07, 0.15), call(0.14, 0.18), call(0.07, 0.09),
            call(0.3, 0.5), call(0.07, 0.15), call(0.14, 0.18), call(0.07, 0.09), call(0.3, 0.5),
        ])
        for values in (lead_times, jump_holds, skill_holds, gaps):
            self.assertNotAlmostEqual(values[0], values[1])

    def test_custom_skill_hold_is_preserved_and_jump_is_released_before_skill(self):
        self.enable_skill(interval_min_ms=320, interval_max_ms=570,
                          hold_min_ms=20, hold_max_ms=40)
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._hold_movement("right")
            self.clock.return_value = 10.111
            self.worker._tick_actions()
            self.assertAlmostEqual(self.worker._skill_release_at, 10.141)
            self.assertAlmostEqual(self.worker._action_deadline, 10.126)
            self.clock.return_value = 10.127
            self.worker._tick_actions()
            self.clock.return_value = 10.142
            self.worker._tick_actions()
            self.assertAlmostEqual(self.worker._action_deadline, 10.587)
        self.assertEqual(self.keyboard.method_calls[-2:], [call.release(Key.space), call.release("c")])

    def test_expired_airborne_timing_skips_skill_and_never_catches_up_old_actions(self):
        self.enable_skill()
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._hold_movement("right")
            self.clock.return_value = 10.35
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.method_calls, [
                call.press(Key.right), call.press(Key.space), call.release(Key.space)])
            self.clock.return_value = 20.0
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.method_calls[-1], call.press(Key.space))
            self.assertEqual(self.keyboard.press.call_args_list.count(call("c")), 0)
            self.clock.return_value = 20.111
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.method_calls[-1], call.press("c"))

    def test_delayed_release_releases_jump_then_skill_without_starting_another_combo(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.clock.return_value = self.worker._action_deadline + 0.001
        self.worker._tick_actions()
        self.assertTrue(self.worker._skill_held)
        self.keyboard.reset_mock()
        self.clock.return_value = 11.0
        self.worker._tick_actions()
        self.assertEqual(self.keyboard.method_calls, [call.release(Key.space), call.release("c")])
        self.assertEqual(self.worker._action_stage, "rest")
        self.assertGreater(self.worker._action_deadline, 11.0)

    def test_turn_cancels_the_old_jump_attack_and_retimes_skill_from_the_new_jump(self):
        self.enable_skill()
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._hold_movement("right")
            self.clock.return_value = 10.05
            self.worker._hold_movement("left")
            self.assertAlmostEqual(self.worker._jump_started_at, 10.05)
            self.assertAlmostEqual(self.worker._action_deadline, 10.16)
            self.clock.return_value = 10.112
            self.worker._tick_actions()
            self.assertNotIn(call("c"), self.keyboard.press.call_args_list)
            self.clock.return_value = 10.161
            self.worker._tick_actions()
            self.assertEqual(self.keyboard.press.call_args_list.count(call("c")), 1)

    def test_focus_loss_cancels_pending_events_at_every_combo_stage(self):
        for steps, stage in enumerate(("jump_lead", "jump_and_skill", "skill_tail", "rest")):
            with self.subTest(stage=stage):
                self.selector.is_window_foreground.return_value = True
                self.clock.return_value = 10.0
                self.enable_skill()
                self.worker._hold_movement("right")
                for _ in range(steps):
                    self.clock.return_value = self.worker._action_deadline + 0.001
                    self.worker._tick_actions()
                self.assertEqual(self.worker._action_stage, stage)
                expected = [call.release(Key.right)]
                if self.worker._jump_held:
                    expected.append(call.release(Key.space))
                if self.worker._skill_held:
                    expected.append(call.release("c"))
                self.keyboard.reset_mock()
                self.selector.is_window_foreground.return_value = False
                self.worker._tick_actions()
                self.assertEqual(self.keyboard.method_calls, expected)
                self.assertIsNone(self.worker._action_deadline)
                self.selector.is_window_foreground.return_value = True
                self.clock.return_value = 20.0
                self.worker._tick_actions()
                self.keyboard.press.assert_not_called()
                self.worker.stop()

    def test_stop_cancels_pending_events_at_every_combo_stage(self):
        for steps, stage in enumerate(("jump_lead", "jump_and_skill", "skill_tail", "rest")):
            with self.subTest(stage=stage):
                self.clock.return_value = 10.0
                self.enable_skill()
                self.worker._hold_movement("right")
                for _ in range(steps):
                    self.clock.return_value = self.worker._action_deadline + 0.001
                    self.worker._tick_actions()
                expected = [call.release(Key.right)]
                if self.worker._jump_held:
                    expected.append(call.release(Key.space))
                if self.worker._skill_held:
                    expected.append(call.release("c"))
                self.keyboard.reset_mock()
                self.worker.stop()
                self.clock.return_value = 20.0
                self.worker._tick_actions()
                self.assertEqual(self.keyboard.method_calls, expected)
                self.assertIsNone(self.worker._action_deadline)

    def test_without_skill_key_direction_stays_held_between_short_jumps(self):
        with patch("workers.taunt_worker.random.uniform", side_effect=lambda a, b: (a + b) / 2):
            self.worker._hold_movement("right")
            self.assertAlmostEqual(self.worker._action_deadline, 10.19)
            self.clock.return_value = 10.191
            self.worker._tick_actions()
            for _ in range(10):
                self.worker._hold_movement("right")
            self.assertFalse(self.worker._jump_held)
            self.clock.return_value = 10.592
            self.worker._tick_actions()
        self.assertEqual(self.keyboard.method_calls, [
            call.press(Key.right), call.press(Key.space), call.release(Key.space), call.press(Key.space)])

    def test_stuck_detection_still_counts_when_short_jump_is_released(self):
        self.worker._hold_movement("right")
        self.assertFalse(self.worker._movement_stalled(0.3, 200, 10.0))
        self.clock.return_value = 10.3
        self.worker._tick_actions()
        self.assertFalse(self.worker._jump_held)
        self.assertTrue(self.worker._movement_stalled(0.3, 200, 12.0))

    def test_live_frame_loop_keeps_pulsing_during_marker_loss_and_turns_after_recovery(self):
        self.enable_skill(interval_min_ms=80, interval_max_ms=80,
                          hold_min_ms=40, hold_max_ms=40)
        self.monitor_type.find_player_position_in_image.side_effect = [
            ((60, 20), "")] * 5 + [(None, "")] * 350 + [((178, 20), "")] * 25
        updates, errors = [], []
        clock = [10.0]
        def wait(seconds):
            clock[0] += seconds
            if 6 <= self.monitor_type.find_player_position_in_image.call_count <= 355:
                self.assertEqual(self.worker._held_direction, Key.right)
                self.assertNotIn(call(Key.right), self.keyboard.release.call_args_list)
            return True
        def position(x, direction):
            updates.append((x, direction))
            if len(updates) == 30:
                self.worker._stop_event.set()
        self.worker._wait.side_effect = wait
        self.worker.position_update.connect(position)
        self.worker.error_signal.connect(errors.append)
        with patch("workers.taunt_worker.time.monotonic", side_effect=lambda: clock[0]):
            self.worker.run()
        self.assertEqual(errors, [])
        self.assertGreater(clock[0], 15.0)
        self.assertEqual(len(updates), 30)
        self.assertEqual(updates[4][1], "right")
        self.assertEqual(updates[5][1], "left")
        presses = self.keyboard.press.call_args_list
        self.assertEqual(presses.count(call(Key.right)), 1)
        self.assertEqual(presses.count(call(Key.left)), 1)
        self.assertGreater(presses.count(call(Key.space)), 2)
        self.assertGreater(presses.count(call("c")), 2)
        self.assertEqual(presses.count(call("c")), self.keyboard.release.call_args_list.count(call("c")))

    def test_stop_during_marker_loss_releases_a_held_skill_with_the_movement_keys(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.monitor_type.find_player_position_in_image.return_value = (None, "")
        self.worker._wait.side_effect = lambda _: (self.worker.stop() or False)
        self.keyboard.reset_mock()
        self.worker.run()
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c")])

    def test_focus_lost_at_the_skill_press_deadline_prevents_the_press(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.clock.return_value = self.worker._action_deadline + 0.001
        self.selector.is_window_foreground.return_value = False
        self.keyboard.reset_mock()
        self.worker._tick_actions()
        self.keyboard.press.assert_not_called()
        self.assertIsNone(self.worker._action_deadline)

    def test_turning_is_not_blocked_by_a_held_skill_key(self):
        self.enable_skill(hold_min_ms=500, hold_max_ms=500)
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.keyboard.reset_mock()
        self.worker._hold_movement("left")
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c"),
            call.press(Key.left), call.press(Key.space)])
        self.assertFalse(self.worker._skill_held)
        self.assertEqual(self.worker._action_stage, "jump_lead")

    def test_focus_loss_releases_skill_and_resets_the_schedule_before_resuming(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.clock.return_value = self.worker._action_deadline + 0.001
        self.worker._tick_actions()
        self.assertTrue(self.worker._skill_held)
        self.keyboard.reset_mock()
        self.selector.is_window_foreground.return_value = False
        self.worker._tick_actions()
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c")])
        self.assertIsNone(self.worker._action_deadline)
        self.selector.is_window_foreground.return_value = True
        self.worker._tick_actions()
        self.keyboard.press.assert_not_called()
        self.worker._focus_paused = False
        self.worker._hold_movement("left")
        self.worker._tick_actions()
        self.assertFalse(self.worker._skill_held)
        self.assertEqual(self.worker._action_stage, "jump_lead")
        self.assertGreater(self.worker._action_deadline, self.clock.return_value)

    def test_stop_releases_skill_direction_and_jump_and_never_sends_another_skill(self):
        self.enable_skill()
        self.worker._hold_movement("right")
        self.worker._skill_held = True
        self.keyboard.reset_mock()
        self.worker.stop()
        self.worker._tick_actions()
        self.assertEqual(self.keyboard.method_calls, [
            call.release(Key.right), call.release(Key.space), call.release("c")])
        self.assertFalse(self.worker._skill_held)
        self.assertIsNone(self.worker._action_deadline)

    def test_skill_key_rejects_direction_escape_and_the_jump_key(self):
        self.assertIsNone(TauntWorker.resolve_skill_key("", "Alt"))
        self.assertEqual(TauntWorker.resolve_skill_key("C", "Alt"), "c")
        for key, jump in (("Left", "Alt"), ("Esc", "Alt"), ("c", "C"),
                          ("PageDown", "pagedown"), ("invalid", "Space")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                TauntWorker.resolve_skill_key(key, jump)

    def test_failed_minimap_detection_does_not_press_keys(self):
        self.monitor.auto_detect_dark_region.return_value = None
        errors = []
        self.worker.error_signal.connect(errors.append)

        self.worker.run()

        self.assertIn("无法识别小地图", errors[0])
        self.keyboard.press.assert_not_called()
        self.monitor.close_capture.assert_called_once_with()

    def test_wrong_map_does_not_press_keys(self):
        self.topology.visual_signature = [20] * 384
        errors = []
        self.worker.error_signal.connect(errors.append)
        with patch("workers.taunt_worker.MinimapVisualMatcher.comparison", return_value={"isMatch": False}):
            self.worker.run()
        self.assertIn("不匹配", errors[0])
        self.keyboard.press.assert_not_called()

    def test_key_selection_supports_modifiers_function_keys_and_physical_letters(self):
        self.assertEqual(TauntWorker.resolve_jump_key("Alt"), Key.alt)
        self.assertEqual(TauntWorker.resolve_jump_key("F5"), Key.f5)
        self.assertEqual(TauntWorker.resolve_jump_key("PageDown"), Key.page_down)
        self.assertEqual(TauntWorker.resolve_jump_key("C"), "c")
        for value in ("Left", "Up", "Esc", "bad key", ""):
            with self.subTest(key=value), self.assertRaises(ValueError):
                TauntWorker.resolve_jump_key(value)


class TauntConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.maps = [make_map(), make_map("另一个地图", 0.2, 0.7)]
        self.panel = TauntPanel(self.maps)
        self.addCleanup(self.panel.close)

    def test_map_selection_only_lists_platforms_on_that_map(self):
        self.assertEqual(self.panel.selected_platform_id(), self.maps[0].platforms[0].id)
        self.panel.map_list.setCurrentRow(1)
        self.assertEqual(self.panel.selected_platform_id(), self.maps[1].platforms[0].id)
        self.assertIn("P1", self.panel.platform_list.item(0).text())

    def test_restore_selection_uses_stable_ids_when_maps_are_reordered(self):
        settings = {"taunt_map_name": self.maps[1].map_name,
                    "taunt_platform_id": self.maps[1].platforms[0].id, "taunt_jump_key": "C"}
        self.panel.set_maps(list(reversed(self.maps)))
        self.panel.restore_settings(settings)
        for key, value in settings.items():
            self.assertEqual(self.panel.settings()[key], value)

    def test_deleted_map_or_platform_is_not_silently_replaced(self):
        self.panel.restore_settings({"taunt_map_name": self.maps[0].map_name, "taunt_platform_id": "deleted"})
        self.assertEqual(self.panel.selected_platform_id(), "")
        self.panel.restore_settings({"taunt_map_name": "deleted", "taunt_platform_id": "deleted"})
        self.assertIsNone(self.panel.selected_map())

    def test_configuration_round_trip_is_independent_of_other_modes_jump_key(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SettingsManager(str(Path(directory) / "settings.ini"))
            expected = self.panel.settings()
            expected["taunt_jump_key"] = "C"
            expected.update(taunt_skill_key="D", taunt_interval_min_ms=333,
                            taunt_interval_max_ms=777, taunt_hold_min_ms=51, taunt_hold_max_ms=137)
            manager.save_settings([], mode="taunt", jump_key="Alt", **expected)
            settings = manager.load_settings()
        self.assertEqual(settings["mode"], "taunt")
        self.assertEqual(settings["jump_key"], "Alt")
        for key, value in expected.items():
            self.assertEqual(settings[key], value)
        self.panel.restore_settings(settings)
        self.assertEqual(self.panel.settings(), expected)

    def test_old_settings_load_default_skill_ranges_and_keep_movement_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text("[General]\nmode=taunt\ntaunt_jump_key=Space\n", encoding="utf-8")
            settings = SettingsManager(str(path)).load_settings()
        self.panel.restore_settings(settings)
        self.assertEqual(self.panel.skill_key, "")
        self.assertEqual(self.panel.worker_options(), {
            "skill_key": "", "interval_min_ms": 300, "interval_max_ms": 500,
            "hold_min_ms": 140, "hold_max_ms": 180,
        })

    def test_legacy_default_timings_upgrade_to_the_recorded_combo_rhythm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text("[General]\nmode=taunt\ntaunt_skill_key=A\n"
                            "taunt_interval_min_ms=800\ntaunt_interval_max_ms=1200\n"
                            "taunt_hold_min_ms=60\ntaunt_hold_max_ms=120\n", encoding="utf-8")
            settings = SettingsManager(str(path)).load_settings()
        self.panel.restore_settings(settings)
        self.assertEqual(self.panel.worker_options(), {
            "skill_key": "A", "interval_min_ms": 300, "interval_max_ms": 500,
            "hold_min_ms": 140, "hold_max_ms": 180,
        })

    def test_legacy_custom_timings_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text("[General]\nmode=taunt\ntaunt_skill_key=A\n"
                            "taunt_interval_min_ms=700\ntaunt_interval_max_ms=900\n"
                            "taunt_hold_min_ms=130\ntaunt_hold_max_ms=210\n", encoding="utf-8")
            settings = SettingsManager(str(path)).load_settings()
        self.panel.restore_settings(settings)
        self.assertEqual(self.panel.worker_options(), {
            "skill_key": "A", "interval_min_ms": 700, "interval_max_ms": 900,
            "hold_min_ms": 130, "hold_max_ms": 210,
        })

    def test_newly_saved_ranges_matching_old_defaults_are_not_migrated_again(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SettingsManager(str(Path(directory) / "settings.ini"))
            manager.save_settings([], mode="taunt", taunt_skill_key="A",
                                  taunt_interval_min_ms=800, taunt_interval_max_ms=1200,
                                  taunt_hold_min_ms=60, taunt_hold_max_ms=120)
            settings = manager.load_settings()
        self.panel.restore_settings(settings)
        self.assertEqual(self.panel.worker_options(), {
            "skill_key": "A", "interval_min_ms": 800, "interval_max_ms": 1200,
            "hold_min_ms": 60, "hold_max_ms": 120,
        })

    def test_invalid_saved_ranges_are_repaired_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text("[General]\nmode=taunt\ntaunt_skill_key=C\n"
                            "taunt_interval_min_ms=bad\ntaunt_interval_max_ms=400\n"
                            "taunt_hold_min_ms=900000\ntaunt_hold_max_ms=-2\n", encoding="utf-8")
            settings = SettingsManager(str(path)).load_settings()
        self.panel.restore_settings(settings)
        self.assertEqual(settings["mode"], "taunt")
        self.assertEqual(self.panel.worker_options(), {
            "skill_key": "C", "interval_min_ms": 300, "interval_max_ms": 400,
            "hold_min_ms": 1, "hold_max_ms": 600000,
        })

    def test_millisecond_controls_keep_order_and_changes_are_saved(self):
        changed = Mock()
        self.panel.changed.connect(changed)
        self.panel.interval_min.setValue(1500)
        self.assertEqual(self.panel.interval_max.value(), 1500)
        self.panel.hold_max.setValue(40)
        self.assertEqual(self.panel.hold_min.value(), 40)
        self.assertGreater(changed.call_count, 0)
        self.panel.skill_key = "C"
        self.panel._clear_skill_key()
        self.assertEqual(self.panel.settings()["taunt_skill_key"], "")

    def test_taunt_follows_the_existing_account_authorization_policy(self):
        for source in ({}, {"username": "ordinary_user"}, {"authorizedModes": []}):
            with self.subTest(source=source):
                self.assertNotIn("taunt", AccountManager._authorized_modes_from(source))
        self.assertNotIn("taunt", AccountManager.DEFAULT_AUTHORIZED_MODES)
        self.assertNotIn("taunt", MainWindow.DEFAULT_AUTHORIZED_MODES)
        self.assertIn("taunt", AccountManager._authorized_modes_from({}, is_super_admin=True))
        self.assertIn("taunt", AccountManager._authorized_modes_from({"authorizedModes": ["taunt"]}))
        self.assertNotIn("taunt", AccountManager._authorized_modes_from({"authorizedModes": ["live"]}))


class TauntWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = SettingsManager(str(Path(directory.name) / "settings.ini"))
        self.settings.legacy_config_path = str(Path(directory.name) / "missing.ini")
        self.patches.enter_context(patch("ui.main_window.SettingsManager", return_value=self.settings))
        store = self.patches.enter_context(patch("ui.modern_main_window.MapLibraryStore"))
        store.return_value.load.return_value = [make_map()]
        self.patches.enter_context(patch.object(MainWindow, "auto_identify_on_startup"))
        self.patches.enter_context(patch("ui.modern_main_window.get_screen_resolution", return_value=(1280, 720)))
        self.window = MainWindow(authorized_modes=["dead", "taunt"])
        self.addCleanup(self.window.close)
        self.window._ensure_game_window_available = Mock(return_value=True)
        self.window.game_window_hwnd = 101
        self.window._switch_mode_tab("taunt")
        self.worker_type = self.patches.enter_context(patch("ui.modern_main_window.TauntWorker"))

    def test_starting_taunt_requires_no_buffs_and_stopping_restores_controls(self):
        for checkbox in self.window.buff_checkboxes:
            checkbox.setChecked(False)
        self.assertFalse(any(buff.enabled for buff in self.window.buffs))

        self.window.start_worker()

        self.worker_type.return_value.start.assert_called_once_with()
        self.assertTrue(self.window.is_worker_running)
        self.assertFalse(self.window.taunt_panel.jump_button.isEnabled())
        for control in (self.window.taunt_panel.skill_button, self.window.taunt_panel.interval_min,
                        self.window.taunt_panel.interval_max, self.window.taunt_panel.hold_min,
                        self.window.taunt_panel.hold_max):
            self.assertFalse(control.isEnabled())
        self.assertFalse(self.window.dead_flower_tab.isEnabled())
        self.assertFalse(self.window.taunt_tab.isEnabled())
        settings = self.settings.load_settings()
        self.assertEqual(settings["mode"], "taunt")
        self.assertEqual(settings["taunt_map_name"], "乌鲁庄园2")

        self.window.stop_worker()

        self.worker_type.return_value.stop.assert_called_once_with()
        self.assertFalse(self.window.is_worker_running)
        self.assertTrue(self.window.taunt_panel.jump_button.isEnabled())
        self.assertTrue(self.window.taunt_panel.skill_button.isEnabled())
        self.assertTrue(self.window.taunt_panel.interval_min.isEnabled())
        self.assertTrue(self.window.dead_flower_tab.isEnabled())
        self.assertTrue(self.window.taunt_tab.isEnabled())

    def test_start_passes_skill_key_and_custom_millisecond_ranges_to_worker(self):
        self.window.taunt_panel.restore_settings({
            "taunt_map_name": "乌鲁庄园2", "taunt_jump_key": "Space", "taunt_skill_key": "C",
            "taunt_interval_min_ms": 432, "taunt_interval_max_ms": 876,
            "taunt_hold_min_ms": 71, "taunt_hold_max_ms": 153,
        })
        self.window.start_worker()
        options = self.worker_type.call_args.kwargs
        for key, value in self.window.taunt_panel.worker_options().items():
            self.assertEqual(options[key], value)
        self.assertEqual(options["jump_key"], "Space")
        saved = self.settings.load_settings()
        self.assertEqual(saved["taunt_skill_key"], "C")
        self.assertEqual(saved["taunt_hold_max_ms"], 153)

    def test_empty_platform_selection_does_not_start_input(self):
        self.window.taunt_panel.platform_list.setCurrentRow(-1)
        with patch("ui.modern_main_window.QMessageBox.warning") as warning:
            self.window.start_worker()
        self.worker_type.assert_not_called()
        warning.assert_called_once()

    def test_revoking_authorization_stops_taunt_and_switches_back(self):
        self.window.start_worker()

        self.window.apply_authorized_modes(["dead"])

        self.worker_type.return_value.stop.assert_called_once_with()
        self.assertFalse(self.window.is_worker_running)
        self.assertEqual(self.window.mode, "dead")
        self.assertTrue(self.window.taunt_tab.isHidden())
        self.assertTrue(self.window.taunt_panel.isHidden())

    def test_default_account_does_not_expose_saved_taunt_mode(self):
        self.settings.save_settings([], mode="taunt")
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertNotIn("taunt", window.authorized_modes)
        self.assertTrue(window.taunt_tab.isHidden())
        self.assertTrue(window.taunt_panel.isHidden())
        self.assertEqual(window.mode, "dead")
        window._switch_mode_tab("taunt")
        self.assertEqual(window.mode, "dead")

    def test_explicit_grant_reveals_taunt_mode(self):
        self.window.apply_authorized_modes(["dead"])
        self.assertTrue(self.window.taunt_tab.isHidden())
        self.window._switch_mode_tab("taunt")
        self.assertEqual(self.window.mode, "dead")

        self.window.apply_authorized_modes(["dead", "taunt"])
        self.assertFalse(self.window.taunt_tab.isHidden())
        self.window._switch_mode_tab("taunt")
        self.assertEqual(self.window.mode, "taunt")
        self.assertFalse(self.window.taunt_panel.isHidden())

    def test_unauthorized_taunt_cannot_start_even_with_stale_mode(self):
        self.window.apply_authorized_modes(["dead"])
        self.window.mode = "taunt"

        with patch("ui.modern_main_window.QMessageBox.warning") as warning:
            self.window.start_worker()

        self.worker_type.assert_not_called()
        warning.assert_called_once()
        self.assertFalse(self.window.is_worker_running)

    def test_revoking_all_modes_stops_and_hides_taunt(self):
        self.window.start_worker()

        self.window.apply_authorized_modes([])
        self.window._update_movement_mode_visibility()

        self.worker_type.return_value.stop.assert_called_once_with()
        self.assertFalse(self.window.is_worker_running)
        self.assertTrue(self.window.taunt_tab.isHidden())
        self.assertTrue(self.window.taunt_panel.isHidden())
        self.assertFalse(self.window.toggle_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()

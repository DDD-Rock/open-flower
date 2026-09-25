import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from workers.mumu_smart_walk_worker import (
    BUFF_HOLD_MAX_MS,
    BUFF_HOLD_MIN_MS,
    MumuSmartWalkWorker,
)


class MumuSmartWalkWorkerTests(unittest.TestCase):
    def _worker(self, countdowns=None, statuses=None):
        return MumuSmartWalkWorker(
            "127.0.0.1:16384",
            "adb.exe",
            lambda: None,
            countdown_callback=(countdowns if countdowns is not None else []).append,
            status_callback=(statuses if statuses is not None else []).append,
        )

    def test_two_due_buffs_are_double_pressed_with_windows_client_gap(self):
        countdowns = []
        statuses = []
        worker = self._worker(countdowns, statuses)
        worker._press_key = Mock(return_value=True)
        worker._stop.wait = Mock(return_value=False)
        config = {
            "buffs": [
                {"enabled": True, "key": "1", "duration": 270},
                {"enabled": True, "key": "2", "duration": 270},
            ],
            "random_behavior_enabled": False,
            "random_behavior_value": 20,
        }
        due = {0: 0.0, 1: 0.0}

        with patch(
            "workers.mumu_smart_walk_worker.random.uniform",
            side_effect=[0.2, 0.2],
        ), patch(
            "workers.mumu_smart_walk_worker.random.randint",
            return_value=2500,
        ), patch(
            "workers.mumu_smart_walk_worker.time.monotonic",
            side_effect=[100.0, 110.0],
        ):
            worker._release_due_buffs(config, due, 1.0)

        self.assertEqual(
            [call.args[0] for call in worker._press_key.call_args_list],
            ["1", "1", "2", "2"],
        )
        self.assertEqual(due, {0: 370.0, 1: 380.0})
        self.assertIn(2.5, [call.args[0] for call in worker._stop.wait.call_args_list])
        self.assertEqual(countdowns[-1], {0: 260, 1: 270})
        self.assertTrue(any("BUFF 2" in status and "已释放" in status for status in statuses))

    def test_buff_hold_is_300_to_500_milliseconds(self):
        worker = self._worker()
        worker._virtual_key = Mock(return_value=0x31)
        worker._get_window_handle = Mock(return_value=1)
        worker._post_key = Mock()

        with patch(
            "workers.mumu_smart_walk_worker.random.randint",
            return_value=400,
        ) as randint, patch(
            "workers.mumu_smart_walk_worker.time.sleep",
        ) as sleep:
            self.assertTrue(
                worker._press_key("1", (BUFF_HOLD_MIN_MS, BUFF_HOLD_MAX_MS))
            )

        randint.assert_called_once_with(300, 500)
        sleep.assert_called_once_with(0.4)
        self.assertEqual(
            [call.args[2] for call in worker._post_key.call_args_list],
            [True, False],
        )

    def test_failed_double_press_is_not_given_a_false_countdown(self):
        countdowns = []
        statuses = []
        worker = self._worker(countdowns, statuses)
        worker._press_key = Mock(side_effect=[True, False])
        worker._stop.wait = Mock(return_value=False)
        config = {
            "buffs": [{"enabled": True, "key": "1", "duration": 270}],
            "random_behavior_enabled": False,
            "random_behavior_value": 20,
        }
        due = {0: 0.0}

        with patch("workers.mumu_smart_walk_worker.random.uniform", return_value=0.2):
            worker._release_due_buffs(config, due, 1.0)

        self.assertEqual(due[0], 0.0)
        self.assertTrue(any("发送失败" in status for status in statuses))

    def test_config_preserves_empty_buff_slot_indexes(self):
        worker = self._worker()
        worker.update_config(
            {
                "buffs": [
                    {"enabled": True, "key": "1", "duration": 270},
                    {"enabled": False, "key": "", "duration": 270},
                    {"enabled": True, "key": "3", "duration": 270},
                ]
            }
        )

        self.assertEqual(len(worker._config["buffs"]), 3)
        self.assertEqual(worker._config["buffs"][2]["key"], "3")

    def test_startup_moves_horizontally_into_range_and_ignores_height(self):
        statuses = []
        positions = iter([(20, 999), (34, -100), (41, 5000)])
        worker = MumuSmartWalkWorker(
            "127.0.0.1:16384",
            "adb.exe",
            lambda: SimpleNamespace(player_position=next(positions)),
            status_callback=statuses.append,
        )
        worker._walk_once = Mock(return_value=True)
        worker._stop.wait = Mock(return_value=False)
        config = {"anchor": (50, 55), "half_width": 10}

        with patch("workers.mumu_smart_walk_worker.random.uniform", return_value=0.4):
            positioned = worker._move_into_horizontal_range(config)

        self.assertTrue(positioned)
        self.assertEqual(
            [call.args[0] for call in worker._walk_once.call_args_list],
            ["right", "right"],
        )
        self.assertTrue(any("定位完成" in status for status in statuses))

    def test_startup_does_not_move_when_x_is_already_in_range(self):
        worker = MumuSmartWalkWorker(
            "127.0.0.1:16384",
            "adb.exe",
            lambda: SimpleNamespace(player_position=(55, 9999)),
        )
        worker._walk_once = Mock(return_value=True)

        positioned = worker._move_into_horizontal_range(
            {"anchor": (50, 1), "half_width": 10}
        )

        self.assertTrue(positioned)
        worker._walk_once.assert_not_called()

    def test_startup_waits_for_marker_before_releasing(self):
        statuses = []
        worker = MumuSmartWalkWorker(
            "127.0.0.1:16384",
            "adb.exe",
            lambda: None,
            status_callback=statuses.append,
        )
        worker._find_position_with_jump = Mock(return_value=None)

        positioned = worker._move_into_horizontal_range(
            {"anchor": (50, 50), "half_width": 10}
        )

        self.assertFalse(positioned)
        self.assertTrue(any("等待重试" in status for status in statuses))

    def test_switching_a_buff_off_and_on_keeps_its_deadline(self):
        worker = self._worker()
        worker._buff_identity = [("1", 270.0), ("2", 200.0)]
        original = {
            "buffs": [
                {"enabled": True, "key": "1", "duration": 270},
                {"enabled": True, "key": "2", "duration": 200},
            ]
        }
        due = worker._align_due_buffs({0: 1000.0, 1: 2000.0}, original)

        disabled = {
            "buffs": [
                {"enabled": False, "key": "1", "duration": 270},
                {"enabled": True, "key": "2", "duration": 200},
            ]
        }
        due = worker._align_due_buffs(due, disabled)
        due = worker._align_due_buffs(due, original)

        self.assertEqual(due, {0: 1000.0, 1: 2000.0})

    def test_changing_one_key_resets_only_that_deadline(self):
        worker = self._worker()
        worker._buff_identity = [("1", 270.0), ("2", 200.0)]

        due = worker._align_due_buffs(
            {0: 1000.0, 1: 2000.0},
            {
                "buffs": [
                    {"enabled": True, "key": "9", "duration": 270},
                    {"enabled": True, "key": "2", "duration": 200},
                ]
            },
        )

        self.assertEqual(due, {0: 0.0, 1: 2000.0})

    def test_unscheduled_slot_is_not_shown_as_zero_seconds(self):
        countdowns = []
        worker = self._worker(countdowns)
        worker._emit_countdown(
            {0: 0.0, 1: 50.0},
            {
                "buffs": [
                    {"enabled": True, "key": "1", "duration": 270},
                    {"enabled": True, "key": "2", "duration": 270},
                ]
            },
            now=10.0,
        )

        self.assertEqual(countdowns[-1], {1: 40})

    def test_turning_controller_off_and_on_keeps_showing_remaining_time(self):
        countdowns = []
        worker = self._worker(countdowns)
        worker._buff_identity = [("1", 270.0)]
        worker._move_into_horizontal_range = Mock(return_value=False)
        worker._release_due_buffs = Mock()
        future = time.monotonic() + 80
        stopped = {
            "enabled": False,
            "anchor": (40, 10),
            "buffs": [{"enabled": True, "key": "1", "duration": 270}],
        }
        running = dict(stopped, enabled=True)
        worker.update_config(stopped)

        due, was_enabled, pending = worker._service_once({0: future}, True, False)

        self.assertEqual(due[0], future)
        self.assertEqual(countdowns[-1], {})
        worker.update_config(running)
        due, was_enabled, pending = worker._service_once(due, was_enabled, pending)

        self.assertEqual(due[0], future)
        self.assertTrue(pending)
        self.assertGreater(countdowns[-1][0], 0)
        worker._release_due_buffs.assert_not_called()

    def test_settle_uses_ranges_and_ignores_a_hidden_marker(self):
        provider = Mock(return_value=None)
        worker = MumuSmartWalkWorker(
            "127.0.0.1:16384",
            "adb.exe",
            provider,
        )
        worker._press_key = Mock(return_value=True)
        worker._stop.wait = Mock(return_value=False)
        worker._needs_settle = True
        worker._settle_not_before = 1000.45
        due = {0: 0.0}

        with patch(
            "workers.mumu_smart_walk_worker.time.monotonic",
            return_value=1000.0,
        ), patch(
            "workers.mumu_smart_walk_worker.random.uniform",
            return_value=0.2,
        ):
            worker._release_due_buffs(
                {
                    "buffs": [{"enabled": True, "key": "1", "duration": 270}],
                    "random_behavior_enabled": False,
                    "random_behavior_value": 20,
                },
                due,
                1.0,
            )

        provider.assert_not_called()
        self.assertAlmostEqual(worker._stop.wait.call_args_list[0].args[0], 0.45)
        self.assertEqual(
            [call.args[0] for call in worker._press_key.call_args_list],
            ["1", "1"],
        )
        self.assertGreater(due[0], 0)
        self.assertFalse(worker._needs_settle)

    def test_stopping_during_settle_does_not_press_buff(self):
        worker = self._worker()
        worker._press_key = Mock(return_value=True)
        worker._stop.wait = Mock(return_value=True)
        worker._needs_settle = True
        worker._settle_not_before = 50.0

        with patch("workers.mumu_smart_walk_worker.time.monotonic", return_value=49.5):
            worker._release_due_buffs(
                {
                    "buffs": [{"enabled": True, "key": "1", "duration": 270}],
                    "random_behavior_enabled": False,
                    "random_behavior_value": 20,
                },
                {0: 0.0},
                1.0,
            )

        worker._press_key.assert_not_called()
        worker._stop.wait.assert_called_with(0.5)

    def test_jump_waits_longer_than_walking_and_both_use_ranges(self):
        worker = self._worker()
        with patch(
            "workers.mumu_smart_walk_worker.time.monotonic",
            return_value=20,
        ), patch(
            "workers.mumu_smart_walk_worker.random.uniform",
            side_effect=[0.55, 1.05],
        ) as uniform:
            worker._note_motion("walk")
            walked_until = worker._settle_not_before
            worker._note_motion("jump")

        self.assertEqual(uniform.call_args_list[0].args, (0.4, 0.6))
        self.assertEqual(uniform.call_args_list[1].args, (0.8, 1.2))
        self.assertEqual(walked_until, 20.55)
        self.assertEqual(worker._settle_not_before, 21.05)
        self.assertTrue(worker._needs_settle)


if __name__ == "__main__":
    unittest.main()

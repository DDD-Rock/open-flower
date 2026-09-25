import unittest
from unittest import mock

from workers.skill_worker import SkillWorker


class SkillWorkerSmartWalkTests(unittest.TestCase):
    def _worker(self):
        with (
            mock.patch("workers.skill_worker.HumanInput") as human_input,
            mock.patch("workers.skill_worker.MinimapMonitor") as monitor,
        ):
            worker = SkillWorker(
                [],
                game_window_hwnd=123,
                movement_mode="smart",
                smart_walk_anchor_pos=(50, 20),
                smart_walk_minimap_region=(5, 10, 180, 90),
                smart_walk_boundary_tolerance=6,
            )
        worker.is_running = True
        worker.human_input = human_input.return_value
        worker.smart_walk_monitor = monitor.return_value
        worker._ensure_game_window_focus = mock.Mock(return_value=True)
        return worker

    def test_missing_marker_jumps_before_walking(self):
        worker = self._worker()
        worker.smart_walk_monitor.find_player_position_once.return_value = None
        worker._find_smart_walk_player_during_jump = mock.Mock(
            return_value=(42, 20)
        )
        worker._smart_walk_from_position = mock.Mock(return_value="complete")

        worker._perform_smart_walk()

        worker._find_smart_walk_player_during_jump.assert_called_once_with()
        worker._smart_walk_from_position.assert_called_once_with((42, 20))

    def test_short_walk_crosses_center_and_stops_at_boundary(self):
        worker = self._worker()
        worker.smart_walk_monitor.find_player_position_once.side_effect = [
            (50, 20),
            (56, 20),
        ]

        with (
            mock.patch(
                "workers.skill_worker.random.randint", return_value=600
            ) as choose_duration,
            mock.patch("workers.skill_worker.time.sleep"),
            mock.patch(
                "workers.skill_worker.time.monotonic",
                side_effect=[0.0, 0.04, 0.08],
            ),
        ):
            result = worker._smart_walk_from_position((42, 20))

        self.assertEqual(result, "boundary")
        choose_duration.assert_called_once_with(300, 600)
        worker.human_input.move_right.assert_called_once_with()
        worker.human_input.stop_move.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

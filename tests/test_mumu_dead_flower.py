import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

from detection.emulator_market import EmulatorMarketRecognizer, MENU_POINT, MARKET_POINT
from ui.emulator_stream_dialog import EmulatorStreamDialog
from utils.mumu_settings import MumuSettingsStore
from workers.mumu_dead_flower_worker import MumuDeadFlowerWorker
from workers.mumu_monitor_worker import MumuMonitorWorker


class DeadFlowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def worker(self):
        snap = {"frame": np.zeros((540, 960, 3), np.uint8),
                "frame_age_ms": 0, "frame_sequence": 1}
        worker = MumuDeadFlowerWorker("test", "adb", Mock(), snapshot_provider=Mock(return_value=snap))
        worker.update_config({"enabled": True, "random_behavior_enabled": False,
                              "buffs": [{"enabled": True, "key": "1", "duration": 270}]})
        return worker, snap

    def test_menu_then_market_fixed_coordinates_and_no_buff_in_menu(self):
        worker, snap = self.worker()
        worker._phase = "return"
        worker._observe = Mock(return_value=("field", snap))
        worker._tap = Mock(return_value=True)
        worker._cast = Mock()
        due, enabled, _ = worker._service_once({0: 0}, True, False)
        worker._tap.assert_called_once_with(MENU_POINT)
        worker._observe.return_value = ("menu", snap)
        worker._service_once(due, enabled, False)
        self.assertEqual(worker._tap.call_args.args, (MARKET_POINT,))
        self.assertEqual(worker._phase, "returning")
        worker._cast.assert_not_called()

    def test_market_due_leaves_first_and_field_casts_then_returns(self):
        worker, snap = self.worker()
        worker._observe = Mock(return_value=("market", snap))
        worker._leave_step = Mock()
        worker._cast = Mock(return_value=True)
        worker._service_once({}, False, False)
        worker._leave_step.assert_called_once()
        worker._cast.assert_not_called()
        worker._observe.return_value = ("field", snap)
        with patch.object(worker._stop, "wait", return_value=False):
            worker._service_once({0: 0}, True, False)
        worker._cast.assert_called_once()
        self.assertEqual(worker._phase, "return")

    def test_return_failure_keeps_return_phase_without_recasting(self):
        worker, snap = self.worker()
        worker._phase = "returning"
        worker._transition_until = 0
        worker._observe = Mock(return_value=("field", snap))
        worker._cast = Mock()
        worker._tap = Mock(return_value=True)
        worker._service_once({0: 0}, True, False)
        self.assertEqual(worker._phase, "return")
        worker._service_once({0: 0}, True, False)
        worker._cast.assert_not_called()
        worker._tap.assert_called_once_with(MENU_POINT)

    def test_slow_menu_frame_does_not_toggle_menu_closed(self):
        worker, snap = self.worker()
        worker._phase = "return"
        worker._observe = Mock(return_value=("field", snap))
        worker._tap = Mock(return_value=True)
        with patch("workers.mumu_dead_flower_worker.time.monotonic", return_value=100):
            worker._service_once({0: 200}, True, False)
            worker._service_once({0: 200}, True, False)
        worker._tap.assert_called_once_with(MENU_POINT)

    def test_stale_frame_and_black_screen_do_not_trigger_input(self):
        worker, snap = self.worker()
        worker._press_key = Mock()
        worker._tap = Mock()
        snap["frame_age_ms"] = 500
        worker._service_once({}, False, False)
        worker._tap.assert_not_called()
        worker._press_key.assert_not_called()
        snap["frame_age_ms"] = 0
        self.assertEqual(worker.recognizer.scene(snap["frame"]), "unknown")

    def test_scene_confirmation_requires_new_frames(self):
        worker, snap = self.worker()
        worker.recognizer.scene = Mock(return_value="field")
        with patch("workers.mumu_dead_flower_worker.time.monotonic", side_effect=[1.0, 2.0]):
            self.assertIsNone(worker._observe()[0])
            self.assertIsNone(worker._observe()[0])
            snap["frame_sequence"] += 1
            self.assertEqual(worker._observe()[0], "field")

    def test_buff_double_press_failure_does_not_start_countdown(self):
        worker, _ = self.worker()
        worker.recognizer.scene = Mock(return_value="field")
        worker._press_key = Mock(side_effect=[True, False])
        due = {0: 0}
        with patch.object(worker._stop, "wait", return_value=False):
            self.assertFalse(worker._cast(worker._config, due))
        self.assertEqual(due, {0: 0})

    def test_two_buffs_double_pressed_with_independent_deadlines(self):
        worker, _ = self.worker()
        worker.update_config({"enabled": True, "random_behavior_enabled": False,
                              "buffs": [{"enabled": True, "key": "1", "duration": 270},
                                        {"enabled": True, "key": "2", "duration": 200}]})
        worker.recognizer.scene = Mock(return_value="field")
        worker._press_key = Mock(return_value=True)
        due = {}
        with patch.object(worker._stop, "wait", return_value=False) as wait:
            self.assertTrue(worker._cast(worker._config, due))
        self.assertEqual([call.args[0] for call in worker._press_key.call_args_list], ["1", "1", "2", "2"])
        self.assertGreater(due[0], due[1])
        self.assertTrue(any(1 <= call.args[0] <= 2 for call in wait.call_args_list))

    def test_touch_scales_to_device_resolution_and_stop_prevents_tap(self):
        worker, _ = self.worker()
        with patch("workers.mumu_dead_flower_worker.subprocess.run") as run:
            run.side_effect = [SimpleNamespace(returncode=0, stdout=b"Physical size: 1920x1080"),
                               SimpleNamespace(returncode=0)]
            self.assertTrue(worker._tap(MARKET_POINT))
            self.assertEqual(run.call_args.args[0][-2:], ["1728", "680"])
            worker._stop.set()
            self.assertFalse(worker._tap(MENU_POINT))
            self.assertEqual(run.call_count, 2)

    def test_portal_missing_or_wrong_layer_never_walks(self):
        worker, _ = self.worker()
        worker._navigation_observation = Mock(return_value=({}, SimpleNamespace(player_position=(40, 30))))
        worker._walk_to_portal = Mock()
        worker._press_key = Mock()
        worker._leave_step({"portal_anchor": (20, 75)})
        worker._walk_to_portal.assert_not_called()
        worker._press_key.assert_not_called()

    def test_small_downsampled_portal_is_not_filtered_out(self):
        minimap = np.zeros((82, 139, 3), np.uint8)
        minimap[68:79, 18:26] = (190, 150, 130)  # pale translucent blue
        minimap[30, 8] = (255, 160, 0)  # isolated decorative pixel
        portal = MumuDeadFlowerWorker._portal(SimpleNamespace(minimap_image=minimap))
        self.assertEqual(portal, (22, 73.5))

    def test_jump_recovery_uses_x_after_landing_even_when_marker_is_hidden_again(self):
        worker, _ = self.worker()
        worker._navigation_observation = Mock(return_value=({}, SimpleNamespace(player_position=None)))
        worker._find_position_with_jump = Mock(return_value=(40, 60))
        worker._walk_to_portal = Mock(return_value="estimated")
        worker._leave_step({"portal_anchor": (20, 75)})
        worker._find_position_with_jump.assert_called_once()
        worker._walk_to_portal.assert_called_once_with((20, 75), (40, 60))

    def test_panel_settings_countdown_and_modes_are_independent(self):
        dialog = EmulatorStreamDialog({"serial": "test", "vm_index": "2"})
        try:
            dialog.mode_tabs.setCurrentIndex(2)
            dialog._on_minimap_clicked(21, 75)
            self.assertEqual(dialog.dead_flower_panel.anchor, (21, 75))
            self.assertIsNone(dialog.smart_walk_anchor)
            self.assertIsNone(dialog.smoke_anchor)
            panel = dialog.dead_flower_panel
            panel.set_config({"enabled": False, "portal_anchor": (21, 75),
                              "buffs": [{"enabled": True, "key": "1", "duration": 270}]})
            dialog.smart_walk_enabled.setChecked(True)
            panel.enabled.setChecked(True)
            self.assertFalse(dialog.smart_walk_enabled.isChecked())
            panel.update_countdown({0: 198})
            self.assertEqual(panel.rows[0][4].text(), "198s")
            dialog.smoke_enabled.setChecked(True)
            self.assertFalse(panel.enabled.isChecked())
            self.assertEqual(panel.rows[0][4].text(), "--")
        finally:
            dialog.close()

    def test_persistence_keeps_dead_config_per_serial_but_always_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MumuSettingsStore(str(Path(directory) / "mumu.json"))
            store.save({"a": {"dead_flower": {"enabled": True, "portal_anchor": [21, 75]}},
                        "b": {"dead_flower": {"enabled": True, "portal_anchor": [50, 80]}}})
            loaded = store.load()
            self.assertEqual(loaded["a"]["dead_flower"]["portal_anchor"], [21, 75])
            self.assertEqual(loaded["b"]["dead_flower"]["portal_anchor"], [50, 80])
            self.assertFalse(loaded["a"]["dead_flower"]["enabled"])
            self.assertFalse(loaded["b"]["dead_flower"]["enabled"])

    def test_panel_clears_removed_deadlines_and_replaces_extra_slots(self):
        dialog = EmulatorStreamDialog({"serial": "test"})
        try:
            panel = dialog.dead_flower_panel
            panel.set_config({"enabled": True, "buffs": [
                {"enabled": True, "key": "1", "duration": 270}] * 5})
            panel.update_countdown({0: 200, 1: 190})
            panel.update_countdown({0: 199})
            self.assertEqual(panel.rows[1][4].text(), "--")
            panel.rows[0][2].setText("2")
            panel._emit()
            self.assertEqual(panel.rows[0][4].text(), "--")
            panel.set_config({"enabled": False, "buffs": []})
            self.assertEqual(len(panel.rows), 3)
        finally:
            dialog.close()

    def test_monitor_preserves_other_instances_and_stops_dead_on_live_start(self):
        with patch("workers.mumu_monitor_worker.resolve_mumu_cli_path", return_value=None):
            monitor = MumuMonitorWorker()
        try:
            a, b = Mock(), Mock()
            monitor._dead_flower_workers = {"a": a, "b": b}
            monitor._smart_walk_workers["a"] = Mock()
            monitor.update_smart_walk_config("a", {"enabled": True})
            a.stop.assert_called_once()
            b.stop.assert_not_called()
            monitor.stop()
            self.assertGreaterEqual(a.stop.call_count, 2)
            b.stop.assert_called_once()
        finally:
            monitor._analysis_executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()

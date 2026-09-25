import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from detection.emulator_frame_analysis import EmulatorFrameAnalysis
from ui.emulator_stream_dialog import EmulatorStreamDialog
from workers.mumu_monitor_worker import MumuMonitorWorker


class MumuMonitorWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_requests_redetection_for_its_stream(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        emitted = []
        dialog.redetect_minimap_requested.connect(emitted.append)

        dialog.redetect_button.click()

        self.assertEqual(emitted, ["127.0.0.1:16384"])
        dialog.close()

    def test_duplicate_adb_aliases_keep_mumu_manager_serial(self):
        devices = [
            {
                "serial": "emulator-5554",
                "state": "device",
                "model": "SM G9980",
                "boot_id": "same-boot",
            },
            {
                "serial": "127.0.0.1:16384",
                "state": "device",
                "model": "SM G9980",
                "boot_id": "same-boot",
            },
        ]

        result = MumuMonitorWorker._deduplicate_adb_aliases(
            devices, {"127.0.0.1:16384"}
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["serial"], "127.0.0.1:16384")

    def test_same_model_different_boots_are_not_merged(self):
        devices = [
            {"serial": "emulator-5554", "model": "SM G9980", "boot_id": "a"},
            {"serial": "emulator-5556", "model": "SM G9980", "boot_id": "b"},
        ]

        result = MumuMonitorWorker._deduplicate_adb_aliases(devices)

        self.assertEqual(len(result), 2)

    def test_dialog_displays_independent_buff_countdowns(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.buff_inputs[0][0].setChecked(True)
        dialog.buff_inputs[0][1].setText("1")
        dialog.buff_inputs[1][0].setChecked(True)
        dialog.buff_inputs[1][1].setText("2")
        dialog.smart_walk_enabled.setChecked(True)

        dialog.update_buff_countdown({0: 270, 1: 265})

        self.assertEqual(dialog.buff_countdown_labels[0].text(), "270s")
        self.assertEqual(dialog.buff_countdown_labels[1].text(), "265s")
        self.assertEqual(dialog.buff_countdown_labels[2].text(), "--")
        dialog.close()

    def test_turning_emulator_switch_off_and_on_shows_countdown_again(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.buff_inputs[0][0].setChecked(True)
        dialog.buff_inputs[0][1].setText("1")
        dialog.buff_inputs[1][0].setChecked(True)
        dialog.buff_inputs[1][1].setText("2")
        dialog.smart_walk_enabled.setChecked(True)
        dialog.update_buff_countdown({0: 188, 1: 90})

        dialog.smart_walk_enabled.setChecked(False)
        dialog.update_buff_countdown({})

        self.assertEqual(dialog.buff_countdown_labels[0].text(), "--")
        dialog.smart_walk_enabled.setChecked(True)
        self.assertEqual(dialog.buff_countdown_labels[0].text(), "188s")
        self.assertEqual(dialog.buff_countdown_labels[1].text(), "90s")
        dialog.close()

    def test_reenabling_one_buff_shows_its_saved_countdown(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.smart_walk_enabled.setChecked(True)
        dialog.buff_inputs[0][0].setChecked(True)
        dialog.buff_inputs[0][1].setText("1")
        dialog.buff_inputs[1][0].setChecked(True)
        dialog.buff_inputs[1][1].setText("2")
        dialog.update_buff_countdown({0: 188, 1: 90})

        dialog.buff_inputs[0][0].setChecked(False)
        dialog.update_buff_countdown({1: 80})

        self.assertEqual(dialog.buff_countdown_labels[0].text(), "--")
        self.assertEqual(dialog.buff_countdown_labels[1].text(), "80s")
        dialog.buff_inputs[0][0].setChecked(True)
        self.assertEqual(dialog.buff_countdown_labels[0].text(), "188s")
        self.assertEqual(dialog.buff_countdown_labels[1].text(), "80s")
        dialog.close()

    def test_restored_running_settings_show_countdown_immediately(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.set_smart_walk_config(
            {
                "enabled": True,
                "buffs": [
                    {"enabled": True, "key": "1", "duration": 270},
                    {"enabled": True, "key": "2", "duration": 200},
                ],
            }
        )

        dialog.update_buff_countdown({0: 150, 1: 40})

        self.assertTrue(dialog.smart_walk_enabled.isChecked())
        self.assertEqual(dialog.buff_countdown_labels[0].text(), "150s")
        self.assertEqual(dialog.buff_countdown_labels[1].text(), "40s")
        dialog.close()

    def test_default_window_shows_the_full_live_flower_page(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.show()
        self.app.processEvents()

        scroll = dialog.live_flower_scroll
        self.assertGreaterEqual(dialog.height(), 780)
        self.assertEqual(
            scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertTrue(all(row.height() >= 34 for row in dialog.buff_row_widgets))
        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)

        for _ in range(5):
            dialog._add_buff_row(emit_change=False)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        dialog.close()

    def test_dialog_exposes_horizontal_range_only(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )

        config = dialog.smart_walk_config()

        self.assertIn("half_width", config)
        self.assertNotIn("half_height", config)
        self.assertEqual(config["min_minutes"], 16)
        self.assertEqual(config["max_minutes"], 18)
        self.assertFalse(hasattr(dialog, "smart_walk_height_input"))
        dialog.close()

    def test_dialog_restores_dynamic_buff_slots_up_to_windows_limit(self):
        dialog = EmulatorStreamDialog(
            {"serial": "127.0.0.1:16384", "vm_index": "0"}
        )
        dialog.set_smart_walk_config(
            {
                "buffs": [
                    {"enabled": index < 2, "key": str(index + 1), "duration": 270}
                    for index in range(5)
                ]
            }
        )

        self.assertEqual(len(dialog.buff_inputs), 5)
        self.assertEqual(dialog.buff_inputs[4][1].text(), "5")
        self.assertTrue(all(not button.isHidden() for button in dialog.buff_remove_buttons))
        dialog.close()

    def test_analysis_task_reads_latest_frame_when_it_starts(self):
        worker = MumuMonitorWorker()
        serial = "127.0.0.1:16384"
        old_frame = np.zeros((20, 30, 3), dtype=np.uint8)
        newest_frame = np.full((20, 30, 3), 77, dtype=np.uint8)
        with worker._lock:
            worker._latest_frames[serial] = newest_frame
            worker._latest_frame_at[serial] = 10.0
            worker._recognition_generations[serial] = 0

        result = EmulatorFrameAnalysis(
            game_state="in_game",
            minimap_rect=(1, 1, 10, 10),
            has_game_evidence=True,
        )
        with patch(
            "workers.mumu_monitor_worker.analyze_known_emulator_minimap",
            return_value=result,
        ) as analyze:
            worker._analyze_latest_frame(
                serial,
                (1, 1, 10, 10),
                False,
                0,
            )

        self.assertIs(analyze.call_args.args[0], newest_frame)
        self.assertIsNot(analyze.call_args.args[0], old_frame)
        worker._analysis_executor.shutdown(wait=True, cancel_futures=True)

    def test_redetection_invalidates_locked_region_and_old_results(self):
        worker = MumuMonitorWorker()
        serial = "127.0.0.1:16384"
        with worker._lock:
            worker._minimap_rects[serial] = (8, 50, 200, 120)
            worker._latest_analysis[serial] = object()

        worker.request_minimap_redetection(serial)

        self.assertNotIn(serial, worker._minimap_rects)
        self.assertNotIn(serial, worker._latest_analysis)
        self.assertIn(serial, worker._force_full_analysis)
        self.assertEqual(worker._recognition_generations[serial], 1)
        worker._analysis_executor.shutdown(wait=True, cancel_futures=True)

    def test_locked_region_uses_fast_path_without_periodic_full_search(self):
        worker = MumuMonitorWorker()
        serial = "127.0.0.1:16384"
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        worker._running = True
        worker._minimap_rects[serial] = (1, 1, 10, 10)
        worker._last_analysis_at[serial] = 0.0
        worker._last_full_analysis_at[serial] = 0.0
        submitted = []

        with patch.object(
            worker._analysis_executor,
            "submit",
            side_effect=lambda *args: submitted.append(args),
        ):
            with patch("workers.mumu_monitor_worker.time.monotonic", return_value=100.0):
                worker._on_frame(serial, frame)

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0][2], (1, 1, 10, 10))
        self.assertFalse(submitted[0][3])
        worker._running = False
        worker._analysis_inflight.clear()
        worker._analysis_executor.shutdown(wait=True, cancel_futures=True)

    def test_stale_analysis_is_dropped_when_a_newer_frame_exists(self):
        worker = MumuMonitorWorker()
        serial = "127.0.0.1:16384"
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        with worker._lock:
            worker._latest_frames[serial] = frame
            worker._latest_frame_at[serial] = 10.0
            worker._recognition_generations[serial] = 0

        result = EmulatorFrameAnalysis(
            game_state="in_game",
            minimap_rect=(1, 1, 10, 10),
            has_game_evidence=True,
        )

        def analyze_and_receive_new_frame(*_args):
            with worker._lock:
                worker._latest_frame_at[serial] = 10.1
            return result

        with patch(
            "workers.mumu_monitor_worker.analyze_known_emulator_minimap",
            side_effect=analyze_and_receive_new_frame,
        ):
            with patch(
                "workers.mumu_monitor_worker.time.monotonic",
                side_effect=[10.0, 10.5],
            ):
                worker._analyze_latest_frame(
                    serial,
                    (1, 1, 10, 10),
                    False,
                    0,
                )

        self.assertNotIn(serial, worker._latest_analysis)
        self.assertEqual(worker._dropped_analysis[serial], 1)
        worker._analysis_executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()

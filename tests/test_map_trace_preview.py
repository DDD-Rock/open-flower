import os
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from models.map_topology import MapPlatform, MapTopology, NormalizedMapPoint
from ui.map_library_dialog import MapEditorDialog
from workers.map_trace_worker import MapTraceWorker


class MapTracePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.reference = np.full((80, 160, 3), 25, dtype=np.uint8)
        cv2.circle(self.reference, (15, 15), 3, (0, 255, 255), -1)
        self.topology = MapTopology(
            "实时采集地图", 160, 80,
            reference_bgr=self.reference.tobytes(),
            platforms=[MapPlatform([
                NormalizedMapPoint(0.1, 0.8), NormalizedMapPoint(0.9, 0.8),
            ])],
        )
        self.dialog = MapEditorDialog(self.topology, hwnd=101)
        self.addCleanup(self.dialog.close)
        self.information = self.patches.enter_context(
            patch("ui.map_library_dialog.QMessageBox.information")
        )
        self.patches.enter_context(patch("workers.map_trace_worker.MinimapMonitor"))
        self.workers = []

        def make_worker(*args):
            worker = MapTraceWorker(*args)
            worker.start = Mock()
            worker.stop = Mock()
            worker.wait = Mock(return_value=True)
            self.workers.append(worker)
            return worker

        self.patches.enter_context(
            patch("ui.map_library_dialog.MapTraceWorker", side_effect=make_worker)
        )

    def start_trace(self):
        self.dialog._toggle_trace()
        return self.workers[-1]

    @staticmethod
    def frame(point=None, size=(160, 80)):
        width, height = size
        image = np.full((height, width, 3), 25, dtype=np.uint8)
        if point is not None:
            cv2.circle(image, point, 3, (0, 255, 255), -1)
        return {"image": image, "player": point}

    def test_yellow_marker_moves_with_live_frames_and_leaves_a_trail(self):
        worker = self.start_trace()
        worker.frame_ready.emit(self.frame((40, 30)))
        first = self.dialog.canvas.pixmap().toImage()
        worker.frame_ready.emit(self.frame((80, 30)))
        second = self.dialog.canvas.pixmap().toImage()

        self.assertEqual(first.pixelColor(80, 60).getRgb()[:3], (255, 255, 0))
        self.assertEqual(second.pixelColor(160, 60).getRgb()[:3], (255, 255, 0))
        self.assertNotEqual(second.pixelColor(80, 60), first.pixelColor(80, 60))
        self.assertEqual(second.pixelColor(30, 30).getRgb()[:3], (25, 25, 25))
        self.assertEqual(self.dialog.canvas.player_position, (80.0, 30.0))
        self.assertEqual(self.dialog.canvas.trace_points, [(40.0, 30.0), (80.0, 30.0)])
        self.assertIn("有效样本 2", self.dialog.summary.text())
        self.assertIn("80.0, 30.0", self.dialog.summary.text())
        np.testing.assert_array_equal(self.dialog.image, self.reference)
        self.assertEqual(self.dialog.topology.reference_bgr, self.reference.tobytes())
        self.assertEqual(len(self.dialog.topology.platforms), 1)

    def test_live_frame_coordinates_match_the_reference_when_capture_size_differs(self):
        worker = self.start_trace()
        worker.frame_ready.emit(self.frame((160, 80), size=(320, 160)))

        self.assertEqual(self.dialog.trace_samples, [(80.0, 40.0)])
        self.assertEqual(self.dialog.canvas.player_position, (80.0, 40.0))
        self.assertEqual(self.dialog.canvas.pixmap().size().width(), 320)
        self.assertEqual(self.dialog.canvas.pixmap().size().height(), 160)

    def test_marker_loss_updates_the_image_and_does_not_record_a_stale_position(self):
        worker = self.start_trace()
        worker.frame_ready.emit(self.frame((40, 30)))
        worker.frame_ready.emit(self.frame())

        self.assertIsNone(self.dialog.canvas.player_position)
        self.assertEqual(self.dialog.trace_samples, [(40.0, 30.0)])
        self.assertIn("暂未识别到玩家黄点", self.dialog.summary.text())
        self.assertEqual(
            self.dialog.canvas.pixmap().toImage().pixelColor(80, 60).getRgb()[:3],
            (25, 25, 25),
        )

        worker.frame_ready.emit({"image": None, "player": None})
        self.assertIn("截图失败", self.dialog.summary.text())
        self.assertEqual(len(self.dialog.trace_samples), 1)
        worker.frame_ready.emit(self.frame((60, 30)))
        self.assertEqual(self.dialog.canvas.player_position, (60.0, 30.0))
        self.assertIn("有效样本 2", self.dialog.summary.text())

    def test_finishing_collection_builds_annotations_and_ignores_late_frames(self):
        worker = self.start_trace()
        for x in (30, 34, 38, 42, 46, 50):
            worker.frame_ready.emit(self.frame((x, 30)))

        self.dialog._toggle_trace()

        worker.stop.assert_called_once_with()
        worker.wait.assert_called_once_with(1500)
        self.assertEqual(len(self.dialog.topology.platforms), 2)
        self.assertAlmostEqual(self.dialog.topology.platforms[-1].points[0].x, 30 / 160)
        self.assertAlmostEqual(self.dialog.topology.platforms[-1].points[-1].x, 50 / 160)
        self.assertIsNone(self.dialog.trace_worker)
        self.assertEqual(self.dialog.canvas.trace_points, [])
        self.assertTrue(self.dialog.tool.isEnabled())
        worker.frame_ready.emit(self.frame((90, 30)))
        self.assertEqual(len(self.dialog.trace_samples), 6)
        self.assertIsNone(self.dialog.canvas.player_position)

    def test_new_collection_ignores_frames_from_the_previous_worker(self):
        first = self.start_trace()
        self.dialog._stop_trace()
        second = self.start_trace()

        first.frame_ready.emit(self.frame((20, 30)))
        first.finished.emit()
        second.frame_ready.emit(self.frame((70, 30)))

        self.assertIs(self.dialog.trace_worker, second)
        self.assertEqual(self.dialog.trace_samples, [(70.0, 30.0)])
        self.assertFalse(self.dialog.tool.isEnabled())

    def test_cancel_stops_collection_without_adding_annotations(self):
        worker = self.start_trace()
        worker.frame_ready.emit(self.frame((40, 30)))

        self.dialog.reject()

        worker.stop.assert_called_once_with()
        self.assertIsNone(self.dialog.trace_worker)
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(len(self.dialog.topology.platforms), 1)
        self.information.assert_not_called()


class MapTraceWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_background_capture_updates_the_editor_on_the_qt_event_loop(self):
        dialog = MapEditorDialog(MapTopology("线程预览", 160, 80), hwnd=101)
        self.addCleanup(dialog.close)
        with patch("workers.map_trace_worker.MinimapMonitor") as monitor_type:
            worker = MapTraceWorker(101, parent=dialog)
            dialog.trace_worker = worker
            dialog.canvas.trace_points = dialog.trace_samples
            frames = [MapTracePreviewTests.frame(point) for point in ((40, 30), (80, 30))]
            monitor_type.return_value.auto_detect_dark_region.return_value = (0, 0, 160, 80)

            def capture():
                frame = frames.pop(0)
                if not frames:
                    worker._running = False
                return frame["image"]

            monitor_type.return_value.capture_minimap.side_effect = capture
            monitor_type.find_player_position_in_image.side_effect = [
                ((40, 30), ""), ((80, 30), ""),
            ]
            worker.frame_ready.connect(dialog._on_trace_frame)
            loop = QEventLoop()
            worker.finished.connect(loop.quit)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(2000)
            worker.start()
            try:
                loop.exec()
            finally:
                timeout.stop()
                worker.stop()
                self.assertTrue(worker.wait(1500))

        self.assertEqual(dialog.trace_samples, [(40.0, 30.0), (80.0, 30.0)])
        self.assertEqual(dialog.canvas.player_position, (80.0, 30.0))
        monitor_type.return_value.close_capture.assert_called_once_with()

    def test_worker_emits_each_captured_frame_and_cleans_up_its_capture_session(self):
        with patch("workers.map_trace_worker.MinimapMonitor") as monitor_type:
            worker = MapTraceWorker(101)
        monitor = monitor_type.return_value
        monitor.auto_detect_dark_region.return_value = (0, 0, 160, 80)
        frames = [MapTracePreviewTests.frame(point) for point in ((40, 30), (80, 30), None)]
        monitor.capture_minimap.side_effect = [item["image"] for item in frames] + [None]
        monitor_type.find_player_position_in_image.side_effect = [
            ((40, 30), ""), ((80, 30), ""), (None, ""),
        ]
        received = []
        samples = []

        def receive(frame):
            received.append(frame)
            if len(received) == 4:
                worker._running = False

        worker.frame_ready.connect(receive)
        worker.sample_ready.connect(samples.append)
        with (
            patch("workers.map_trace_worker.MinimapMonitor", monitor_type),
            patch("workers.map_trace_worker.time.sleep"),
        ):
            worker.run()

        self.assertEqual([item["player"] for item in received], [(40, 30), (80, 30), None, None])
        self.assertIs(received[0]["image"], frames[0]["image"])
        self.assertIsNone(received[-1]["image"])
        self.assertEqual(samples, [(40.0, 30.0), (80.0, 30.0)])
        monitor.start_capture.assert_called_once_with()
        monitor.close_capture.assert_called_once_with()

    def test_capture_session_is_closed_if_detection_fails(self):
        with patch("workers.map_trace_worker.MinimapMonitor") as monitor_type:
            worker = MapTraceWorker(101)
        monitor_type.return_value.auto_detect_dark_region.return_value = None
        errors = []
        worker.error_signal.connect(errors.append)

        worker.run()

        self.assertEqual(errors, ["无法识别小地图"])
        monitor_type.return_value.close_capture.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

import copy
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton

from models.map_library import MapLibraryStore
from models.map_topology import MapPlatform, MapTopology, NormalizedMapPoint
from ui.map_library_dialog import MapLibraryDialog
from ui.modern_main_window import MainWindow


class MapLibraryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.store = MapLibraryStore(str(Path(self.directory.name) / "maps.json"))
        self.account = Mock()
        self.account.session_credentials.return_value = {"isSuperAdmin": True}
        self.selector = Mock()
        self.selector.is_window_valid.return_value = True
        self.selector.ensure_window_focus.return_value = True
        self.resolver = Mock(return_value=202)
        self.dialog = MapLibraryDialog(
            self.store,
            hwnd=101,
            window_selector=self.selector,
            account_manager=self.account,
            game_window_resolver=self.resolver,
        )
        self.addCleanup(self.dialog.close)
        self.monitor_type = self.patches.enter_context(
            patch("ui.map_library_dialog.MinimapMonitor")
        )
        self.monitor = self.monitor_type.return_value
        self.monitor.auto_detect_dark_region.return_value = (10, 20, 90, 50)
        self.image = np.full((50, 90, 3), 35, dtype=np.uint8)
        self.monitor.capture_minimap.return_value = self.image
        self.warning = self.patches.enter_context(
            patch("ui.map_library_dialog.QMessageBox.warning")
        )
        self.name_prompt = self.patches.enter_context(
            patch("ui.map_library_dialog.QInputDialog.getText", return_value=("地图一", True))
        )
        self.editor = self.patches.enter_context(patch("ui.map_library_dialog.MapEditorDialog"))

        def editor(topology, *_args, **_kwargs):
            return SimpleNamespace(
                topology=copy.deepcopy(topology),
                exec=Mock(return_value=QDialog.DialogCode.Accepted),
            )

        self.editor.side_effect = editor

    def test_admin_creates_map_without_monitoring(self):
        self.dialog.create_button.click()

        saved = self.store.load()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].map_name, "地图一")
        self.assertEqual((saved[0].reference_width, saved[0].reference_height), (90, 50))
        self.assertEqual(saved[0].reference_bgr, self.image.tobytes())
        self.resolver.assert_called_once_with()
        self.selector.ensure_window_focus.assert_called_once_with(202)
        self.monitor.set_window_handle.assert_called_once_with(202)
        self.assertEqual(self.editor.call_args.kwargs["hwnd"], 202)
        self.warning.assert_not_called()

    def test_each_creation_captures_the_current_map_again(self):
        self.dialog._create()
        next_image = np.full((65, 120, 3), 80, dtype=np.uint8)
        self.monitor.capture_minimap.return_value = next_image
        self.name_prompt.return_value = ("地图二", True)
        self.resolver.return_value = 303

        self.dialog._create()

        saved = self.store.load()
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0].reference_bgr, self.image.tobytes())
        self.assertEqual(saved[1].reference_bgr, next_image.tobytes())
        self.assertEqual((saved[1].reference_width, saved[1].reference_height), (120, 65))
        self.monitor.set_window_handle.assert_called_with(303)
        self.assertEqual(self.monitor.capture_minimap.call_count, 2)

    def test_existing_map_can_be_annotated_without_a_game_window(self):
        topology = MapTopology("已有地图", 90, 50, reference_bgr=self.image.tobytes())
        self.dialog.maps = [topology]
        self.dialog._reload()
        self.resolver.return_value = None

        def annotate(topology, *_args, **_kwargs):
            edited = copy.deepcopy(topology)
            edited.platforms.append(MapPlatform([
                NormalizedMapPoint(0.1, 0.5), NormalizedMapPoint(0.8, 0.5),
            ]))
            return SimpleNamespace(
                topology=edited,
                exec=Mock(return_value=QDialog.DialogCode.Accepted),
            )

        self.editor.side_effect = annotate
        self.dialog.edit_button.click()

        self.assertEqual(len(self.store.load()[0].platforms), 1)
        self.resolver.assert_not_called()
        self.monitor_type.assert_not_called()

    def test_missing_game_does_not_use_an_old_window_or_save_a_map(self):
        self.resolver.return_value = None

        self.dialog._create()

        self.warning.assert_called_once()
        self.assertIn("未找到游戏窗口", self.warning.call_args.args[2])
        self.monitor_type.assert_not_called()
        self.editor.assert_not_called()
        self.assertFalse(self.store.path.exists())

    def test_capture_failures_leave_the_library_unchanged(self):
        for failure in ("invalid_window", "focus", "region", "empty", "capture", "exception"):
            with self.subTest(failure=failure):
                self.selector.is_window_valid.return_value = failure != "invalid_window"
                self.selector.ensure_window_focus.return_value = failure != "focus"
                self.monitor.auto_detect_dark_region.return_value = (
                    None if failure == "region" else (10, 20, 90, 50)
                )
                self.monitor.capture_minimap.side_effect = (
                    RuntimeError("截图异常") if failure == "exception" else None
                )
                self.monitor.capture_minimap.return_value = (
                    None if failure == "capture"
                    else np.empty((0, 0, 3), dtype=np.uint8) if failure == "empty"
                    else self.image
                )
                self.warning.reset_mock()

                self.dialog._create()

                self.warning.assert_called_once()
                self.assertNotIn("启动监控", self.warning.call_args.args[2])
                self.editor.assert_not_called()
                self.assertFalse(self.store.path.exists())

    def test_cancelled_or_duplicate_name_does_not_capture(self):
        self.dialog.maps = [MapTopology("已有地图", 90, 50)]
        for answer in (("地图一", False), ("  ", True), ("已有地图", True)):
            with self.subTest(answer=answer):
                self.name_prompt.return_value = answer
                self.dialog._create()
                self.resolver.assert_not_called()
                self.monitor_type.assert_not_called()

    def test_cancelled_editor_does_not_save_a_map(self):
        self.editor.side_effect = None
        self.editor.return_value.exec.return_value = QDialog.DialogCode.Rejected

        self.dialog._create()

        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.dialog.maps, [])

    def test_regular_user_cannot_create_or_edit_maps(self):
        self.account.session_credentials.return_value = {"isSuperAdmin": False}
        dialog = MapLibraryDialog(self.store, account_manager=self.account)
        self.addCleanup(dialog.close)
        dialog.maps = [MapTopology("已有地图", 90, 50)]
        dialog._reload()

        dialog._create()
        dialog._edit()

        self.name_prompt.assert_not_called()
        self.monitor_type.assert_not_called()
        self.editor.assert_not_called()
        self.assertFalse(self.store.path.exists())

    def test_map_management_opens_without_a_monitor_panel(self):
        window = SimpleNamespace(
            map_library_store=self.store,
            game_window_hwnd=101,
            window_selector=self.selector,
            _ensure_game_window_available=Mock(return_value=True),
            account_manager=self.account,
            monitor_matched_topology=None,
        )
        with patch("ui.map_library_dialog.MapLibraryDialog") as dialog_type:
            MainWindow.on_manage_maps(window)

        dialog_type.return_value.exec.assert_called_once_with()
        resolver = dialog_type.call_args.kwargs["game_window_resolver"]
        window.game_window_hwnd = 303
        self.assertEqual(resolver(), 303)
        self.assertEqual(window.map_topologies, [])

    def test_map_management_stays_enabled_while_monitoring(self):
        window = Mock()
        window.remote_monitor_client = None
        manage_button = QPushButton()
        self.addCleanup(manage_button.close)
        window.monitor_panel.manage_maps_button = manage_button

        with patch("ui.modern_main_window.MonitorWorker") as worker_type:
            MainWindow._start_monitor_worker(window)

        worker_type.return_value.start.assert_called_once_with()
        self.assertTrue(manage_button.isEnabled())


if __name__ == "__main__":
    unittest.main()

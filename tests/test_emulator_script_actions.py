import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from ui.emulator_panel import EmulatorPanel, EmulatorRow
from ui.emulator_stream_dialog import EmulatorStreamDialog
from ui.modern_main_window import MainWindow
from utils.mumu_settings import MumuSettingsStore


class ScriptActionsHarness(QWidget):
    _emulator_script_mode = staticmethod(MainWindow._emulator_script_mode)
    _refresh_emulator_script_button = MainWindow._refresh_emulator_script_button
    _toggle_emulator_script = MainWindow._toggle_emulator_script
    _restore_emulator_dialog_config = MainWindow._restore_emulator_dialog_config
    _update_emulator_dead_config = MainWindow._update_emulator_dead_config
    _update_emulator_smart_walk_config = MainWindow._update_emulator_smart_walk_config
    _update_emulator_smoke_config = MainWindow._update_emulator_smoke_config
    _on_emulator_smoke_finished = MainWindow._on_emulator_smoke_finished
    _on_emulator_devices = MainWindow._on_emulator_devices


class EmulatorScriptActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.owner = ScriptActionsHarness()
        self.owner.emulator_worker = Mock()
        self.owner.emulator_panel = EmulatorPanel()
        self.owner.emulator_panel.set_running(True)
        self.owner._emulator_smart_walk_configs = {
            "a": {"active_mode": "dead_flower", "dead_flower": {
                "enabled": False, "buffs": [{"enabled": True, "key": "1", "duration": 270}]}},
            "b": {"enabled": False, "active_mode": "live_flower", "buffs": [
                {"enabled": True, "key": "2", "duration": 300}]},
        }
        self.owner._emulator_settings_dialogs = {}
        self.owner._emulator_dead_countdowns = {}
        self.owner._emulator_live_countdowns = {}
        self.owner._mumu_settings_store = MumuSettingsStore(str(Path(self.directory.name) / "mumu.json"))
        self.devices = [{"id": serial, "serial": serial, "vm_index": str(index), "state": "device"}
                        for index, serial in enumerate(("a", "b", "c"))]
        self.owner.emulator_panel.script_requested.connect(self.owner._toggle_emulator_script)
        self.owner._on_emulator_devices(self.devices)

    def tearDown(self):
        for dialog in self.owner._emulator_settings_dialogs.values():
            dialog.close()
        self.owner.emulator_panel.close()
        self.owner.close()
        self.directory.cleanup()

    def row(self, serial):
        return self.owner.emulator_panel._rows[serial][1]

    def test_offline_action_is_explicit_and_script_requires_configuration(self):
        row = EmulatorRow()
        row.update_metadata(1, {"vm_index": "0", "state": "offline"})
        row.set_controls_enabled(True)
        launched = []
        row.start_requested.connect(launched.append)
        self.assertEqual(row.start_button.text(), "开启模拟器")
        row.start_button.click()
        self.assertEqual(launched, ["0"])
        self.assertTrue(self.row("c").script_button.isHidden())
        self.assertFalse(self.row("a").script_button.isHidden())
        self.assertEqual(self.row("a").start_button.text(), "设置")
        row.close()

    def test_list_start_stop_uses_correct_instance_and_does_not_launch_emulator(self):
        button = self.row("a").script_button
        button.click()
        self.assertEqual(button.text(), "停止脚本")
        saved = self.owner._emulator_smart_walk_configs
        self.assertTrue(saved["a"]["dead_flower"]["enabled"])
        self.assertFalse(saved["b"]["enabled"])
        self.owner.emulator_worker.update_dead_flower_config.assert_called_with("a", saved["a"]["dead_flower"])
        self.owner.emulator_worker.request_launch.assert_not_called()
        self.assertFalse(self.owner._mumu_settings_store.load()["a"]["dead_flower"]["enabled"])
        button.click()
        self.assertEqual(button.text(), "启动脚本")
        self.assertFalse(self.owner._emulator_smart_walk_configs["a"]["dead_flower"]["enabled"])

    def test_open_settings_and_list_remain_in_sync_without_extra_controller_actions(self):
        dialog = EmulatorStreamDialog({"serial": "a"})
        self.owner._emulator_settings_dialogs["a"] = dialog
        dialog.dead_flower_config_changed.connect(self.owner._update_emulator_dead_config)
        self.owner._restore_emulator_dialog_config(dialog, self.owner._emulator_smart_walk_configs["a"])
        self.row("a").script_button.click()
        self.assertTrue(dialog.dead_flower_panel.enabled.isChecked())
        dialog.dead_flower_panel.enabled.setChecked(False)
        self.assertEqual(self.row("a").script_button.text(), "启动脚本")
        dialog.dead_flower_panel.enabled.setChecked(True)
        self.assertEqual(self.row("a").script_button.text(), "停止脚本")
        self.row("a").script_button.click()
        self.assertFalse(dialog.dead_flower_panel.enabled.isChecked())

    def test_live_and_smoke_configs_can_start_and_smoke_completion_resets_button(self):
        self.row("b").script_button.click()
        self.assertTrue(self.owner._emulator_smart_walk_configs["b"]["enabled"])
        self.row("b").script_button.click()
        config = {"enabled": False, "friend_name": "friend", "anchor": [20, 30],
                  "coordinate_space": "scrcpy_960x540", "smoke_key": "Shift"}
        self.owner._update_emulator_smoke_config("b", config)
        self.owner._emulator_smart_walk_configs["b"]["active_mode"] = "smoke"
        self.row("b").script_button.click()
        self.owner.emulator_worker.update_smoke_config.assert_called_with("b", {**config, "enabled": True})
        self.assertEqual(self.row("b").script_button.text(), "停止脚本")
        self.owner._on_emulator_smoke_finished("b", True)
        self.assertEqual(self.row("b").script_button.text(), "启动脚本")

    def test_disconnected_and_disabled_monitor_do_not_allow_start(self):
        self.owner._emulator_devices_snapshot[0]["state"] = "offline"
        self.owner._toggle_emulator_script("a")
        self.owner.emulator_worker.request_launch.assert_not_called()
        self.assertFalse(self.owner._emulator_smart_walk_configs["a"]["dead_flower"]["enabled"])
        self.owner.emulator_panel.set_running(False)
        self.assertFalse(self.row("a").script_button.isEnabled())

    def test_active_tab_alone_does_not_count_as_script_configuration(self):
        self.assertIsNone(MainWindow._emulator_script_mode({"active_mode": "dead_flower", "enabled": False}))

    def test_saving_new_settings_exposes_button_without_waiting_for_scan(self):
        self.owner._update_emulator_dead_config("c", {"enabled": False, "buffs": [
            {"enabled": True, "key": "3", "duration": 270}]})
        self.assertFalse(self.row("c").script_button.isHidden())
        self.assertEqual(self.row("c").script_button.text(), "启动脚本")


if __name__ == "__main__":
    unittest.main()

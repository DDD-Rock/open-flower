import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from detection.emulator_smoke_recognizer import online_friend, together_action
from ui.emulator_stream_dialog import EmulatorStreamDialog
from workers.mumu_smoke_worker import MumuSmokeWorker, SmokeError


def block(text, x, y):
    return {"text": text, "box": [[x, y], [x + 30, y], [x + 30, y + 20], [x, y + 20]]}


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_online_friend_allows_one_missing_ocr_character(self):
        blocks = [block("QQNeNe好喝到噗茶", 100, 100), block("正在游戏", 100, 130),
                  block("QQNeNe好喝到咩噗茶", 100, 300), block("离线", 100, 330)]
        self.assertEqual(online_friend(blocks, "QQNeNe好喝到咩噗茶"), (115, 110))
        self.assertIsNone(online_friend(blocks + [block("QQNeNe好喝到咩噗茶", 100, 140),
                                                  block("正在游戏", 100, 170)], "QQNeNe好喝到咩噗茶"))
        self.assertIsNone(online_friend([block("QQNeNe好喝到其他茶", 100, 100)],
                                        "QQNeNe好喝到咩噗茶"))

    def test_online_friend_allows_two_missing_stream_ocr_characters(self):
        blocks = [block("QQNeNe好喝到茶", 100, 100), block("正在游戏", 100, 130)]
        self.assertEqual(online_friend(blocks, "QQNeNe好喝到咩噗茶"), (115, 110))

    def test_together_action_requires_unique_item(self):
        self.assertEqual(together_action([block("一起畅游游戏", 180, 650)]), (195, 660))
        self.assertIsNone(together_action([block("一起玩", 100, 100), block("一起畅游游戏", 100, 150)]))

    def test_dialog_smoke_marker_and_mutual_exclusion(self):
        dialog = EmulatorStreamDialog({"serial": "127.0.0.1:16384", "vm_index": "0"})
        try:
            dialog.mode_tabs.setCurrentIndex(1)
            dialog._on_minimap_clicked(145, 56)
            dialog.smoke_friend_input.setText("QQNeNe好喝到咩噗茶")
            self.assertEqual(dialog.smoke_config()["anchor"], (145, 56))
            self.assertEqual(dialog.smoke_config()["coordinate_space"], "scrcpy_960x540")
            dialog.smart_walk_enabled.setChecked(True)
            dialog.smoke_enabled.setChecked(True)
            self.assertFalse(dialog.smart_walk_enabled.isChecked())
            self.assertTrue(dialog.smoke_enabled.isChecked())
        finally:
            dialog.close()

    def test_old_full_resolution_marker_is_converted_to_stream_coordinates(self):
        dialog = EmulatorStreamDialog({"serial": "test", "vm_index": "0"})
        try:
            dialog.set_smoke_config({"anchor": (145, 56), "half_width": 6,
                                     "half_height": 4})
            self.assertEqual(dialog.smoke_config()["anchor"], (72, 28))
            self.assertEqual(dialog.smoke_config()["half_width"], 3)
            self.assertEqual(dialog.smoke_config()["half_height"], 2)
        finally:
            dialog.close()

    def test_stream_tap_converts_to_native_adb_coordinates(self):
        worker = MumuSmokeWorker("test", "adb", Mock(return_value={
            "frame_age_ms": 0, "frame": np.zeros((540, 960, 3), dtype=np.uint8),
        }), Mock())
        with patch("workers.mumu_smoke_worker.subprocess.run") as run:
            run.side_effect = [SimpleNamespace(returncode=0, stdout=b"Physical size: 1920x1080"),
                               SimpleNamespace(returncode=0)]
            worker._tap((882, 36), "社交入口")
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["1764", "72"])

    def test_no_tap_when_stopped(self):
        worker = MumuSmokeWorker("test", "adb", Mock(), Mock())
        worker._stop.set()
        with self.assertRaisesRegex(SmokeError, "用户已停止"):
            worker._tap((1765, 73), "社交入口")

    def test_loading_wait_has_no_deadline_but_can_be_stopped(self):
        worker = MumuSmokeWorker("test", "adb", Mock(return_value={"frame_age_ms": 0}), Mock())
        predicate = Mock(side_effect=lambda _: worker._stop.set())
        with self.assertRaisesRegex(SmokeError, "用户已停止"):
            worker._wait_for(predicate, None, "等待登录页面", poll=0)
        predicate.assert_called_once()

    def test_login_keeps_clicking_until_page_disappears(self):
        worker = MumuSmokeWorker(
            "test", "adb", Mock(return_value={"frame_age_ms": 0}), Mock(),
        )
        worker._text = Mock(side_effect=[
            [block("密码", 100, 100)], [block("密码", 100, 100)],
            [block("登入", 100, 100)], [], [],
        ])
        worker._tap = Mock()
        with patch.object(worker._stop, "wait", return_value=False):
            worker._tap_until_page_disappears(
                worker.LOGIN_EVIDENCE, worker.LOGIN_POINT, "登录",
            )
        self.assertEqual(worker._tap.call_count, 2)
        worker._tap.assert_called_with(worker.LOGIN_POINT, "登录")

    def test_character_page_keeps_clicking_until_it_disappears(self):
        worker = MumuSmokeWorker(
            "test", "adb", Mock(return_value={"frame_age_ms": 0}), Mock(),
        )
        worker._text = Mock(side_effect=[
            [block("新建角色", 100, 100)], [block("新建角色", 100, 100)],
            [], [],
        ])
        worker._tap = Mock()
        with patch.object(worker._stop, "wait", return_value=False):
            worker._login_to_character()
        self.assertEqual(worker._tap.call_count, 2)
        worker._tap.assert_called_with(worker.CHARACTER_POINT, "进入角色")

    @staticmethod
    def _blind_start_worker():
        snapshot = {
            "frame_age_ms": 0,
            "analysis_age_ms": 0,
            "frame": object(),
            "analysis": SimpleNamespace(player_position=None),
        }
        worker = MumuSmokeWorker("test", "adb", Mock(return_value=snapshot), Mock())
        worker._down_jump = Mock()
        return worker

    @staticmethod
    def _anchor_config():
        return {"anchor": (73, 28), "half_width": 3, "half_height": 2,
                "jump_key": "Alt"}

    def test_missing_marker_jumps_until_the_marker_returns(self):
        worker = self._blind_start_worker()
        worker._position = Mock(side_effect=[None, (73, 28)])
        worker._key = Mock()
        with patch.object(worker._stop, "wait", return_value=False):
            self.assertEqual(worker._locate_position("Alt"), (73, 28))
        worker._key.assert_called_once_with("Alt")

    def test_missing_marker_after_drop_keeps_down_jumping(self):
        worker = self._blind_start_worker()
        worker._position = Mock(side_effect=[None, None, (73, 28)])
        with patch.object(worker._stop, "wait", return_value=False):
            self.assertEqual(worker._locate_position("Alt", down=True), (73, 28))
        self.assertEqual(worker._down_jump.call_count, 2)

    def test_missing_friend_prevents_any_input(self):
        worker = MumuSmokeWorker("test", "adb", Mock(), Mock(), finished_callback=Mock())
        worker._move_to_anchor = Mock()
        worker._run({"anchor": (145, 56), "friend_name": ""})
        worker._move_to_anchor.assert_not_called()
        worker.finished_callback.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()

"""地图动作组合测试 Worker，始终在结束时释放所有方向键。"""

import random
import time

from PyQt6.QtCore import QThread, pyqtSignal
from pynput.keyboard import Key

from automation.human_input import HumanInput


class MapActionWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        action: str,
        jump_key="Alt",
        hwnd=None,
        window_selector=None,
        parent=None,
    ):
        super().__init__(parent)
        self.action = action
        self.jump_key = jump_key
        self.hwnd = hwnd
        self.window_selector = window_selector
        self.human = HumanInput()
        self._running = True

    def stop(self):
        self._running = False
        self.requestInterruption()
        self.human.release_all()

    def run(self):
        try:
            if self.window_selector and not self.window_selector.ensure_window_focus(
                self.hwnd
            ):
                raise RuntimeError("无法激活游戏窗口")
            self.log_update.emit(f"开始动作测试：{self.action}")
            if self.action == "walk_left":
                self._hold_direction("left", 2.0)
            elif self.action == "walk_right":
                self._hold_direction("right", 2.0)
            elif self.action == "climb_up":
                self._hold_direction("up", 2.0)
            elif self.action == "climb_down":
                self._hold_direction("down", 2.0)
            elif self.action == "enter_rope":
                self._hold_direction("down", random.uniform(0.85, 1.15))
            elif self.action == "drop":
                self._drop()
            elif self.action in {"walk_off_left", "walk_off_right"}:
                self._hold_direction(
                    "left" if self.action.endswith("left") else "right",
                    random.uniform(0.85, 1.15),
                )
            elif self.action in {"jump_rope_left", "jump_rope_right"}:
                self._jump_rope("left" if self.action.endswith("left") else "right")
            elif self.action in {"dismount_left", "dismount_right"}:
                self._dismount("left" if self.action.endswith("left") else "right")
            elif self.action == "portal":
                self.human.use_portal()
        except Exception as error:
            self.error_signal.emit(str(error))
        finally:
            self.human.release_all()
            self.log_update.emit("动作测试结束，已释放全部方向键")

    def _hold_direction(self, direction, seconds):
        self.human._change_direction(direction)
        self._sleep(seconds)
        self.human.stop_move()

    def _drop(self):
        jump = self._jump_key()
        self.human.keyboard.press(Key.down)
        self._sleep(random.uniform(0.08, 0.14))
        self.human.keyboard.press(jump)
        self._sleep(random.uniform(0.08, 0.13))
        self.human.keyboard.release(Key.down)
        self._sleep(random.uniform(0.03, 0.07))
        self.human.keyboard.release(jump)

    def _jump_rope(self, direction):
        jump = self._jump_key()
        direction_key = Key.left if direction == "left" else Key.right
        self.human.keyboard.press(direction_key)
        self._sleep(random.uniform(0.08, 0.13))
        self.human.keyboard.press(jump)
        self._sleep(random.uniform(0.10, 0.16))
        self.human.keyboard.press(Key.up)
        self._sleep(random.uniform(0.12, 0.2))
        self.human.keyboard.release(jump)
        self.human.keyboard.release(direction_key)
        self._sleep(random.uniform(0.06, 0.1))
        self.human.keyboard.release(Key.up)

    def _dismount(self, direction):
        jump = self._jump_key()
        direction_key = Key.left if direction == "left" else Key.right
        self.human.keyboard.press(direction_key)
        self._sleep(random.uniform(0.045, 0.115))
        self.human.keyboard.press(jump)
        jump_hold = random.uniform(0.07, 0.14)
        self._sleep(jump_hold)
        self.human.keyboard.release(jump)
        self._sleep(random.uniform(0.025, 0.08))
        self.human.keyboard.release(direction_key)

    def _jump_key(self):
        normalized = str(self.jump_key).strip().lower()
        return {
            "alt": Key.alt,
            "ctrl": Key.ctrl,
            "shift": Key.shift,
            "space": Key.space,
        }.get(normalized, normalized[:1] or Key.alt)

    def _sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.02, deadline - time.monotonic()))

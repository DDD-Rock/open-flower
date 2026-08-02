"""神殿挂绳组队第一阶段：队长首次建队邀请，成员等待邀请。"""

from __future__ import annotations

import random
import time

from PyQt6.QtCore import QThread, pyqtSignal

from automation.human_input import HumanInput
from utils.window_selector import WindowSelector
from utils.rope_party import build_rope_party_commands


class RopePartyWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, hwnd: int, is_leader: bool, first_creation: bool, invite_role_names: list[str], disband_only: bool = False):
        super().__init__()
        self.hwnd = hwnd
        self.is_running = True
        self.disband_only = disband_only
        self.commands = ["/退出隊伍"] if disband_only else build_rope_party_commands(is_leader, first_creation, invite_role_names)
        self.human = HumanInput()
        self.window_selector = WindowSelector()

    def run(self):
        try:
            self.log_update.emit("收到网页解散队伍指令" if self.disband_only else "神殿模式 · 挂绳组队启动")
            if self.commands:
                if not self.window_selector.bring_window_to_front(self.hwnd):
                    self.error_signal.emit("发送队伍指令前无法激活游戏窗口")
                    return
                self._sleep(random.uniform(0.2, 0.45))
                for index, command in enumerate(self.commands):
                    if not self.is_running or self.isInterruptionRequested():
                        return
                    self._send_chat_command(command)
                    self.log_update.emit(f"已发送队伍指令：{command}")
                    if index < len(self.commands) - 1:
                        self._sleep(random.uniform(0.55, 1.15))
                self.log_update.emit("已发送解散队伍指令：/退出隊伍" if self.disband_only else "首次建队指令已发送完毕")
            else:
                self.log_update.emit("等待并自动接受队伍邀请")
            if self.disband_only:
                return
            while self.is_running and not self.isInterruptionRequested():
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已失效，挂绳组队已停止")
                    break
                self._sleep(1.0)
        except Exception as exc:
            self.error_signal.emit(f"挂绳组队出错：{exc}")
        finally:
            self.is_running = False
            self.human.release_all()
            self.finished_signal.emit()

    def _send_chat_command(self, command: str):
        self.human.press_enter()
        self._sleep(random.uniform(0.18, 0.42))
        self.human.type_text(command)
        self._sleep(random.uniform(0.12, 0.32))
        self.human.press_enter()

    def _sleep(self, seconds: float):
        deadline = time.monotonic() + seconds
        while self.is_running and not self.isInterruptionRequested() and time.monotonic() < deadline:
            time.sleep(min(0.1, deadline - time.monotonic()))

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        if self.isRunning():
            self.wait()

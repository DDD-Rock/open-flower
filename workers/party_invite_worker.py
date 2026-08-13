"""Independent worker that accepts party invitations while the app is open."""

from __future__ import annotations

import random
import time

from PyQt6.QtCore import QThread, pyqtSignal

from automation.human_input import HumanInput, input_transaction_lock
from detection.party_invite_detector import PartyInviteDetector
from utils.window_selector import WindowSelector


class PartyInviteWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    invite_accepted = pyqtSignal()

    def __init__(self, hwnd: int):
        super().__init__()
        self.hwnd = hwnd
        self.is_running = True
        self.detector = PartyInviteDetector(hwnd)
        self.human = HumanInput()
        self.window_selector = WindowSelector()

    def run(self):
        try:
            pending_point = None
            while self.is_running and not self.isInterruptionRequested():
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已失效，自动同意组队已停止")
                    break

                point = self.detector.find_accept_button()
                if point is None:
                    pending_point = None
                    self._sleep(random.uniform(1.0, 2.0))
                    continue

                # 连续两帧在近似位置都匹配成功后才点击，避免场景切换和动画帧
                # 造成瞬时误识别。
                if pending_point is None or (
                    abs(point[0] - pending_point[0]) > 12
                    or abs(point[1] - pending_point[1]) > 12
                ):
                    pending_point = point
                    self._sleep(random.uniform(0.25, 0.45))
                    continue

                pending_point = None
                self._accept_invite(point)
                self._sleep(random.uniform(4.0, 7.0))
        except Exception as exc:
            self.error_signal.emit(f"自动同意组队出错: {exc}")
        finally:
            self.is_running = False
            self.finished_signal.emit()

    def _accept_invite(self, initial_point):
        with input_transaction_lock:
            self.log_update.emit("检测到队伍邀请，自动同意")
            if not self.window_selector.bring_window_to_front(self.hwnd):
                self.log_update.emit("无法将游戏窗口置于前台，仍会尝试同意组队")
            self._sleep(0.15)

            self.human.click_at(initial_point[0], initial_point[1], offset_range=2)
            for _ in range(14):
                if not self.is_running or self.isInterruptionRequested():
                    return
                self._sleep(0.15)
                if self.detector.find_accept_button() is None:
                    self.log_update.emit("已同意队伍邀请")
                    self.invite_accepted.emit()
                    return
            self.log_update.emit("邀请弹窗点击后仍未消失，本次不报告入队成功")

    def _sleep(self, seconds: float):
        deadline = time.monotonic() + seconds
        while self.is_running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        if self.isRunning():
            self.wait()

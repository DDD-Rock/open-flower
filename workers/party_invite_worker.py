"""Independent worker that accepts party invitations while the app is open."""

from __future__ import annotations

import random
import time

from PyQt6.QtCore import QThread, pyqtSignal

from automation.human_input import HumanInput
from detection.party_invite_detector import PartyInviteDetector
from utils.window_selector import WindowSelector


class PartyInviteWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, hwnd: int):
        super().__init__()
        self.hwnd = hwnd
        self.is_running = True
        self.detector = PartyInviteDetector(hwnd)
        self.human = HumanInput()
        self.window_selector = WindowSelector()

    def run(self):
        try:
            scan_count = 0
            while self.is_running and not self.isInterruptionRequested():
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已失效，自动同意组队已停止")
                    break

                point = self.detector.find_accept_button(
                    include_template=scan_count % 3 == 0
                )
                scan_count += 1
                if point is None:
                    self._sleep(random.uniform(1.0, 2.0))
                    continue

                self._accept_invite(point)
                self._sleep(random.uniform(4.0, 7.0))
        except Exception as exc:
            self.error_signal.emit(f"自动同意组队出错: {exc}")
        finally:
            self.is_running = False
            self.finished_signal.emit()

    def _accept_invite(self, initial_point):
        self.log_update.emit("检测到队伍邀请，自动同意")
        if not self.window_selector.bring_window_to_front(self.hwnd):
            self.log_update.emit("无法将游戏窗口置于前台，仍会尝试同意组队")
        self._sleep(0.15)

        point = initial_point
        for attempt in range(2):
            if not self.is_running or self.isInterruptionRequested():
                return
            if attempt > 0:
                refreshed = self.detector.find_accept_button()
                if refreshed is not None:
                    point = refreshed
            self.human.click_at(point[0], point[1], offset_range=2)
            self._sleep(0.3)
            if self.detector.find_accept_button() is None:
                self.log_update.emit("已同意队伍邀请")
                return

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

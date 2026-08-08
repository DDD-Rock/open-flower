"""Windows 神殿休息室：人数增加触发 BUFF、喊话与定时防卡。"""

from __future__ import annotations

import random
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from automation.human_input import HumanInput, input_transaction_lock
from detection.minimap_monitor import MinimapMonitor
from utils.keyboard_utils import press_key
from utils.lounge import LoungeAnnouncementPicker, LoungeMarkerCounts, LoungePopulationTracker
from utils.window_selector import WindowSelector


class LoungeWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, hwnd: int, buffs: list, move_min_minutes: int, move_max_minutes: int):
        super().__init__()
        self.hwnd = hwnd
        self.buffs = [buff for buff in buffs if buff.enabled and buff.key]
        self.move_min_minutes = max(1, min(1440, int(move_min_minutes)))
        self.move_max_minutes = max(self.move_min_minutes, min(1440, int(move_max_minutes)))
        self.is_running = True
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.window_selector = WindowSelector()
        self.human = HumanInput()
        self.announcements = LoungeAnnouncementPicker()
        self._trigger_lock = threading.Lock()
        self._party_accepted_triggers = 0

    def party_invite_accepted(self):
        if not self.is_running:
            return
        with self._trigger_lock:
            self._party_accepted_triggers += 1
        self.log_update.emit("自动接受组队成功，已加入一次 BUFF 释放队列")

    def run(self):
        try:
            if not self.buffs:
                self.error_signal.emit("没有可运行的 BUFF 配置")
                return
            self.log_update.emit("神殿模式 · 休息室启动")
            if not self.window_selector.bring_window_to_front(self.hwnd):
                self.log_update.emit("警告：无法将游戏窗口置于前台")
            self._sleep(0.5)
            self.log_update.emit("首次启动，立即释放一轮 BUFF")
            self._cast_buffs_and_announce()
            if not self.is_running:
                return
            if self.monitor.auto_detect_dark_region() is None:
                self.error_signal.emit(f"未识别到小地图：{self.monitor.last_detection_summary}")
                return

            tracker = LoungePopulationTracker()
            next_movement_at = self._next_movement_deadline()
            last_capture_error_at = 0.0
            self.log_update.emit(
                f"防卡移动间隔：{self.move_min_minutes}～{self.move_max_minutes} 分钟"
            )
            while self.is_running and not self.isInterruptionRequested():
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已关闭或不可见")
                    return
                if self._consume_party_trigger():
                    self.log_update.emit("自动接受组队触发，释放一轮 BUFF")
                    self._cast_buffs_and_announce()
                    if not self.is_running:
                        break

                frame = self.monitor.capture_minimap()
                if frame is None:
                    now = time.time()
                    if now - last_capture_error_at >= 10:
                        self.log_update.emit("警告：小地图读取失败，将继续重试")
                        last_capture_error_at = now
                else:
                    counts = LoungeMarkerCounts(
                        yellow=MinimapMonitor.count_player_marker_candidates_in_image(frame),
                        orange=len(MinimapMonitor.find_teammate_positions_in_image(frame)),
                    )
                    change = tracker.observe(counts)
                    if change is not None:
                        self.log_update.emit(
                            "休息室人数变化："
                            f"黄点 {change.previous.yellow}、橙点 {change.previous.orange} → "
                            f"黄点 {change.current.yellow}、橙点 {change.current.orange}"
                        )
                        if change.increased:
                            self._cast_buffs_and_announce()

                if time.time() >= next_movement_at:
                    self._perform_anti_stuck_movement()
                    next_movement_at = self._next_movement_deadline()
                self._sleep(1.0)
        except Exception as exc:
            self.error_signal.emit(f"休息室运行出错：{exc}")
        finally:
            self.is_running = False
            self.human.release_all()
            self.log_update.emit("神殿模式 · 休息室已停止")
            self.finished_signal.emit()

    def _consume_party_trigger(self):
        with self._trigger_lock:
            if self._party_accepted_triggers <= 0:
                return False
            self._party_accepted_triggers -= 1
            return True

    def _cast_buffs_and_announce(self):
        if not self._ensure_focus("释放休息室 BUFF"):
            return
        self.log_update.emit(f"释放 {len(self.buffs)} 个 BUFF")
        for index, buff in enumerate(self.buffs):
            if not self.is_running or self.isInterruptionRequested():
                return
            try:
                self.log_update.emit(f"释放 BUFF：{buff.key}")
                press_key(buff.key)
                self._sleep(random.uniform(0.1, 0.3))
                press_key(buff.key)
            except Exception as exc:
                self.error_signal.emit(f"BUFF {buff.key} 失败：{exc}")
            if index < len(self.buffs) - 1:
                self._sleep(random.uniform(2.0, 3.0))
        if not self.is_running:
            return
        self._sleep(random.uniform(0.25, 0.6))
        self._send_chat_message("/隊伍")
        self._sleep(random.uniform(0.35, 0.8))
        announcement = self.announcements.next()
        clock_time = time.strftime("%H:%M", time.localtime())
        self._send_chat_message(announcement, suffix=clock_time)
        self.log_update.emit(f"已发送：{announcement} {clock_time}")

    def _send_chat_message(self, message: str, suffix: str = ""):
        with input_transaction_lock:
            if not self.is_running:
                return
            self.human.press_enter()
            self._sleep(random.uniform(0.18, 0.42))
            self.human.press_delete()
            self._sleep(random.uniform(0.08, 0.18))
            self.human.type_text(message)
            self._sleep(random.uniform(0.12, 0.32))
            if suffix:
                press_key("space")
                self._sleep(random.uniform(0.08, 0.18))
                self.human.type_text(suffix)
                self._sleep(random.uniform(0.12, 0.32))
            self.human.press_enter()

    def _perform_anti_stuck_movement(self):
        if not self._ensure_focus("防卡移动"):
            return
        self.log_update.emit("执行防卡移动：短暂向右，再短暂向左")
        self.human.tap_direction("right", (120, 260))
        self._sleep(random.uniform(0.08, 0.22))
        if self.is_running:
            self.human.tap_direction("left", (120, 260))

    def _next_movement_deadline(self):
        selected = random.randint(self.move_min_minutes, self.move_max_minutes)
        self.log_update.emit(f"下次防卡移动约在 {selected} 分钟后")
        return time.time() + selected * 60

    def _ensure_focus(self, reason: str):
        if self.window_selector.is_window_foreground(self.hwnd):
            return True
        for attempt in range(1, 25):
            if not self.is_running:
                return False
            self.window_selector.bring_window_to_front(self.hwnd)
            self._sleep(0.25)
            if self.window_selector.is_window_foreground(self.hwnd):
                if attempt > 1:
                    self.log_update.emit(f"{reason}：第 {attempt} 次尝试后游戏窗口已获得焦点")
                return True
        self.log_update.emit(f"警告：{reason}焦点恢复失败")
        return False

    def _sleep(self, seconds: float):
        deadline = time.monotonic() + max(0, seconds)
        while self.is_running and not self.isInterruptionRequested():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        self.human.release_all()
        if self.isRunning() and QThread.currentThread() is not self:
            self.wait()

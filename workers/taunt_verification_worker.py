"""独立测谎服务：勾选即监测，疑似时停止挑衅，确认后发送两条随机数字。"""

from collections import deque
import random
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal
from pynput.keyboard import Controller, Key

from automation.human_input import input_transaction_lock
from workers.taunt_verification_watch import TauntVerificationWatch


class TauntVerificationWorker(QThread):
    log_update = pyqtSignal(str)
    suspected = pyqtSignal(str)
    cleared = pyqtSignal()
    POLL_INTERVAL = 0.03
    FOCUS_RETRY_INTERVAL = 1.0

    def __init__(self, hwnd, window_selector, parent=None):
        super().__init__(parent)
        self.hwnd = hwnd
        self.window_selector = window_selector
        self._watch = TauntVerificationWatch(hwnd, window_selector)
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._input_lock = threading.RLock()
        self._taunt_worker = None
        self._pending = deque()
        self._last_queued_episode = 0
        self._chat_step = 0
        self._held_key = None
        self._keyboard = None
        self._last_status = None
        self._next_focus_attempt = 0.0

    def snapshot(self):
        return self._watch.snapshot()

    def set_taunt_worker(self, worker):
        with self._lock:
            self._taunt_worker = worker

    def is_notifying(self):
        with self._lock:
            return bool(self._pending)

    def blocks_taunt(self):
        state = self.snapshot()
        return not state.ready or state.candidate or state.present or self.is_notifying()

    def stop(self):
        self._stop_event.set()
        self._watch.stop()
        self._release_key()

    def _status(self, message):
        if message != self._last_status:
            self._last_status = message
            self.log_update.emit(message)

    def _stop_taunt(self):
        with self._lock:
            worker = self._taunt_worker
        if worker is None:
            return True
        worker.stop_for_verification()
        # 必须等动作线程退出，避免它的收尾松键与通知按键互相干扰。
        return not worker.isRunning()

    def _input_allowed(self):
        return (not self._stop_event.is_set()
                and self.window_selector.is_window_valid(self.hwnd)
                and self.window_selector.is_window_foreground(self.hwnd))

    def _ensure_chat_focus(self):
        """仅在有通知待发送时激活游戏，拿到焦点之前绝不输入。"""
        if self._stop_event.is_set() or not self.window_selector.is_window_valid(self.hwnd):
            return False
        if self._input_allowed():
            return True
        now = time.monotonic()
        if now < self._next_focus_attempt:
            return False
        self._next_focus_attempt = now + self.FOCUS_RETRY_INTERVAL
        self._status("测谎已确认，正在激活游戏窗口并发送随机数字通知")
        try:
            self.window_selector.bring_window_to_front(self.hwnd)
        except Exception as error:
            self._status(f"激活游戏窗口失败，稍后重试，后台检测继续：{error}")
            return False
        if self._input_allowed():
            return True
        # 窗口激活可能异步完成；等待时支持取消，不阻塞独立截图线程。
        deadline = time.monotonic() + 0.2
        while not self._stop_event.wait(self.POLL_INTERVAL):
            if self._input_allowed():
                return True
            if time.monotonic() >= deadline:
                break
        if not self._stop_event.is_set():
            self._status("尚未取得游戏焦点，保留喊话进度并重试激活；后台检测继续")
        return False

    def _wait_for_input(self, seconds):
        deadline = time.monotonic() + seconds
        while not self._stop_event.is_set():
            if not self._input_allowed():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._stop_event.wait(min(self.POLL_INTERVAL, remaining))
        return False

    def _release_key(self):
        with self._input_lock:
            if self._held_key is not None and self._keyboard is not None:
                try:
                    self._keyboard.release(self._held_key)
                except Exception as error:
                    self._status(f"释放通知按键失败：{error}")
                finally:
                    self._held_key = None

    def _send_chat(self, keys):
        if not input_transaction_lock.acquire(timeout=0.05):
            return False
        try:
            while self._chat_step < len(keys):
                if not self._ensure_chat_focus():
                    return False
                if self._chat_step == 3:
                    if not self._wait_for_input(random.uniform(0.8, 1.2)):
                        return False
                with self._input_lock:
                    if not self._input_allowed():
                        return False
                    self._held_key = keys[self._chat_step]
                    self._keyboard.press(self._held_key)
                    self._chat_step += 1
                try:
                    if not self._wait_for_input(random.uniform(0.06, 0.11)):
                        return False
                finally:
                    self._release_key()
                if not self._wait_for_input(random.uniform(0.15, 0.25)):
                    return False
            return True
        finally:
            input_transaction_lock.release()

    def run(self):
        suspected = False
        was_blocked = True
        last_error = ""
        try:
            self._keyboard = Controller()
            self._watch.start()
            self._status("测谎检测已独立开启；后台识别，疑似时停止挑衅，确认后激活游戏并喊话两次随机数字")
            while not self._stop_event.is_set():
                state = self.snapshot()
                if state.error != last_error:
                    last_error = state.error
                    self._status(f"测谎截图或识别暂不可用：{state.error}" if state.error
                                 else "测谎截图及识别已恢复")
                if state.candidate or state.present:
                    self._stop_taunt()
                    if not suspected:
                        suspected = True
                        self.suspected.emit(state.kind or "验证提示")
                        self._status(f"发现疑似测谎（{state.kind or '验证提示'}），挑衅已停止，不会自动恢复")
                elif suspected and not state.error:
                    suspected = False
                    self._status("验证提示已消失，独立检测继续；挑衅需手动重新启动")
                if state.present and state.episode > self._last_queued_episode:
                    first, second = str(random.randint(1, 9)), str(random.randint(1, 9))
                    keys = (Key.enter, first, Key.enter, Key.enter, second, Key.enter)
                    with self._lock:
                        self._pending.append((state.episode, state.kind, keys))
                    self._last_queued_episode = state.episode
                with self._lock:
                    pending = self._pending[0] if self._pending else None
                if pending is not None and self._stop_taunt():
                    if self._send_chat(pending[2]):
                        with self._lock:
                            self._pending.popleft()
                        self._chat_step = 0
                        self._status(f"测谎通知已发送两次（{pending[2][1]}、{pending[2][4]}），独立检测继续")
                blocked = self.blocks_taunt()
                if was_blocked and not blocked:
                    self.cleared.emit()
                was_blocked = blocked
                self._stop_event.wait(self.POLL_INTERVAL)
        except Exception as error:
            self._status(f"独立测谎服务已停止：{error}")
        finally:
            self._release_key()
            self._watch.stop()
            if self._watch.is_alive():
                self._watch.join(timeout=1.0)

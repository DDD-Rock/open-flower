"""刀飞挑衅模式：持续横向行走，按录制时序随机执行短跳、空中挑衅动作组。"""

import math
import random
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal
from pynput.keyboard import Controller, Key

from detection.minimap_monitor import MinimapMonitor
from models.map_topology import MinimapVisualMatcher
from utils.taunt_settings import (
    DEFAULT_TAUNT_HOLD_MS, DEFAULT_TAUNT_INTERVAL_MS, normalize_taunt_range,
)


class TauntWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    position_update = pyqtSignal(float, str)
    FRAME_INTERVAL = 1 / 30
    MISSING_PLAYER_GRACE = 0.15
    MISSING_PLAYER_TIMEOUT = 5.0
    EDGE_MARGIN_PIXELS = 3.0
    TURN_INSET_RATIO = 0.08
    STUCK_TIMEOUT = 2.0
    STUCK_TOLERANCE_PIXELS = 1.0
    JUMP_TO_SKILL_DELAY = (0.070, 0.150)
    JUMP_RELEASE_AFTER_SKILL = (0.070, 0.090)
    MAX_SKILL_AFTER_JUMP = 0.200

    def __init__(self, hwnd, topology, platform_id, jump_key="Alt",
                 window_selector=None, parent=None, *, skill_key="",
                 interval_min_ms=DEFAULT_TAUNT_INTERVAL_MS[0],
                 interval_max_ms=DEFAULT_TAUNT_INTERVAL_MS[1],
                 hold_min_ms=DEFAULT_TAUNT_HOLD_MS[0],
                 hold_max_ms=DEFAULT_TAUNT_HOLD_MS[1]):
        super().__init__(parent)
        self.hwnd = hwnd
        self.topology = topology
        platform = next((item for item in topology.platforms if item.id == platform_id), None)
        if platform is None or len(platform.points) < 2:
            raise ValueError("请选择已标注的平台")
        xs = [point.x for point in platform.points]
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in xs) or max(xs) - min(xs) < 0.015:
            raise ValueError("所选平台的横向范围无效或过窄，请重新标注")
        self.left, self.right = min(xs), max(xs)
        self.jump_key = self.resolve_jump_key(jump_key)
        self.skill_key = self.resolve_skill_key(skill_key, jump_key)
        self.skill_interval = tuple(value / 1000 for value in normalize_taunt_range(
            interval_min_ms, interval_max_ms, DEFAULT_TAUNT_INTERVAL_MS))
        self.skill_hold = tuple(value / 1000 for value in normalize_taunt_range(
            hold_min_ms, hold_max_ms, DEFAULT_TAUNT_HOLD_MS))
        self.window_selector = window_selector
        self.keyboard = Controller()
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.direction = None
        self._held_direction = None
        self._jump_held = False
        self._skill_held = False
        self._action_stage = None
        self._action_deadline = None
        self._jump_started_at = None
        self._skill_release_at = None
        self._focus_paused = False
        self._movement_anchor_x = None
        self._movement_since = None
        self._stop_event = threading.Event()
        self._input_lock = threading.RLock()

    @staticmethod
    def resolve_jump_key(value):
        return TauntWorker._resolve_key(value, "跳跃")

    @staticmethod
    def resolve_skill_key(value, jump_key):
        if not str(value or "").strip():
            return None
        key = TauntWorker._resolve_key(value, "挑衅")
        if key == TauntWorker.resolve_jump_key(jump_key):
            raise ValueError("挑衅键不能与跳跃键相同")
        return key

    @staticmethod
    def _resolve_key(value, label):
        name = str(value).strip().lower()
        aliases = {"capslock": "caps_lock", "pageup": "page_up", "pagedown": "page_down"}
        name = aliases.get(name, name)
        if name in {"left", "right", "up", "down", "esc"}:
            raise ValueError(f"{label}键不能使用方向键或 Esc")
        if len(name) == 1:
            return name
        key = getattr(Key, name, None)
        if key is None:
            raise ValueError(f"请选择有效的{label}键")
        return key

    def stop(self):
        self._stop_event.set()
        self.requestInterruption()
        self._release_keys()
        if self.isRunning() and QThread.currentThread() is not self:
            self.wait(2000)

    def run(self):
        try:
            if self.window_selector and not self._stop_event.is_set():
                self.window_selector.ensure_window_focus(self.hwnd)
            self.monitor.start_capture()
            missing_since = None
            missing_paused = False
            last_x = None
            map_checked = False
            minimap_ready = False
            while not self._stop_event.is_set():
                if self.window_selector and not self.window_selector.is_window_valid(self.hwnd):
                    raise RuntimeError("游戏窗口已关闭或不可用，挑衅模式已停止")
                if not self._input_allowed():
                    self._wait(self.FRAME_INTERVAL)
                    continue
                if self._focus_paused:
                    self._focus_paused = False
                    missing_since, missing_paused, last_x = None, False, None
                    map_checked = minimap_ready = False
                    self.log_update.emit("游戏窗口已恢复焦点，正在重新定位并启动跳走")
                if not minimap_ready:
                    region = self.monitor.auto_detect_dark_region()
                    if not self._input_allowed():
                        continue
                    if region is None:
                        raise RuntimeError("无法识别小地图，请确保游戏小地图已展开且可见")
                    minimap_ready = True
                image = self.monitor.capture_minimap()
                if not self._input_allowed():
                    continue
                if image is not None and not image.size:
                    image = None
                point = None
                if image is not None and image.size:
                    if not map_checked and self.topology.visual_signature:
                        comparison = MinimapVisualMatcher.comparison(
                            self.topology.visual_signature, MinimapVisualMatcher.signature(image)
                        )
                        if not comparison["isMatch"]:
                            raise RuntimeError("当前小地图与所选地图不匹配，请确认地图后重新启动")
                        map_checked = True
                    point, _ = MinimapMonitor.find_player_position_in_image(image)
                if not self._input_allowed():
                    continue
                now = time.monotonic()
                if point is None:
                    if missing_since is None:
                        missing_since = now
                    elapsed = now - missing_since
                    # 黄点会闪烁；远离边界时容忍极短漏帧，避免反复松键。
                    near_edge = last_x is None or image is None
                    if not near_edge:
                        left_turn, right_turn = self._turn_bounds(image.shape[1])
                        padding = self.EDGE_MARGIN_PIXELS / image.shape[1]
                        near_edge = (
                            self.direction == "right" and last_x >= right_turn - padding
                        ) or (
                            self.direction == "left" and last_x <= left_turn + padding
                        )
                    if near_edge or elapsed >= self.MISSING_PLAYER_GRACE:
                        self._release_keys()
                        if not missing_paused:
                            self.log_update.emit("未识别到玩家黄点，已松键等待重新定位")
                            missing_paused = True
                    if elapsed >= self.MISSING_PLAYER_TIMEOUT:
                        raise RuntimeError("持续未识别到玩家黄点，挑衅模式已停止")
                else:
                    if missing_since is not None:
                        # 短暂闪烁只暂停计时；频繁闪烁不能让卡住检测永远重新计时。
                        with self._input_lock:
                            if self._movement_since is not None:
                                self._movement_since += now - missing_since
                    missing_since = None
                    missing_paused = False
                    width = image.shape[1]
                    last_x = float(point[0]) / width
                    self.direction = self._next_direction(last_x, width)
                    if self._movement_stalled(last_x, width, now):
                        self._restart_movement(self.direction)
                    else:
                        self._hold_movement(self.direction)
                    if not self._focus_paused and not self._stop_event.is_set():
                        self.position_update.emit(float(point[0]), self.direction)
                # 动作组计时不阻塞黄点采集与平台折返。
                self._tick_actions()
                delay = self.FRAME_INTERVAL
                if self._action_deadline is not None:
                    delay = min(delay, max(0.001, self._action_deadline - time.monotonic()))
                self._wait(delay)
        except Exception as error:
            self.error_signal.emit(str(error))
        finally:
            self._release_keys()
            self.monitor.close_capture()
            self.log_update.emit("挑衅模式已停止，方向键、跳跃键和挑衅键已释放")

    def _input_allowed(self):
        if self._stop_event.is_set():
            return False
        if self.window_selector and not self.window_selector.is_window_foreground(self.hwnd):
            self._release_keys()
            self.direction = None
            if not self._focus_paused:
                self._focus_paused = True
                self.log_update.emit("游戏窗口失去焦点，挑衅模式已暂停，等待回到游戏")
            return False
        return True

    def _reset_movement_tracking(self):
        self._movement_anchor_x = None
        self._movement_since = None

    def _movement_stalled(self, x, width, now=None):
        with self._input_lock:
            if now is None:
                now = time.monotonic()
            if (self._movement_since is None or self._held_direction is None
                    or abs(x - self._movement_anchor_x) * width > self.STUCK_TOLERANCE_PIXELS + 1e-6):
                # 与静止开始时的位置比较，避免逐帧微小位移被误判成卡住。
                self._movement_anchor_x = x
                self._movement_since = now
                return False
            return now - self._movement_since >= self.STUCK_TIMEOUT

    def _restart_movement(self, direction):
        self._release_keys()
        self.log_update.emit("黄点横向连续 2 秒未移动，已松键，正在重新启动跳走和挑衅")
        if not self._wait_for_input(random.uniform(0.05, 0.10)):
            return
        self._hold_movement(direction)

    def _wait_for_input(self, seconds):
        # 换向或起跳的短暂停顿期间也检查焦点，避免把后续按键发给其他窗口。
        while seconds > 0:
            if not self._input_allowed() or self._focus_paused:
                return False
            self._tick_actions()
            step = min(seconds, self.FRAME_INTERVAL)
            if self._action_deadline is not None:
                step = min(step, max(0.001, self._action_deadline - time.monotonic()))
            if not self._wait(step):
                return False
            seconds -= step
        return self._input_allowed() and not self._focus_paused

    def _start_jump_cycle(self):
        with self._input_lock:
            if (not self._input_allowed() or self._focus_paused
                    or self._held_direction is None):
                return
            self.keyboard.press(self.jump_key)
            self._jump_held = True
            self._jump_started_at = time.monotonic()
            delay = random.uniform(*self.JUMP_TO_SKILL_DELAY)
            if self.skill_key is None:
                delay += random.uniform(*self.JUMP_RELEASE_AFTER_SKILL)
            self._action_stage = "jump_lead"
            self._action_deadline = self._jump_started_at + delay

    def _finish_action_cycle(self, now):
        if self._jump_held:
            self.keyboard.release(self.jump_key)
            self._jump_held = False
        if self._skill_held:
            self.keyboard.release(self.skill_key)
            self._skill_held = False
        self._jump_started_at = None
        self._skill_release_at = None
        self._action_stage = "rest"
        self._action_deadline = now + random.uniform(*self.skill_interval)

    def _tick_actions(self):
        with self._input_lock:
            if (not self._input_allowed() or self._focus_paused
                    or self._held_direction is None or self._action_deadline is None):
                return
            now = time.monotonic()
            if now < self._action_deadline:
                return
            if self._action_stage == "jump_lead":
                if self.skill_key is None or now - self._jump_started_at > self.MAX_SKILL_AFTER_JUMP:
                    # 截图或调度延迟时跳过本次技能，绝不在过期的起跳时序后补按。
                    self._finish_action_cycle(now)
                    return
                self.keyboard.press(self.skill_key)
                self._skill_held = True
                hold = random.uniform(*self.skill_hold)
                self._skill_release_at = now + hold
                overlap = min(random.uniform(*self.JUMP_RELEASE_AFTER_SKILL), hold / 2)
                self._action_stage = "jump_and_skill"
                self._action_deadline = now + overlap
            elif self._action_stage == "jump_and_skill":
                self.keyboard.release(self.jump_key)
                self._jump_held = False
                if now >= self._skill_release_at:
                    self._finish_action_cycle(now)
                else:
                    self._action_stage = "skill_tail"
                    self._action_deadline = self._skill_release_at
            elif self._action_stage == "skill_tail":
                self._finish_action_cycle(now)
            elif self._action_stage == "rest":
                self._start_jump_cycle()

    def _turn_bounds(self, width):
        span = self.right - self.left
        # 两端各内缩约 8%，在平台中段折返；窄平台仍保留往返空间。
        margin = min(max(self.EDGE_MARGIN_PIXELS / width, span * self.TURN_INSET_RATIO), span / 4)
        return self.left + margin, self.right - margin

    def _next_direction(self, x, width):
        left_turn, right_turn = self._turn_bounds(width)
        if x <= left_turn:
            return "right"
        if x >= right_turn:
            return "left"
        return self.direction or ("right" if x <= (self.left + self.right) / 2 else "left")

    def _hold_movement(self, direction):
        key = Key.left if direction == "left" else Key.right
        with self._input_lock:
            if not self._input_allowed() or self._focus_paused:
                return
            if self._held_direction == key:
                return
            turning = self._held_direction is not None
            if turning:
                self.keyboard.release(self._held_direction)
                self._held_direction = None
        if turning:
            if not self._wait_for_input(random.uniform(0.01, 0.03)):
                return
            self._release_keys()
            if not self._wait_for_input(random.uniform(0.05, 0.10)):
                return
        with self._input_lock:
            if not self._input_allowed() or self._focus_paused:
                return
            self.keyboard.press(key)
            self._held_direction = key
        if not self._wait_for_input(random.uniform(0.025, 0.055)):
            return
        self._start_jump_cycle()
        self.log_update.emit("向左短按跳走" if direction == "left" else "向右短按跳走")

    def _release_keys(self):
        with self._input_lock:
            for key in (self._held_direction, self.jump_key if self._jump_held else None,
                        self.skill_key if self._skill_held else None):
                if key is not None:
                    try:
                        self.keyboard.release(key)
                    except Exception:
                        pass
            self._held_direction = None
            self._jump_held = False
            self._skill_held = False
            self._action_stage = None
            self._action_deadline = None
            self._jump_started_at = None
            self._skill_release_at = None
            self._reset_movement_tracking()

    def _wait(self, seconds):
        return not self._stop_event.wait(seconds)

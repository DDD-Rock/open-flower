"""Windows 跟补左右走模式，独立于其它跟补方案。"""

import random
import time
from typing import Dict, List, Optional, Tuple

import win32gui
from PyQt6.QtCore import QThread, pyqtSignal
from pynput.keyboard import Key

from automation.human_input import HumanInput
from detection.minimap_monitor import MinimapMonitor
from models.buff_config import BuffConfig
from utils.countdown import format_release_time, next_release_time, remaining_seconds
from utils.key_names import normalize_key_name
from utils.window_selector import WindowSelector


class FollowHealWalkingWorker(QThread):
    """Historical follow-heal behavior: heal continuously and recover by walking only."""

    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    countdown_update = pyqtSignal(dict)

    BATCH_CAST_WINDOW = 10.0
    RETURN_TIMEOUT = 5.0
    CENTER_ADJUST_INTERVAL = (12.0, 15.0)
    CENTER_ADJUST_DURATION = (0.20, 0.30)

    SPECIAL_KEY_MAP = {
        "shift": Key.shift, "ctrl": Key.ctrl, "control": Key.ctrl,
        "alt": Key.alt, "tab": Key.tab, "space": Key.space,
        "enter": Key.enter, "backspace": Key.backspace,
        "delete": Key.delete, "insert": Key.insert, "home": Key.home,
        "end": Key.end, "page_up": Key.page_up, "pageup": Key.page_up,
        "page_down": Key.page_down, "pagedown": Key.page_down,
        "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
        "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
        "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
    }

    def __init__(
        self,
        hwnd: int,
        buffs: List[BuffConfig],
        heal_key: str,
        anchor_pos: Tuple[int, int],
        minimap_region: Optional[Tuple[int, int, int, int]] = None,
        boundary_tolerance: float = 6.0,
    ):
        super().__init__()
        self.hwnd = hwnd
        self.buffs = [
            buff for buff in buffs
            if buff.enabled and buff.key and buff.duration > 0
        ]
        self.heal_key = heal_key
        self.anchor_pos = anchor_pos
        self.base_x = float(anchor_pos[0])
        self.minimap_region = minimap_region
        self.boundary_tolerance = max(1.0, min(50.0, float(boundary_tolerance)))
        self.is_running = True
        self.human = HumanInput()
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.window_selector = WindowSelector()
        self.buff_next_cast: Dict[str, float] = {}
        self._held_heal_key = None

    def stop(self):
        self.is_running = False
        self._release_held_heal_key()
        self.human.release_all()

    def run(self):
        try:
            if not self.heal_key:
                self.error_signal.emit("请先设置加血技能键")
                return
            if not self.anchor_pos:
                self.error_signal.emit("请先标记跟补基准点")
                return
            self.log_update.emit("跟补左右走模式启动...")
            if not self.buffs:
                self.log_update.emit("未启用 BUFF，将只执行补血和位置修正")
            if not self._ensure_game_focus("跟补启动"):
                self.error_signal.emit("无法将游戏窗口置于前台")
                return

            self.log_update.emit(
                f"使用手动跟补基准点 X={self.base_x:.1f}，"
                f"左右界限 ±{self.boundary_tolerance:.1f}，纯方向键回位"
            )
            if self.minimap_region:
                self.monitor.set_minimap_region(*self.minimap_region)
                self.log_update.emit(
                    "使用标记时的小地图区域 "
                    f"{self.minimap_region[2]}x{self.minimap_region[3]}"
                )
            else:
                self.log_update.emit("未保存小地图区域，将在补血后再识别，避免开局空等")

            next_adjust_at = time.time() + random.uniform(*self.CENTER_ADJUST_INTERVAL)
            self.buff_next_cast.clear()
            while self.is_running:
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已关闭或不可见")
                    break
                if not self.window_selector.is_window_foreground(self.hwnd):
                    self._release_held_heal_key()
                    self.human.release_all()
                    if not self._ensure_game_focus("跟补恢复"):
                        self.error_signal.emit("无法恢复游戏窗口焦点")
                        break

                if self._get_buffs_to_cast(include_upcoming=False):
                    self._cast_all_ready_buffs(
                        self._get_buffs_to_cast(include_upcoming=True)
                    )
                    self._random_sleep(0.8, 1.2)
                    continue

                if self.monitor.get_minimap_size() is None:
                    self._perform_heal_cycle()
                    rect = self.monitor.auto_detect_dark_region()
                    if rect:
                        self.log_update.emit(f"小地图识别完成：{rect[2]}x{rect[3]}")
                    continue

                player = self.monitor.find_player_position()
                if player:
                    player_x = float(player[0])
                    if self._is_outside_boundary(player_x):
                        self._return_to_base(player_x)
                        continue
                    if time.time() >= next_adjust_at:
                        self._center_adjust_step(player_x)
                        next_adjust_at = time.time() + random.uniform(*self.CENTER_ADJUST_INTERVAL)
                        continue
                self._perform_heal_cycle()
        except Exception as exc:
            self.error_signal.emit(f"跟补左右走模式运行错误: {exc}")
        finally:
            self._release_held_heal_key()
            self.human.release_all()
            self.is_running = False
            self.countdown_update.emit({})
            self.log_update.emit("跟补左右走模式已停止")
            self.finished_signal.emit()

    def _is_outside_boundary(self, current_x: float) -> bool:
        return abs(current_x - self.base_x) > self.boundary_tolerance

    def _return_to_base(self, start_x: float):
        direction = "left" if start_x > self.base_x else "right"
        if not self._ensure_game_focus("左右走回位"):
            return
        self._move_direction(direction)
        started_at = time.time()
        while self.is_running:
            if self._cast_if_buff_due():
                return
            self._random_sleep(0.08, 0.14)
            player = self.monitor.find_player_position()
            if not player:
                self.human.stop_move()
                self.log_update.emit("⚠️ 左右走回位时丢失玩家黄点，停止移动")
                return
            current_x = float(player[0])
            if not self._is_outside_boundary(current_x):
                self.human.stop_move()
                self.log_update.emit(
                    f"已回到基准区域：当前X={current_x:.1f}，基准X={self.base_x:.1f}"
                )
                return
            needed = "left" if current_x > self.base_x else "right"
            if needed != direction:
                self.human.stop_move()
                self._random_sleep(0.08, 0.18)
                self._move_direction(needed)
                direction = needed
            if time.time() - started_at > self.RETURN_TIMEOUT:
                self.human.stop_move()
                self.log_update.emit("⚠️ 左右走回位超时，等待下轮检测")
                return
        self.human.stop_move()

    def _center_adjust_step(self, current_x: float):
        direction = "left" if current_x > self.base_x else "right"
        self.log_update.emit(
            f"左右走修正：当前X={current_x:.1f}，向{'左' if direction == 'left' else '右'}小走后继续补血"
        )
        if self._cast_if_buff_due() or not self._ensure_game_focus("左右走修正"):
            return
        self._move_direction(direction)
        self._interruptible_sleep(random.uniform(*self.CENTER_ADJUST_DURATION))
        self.human.stop_move()
        self._random_sleep(0.22, 0.75)

    def _perform_heal_cycle(self):
        if self._cast_if_buff_due() or not self._ensure_game_focus("释放加血技能"):
            return
        roll = random.randint(1, 100)
        if roll <= 25:
            self._burst_heal()
        elif roll <= 45:
            self._timed_heal_tap((0.18, 0.42), (0.12, 0.30))
        else:
            self._interruptible_heal_hold((0.65, 1.40))
            self._random_sleep(0.16, 0.36)

    def _burst_heal(self):
        count = random.randint(2, 4)
        for index in range(count):
            if not self.is_running or self._cast_if_buff_due():
                return
            self._timed_heal_tap((0.045, 0.120), (0.06, 0.18))
            if index == count - 1:
                self._random_sleep(0.12, 0.35)

    def _timed_heal_tap(self, hold_range: Tuple[float, float], after_delay: Tuple[float, float]):
        self._tap_named_key(self.heal_key, hold_range)
        self._random_sleep(*after_delay)

    def _cast_if_buff_due(self) -> bool:
        due = self._get_buffs_to_cast(include_upcoming=False)
        if not due:
            return False
        self._cast_all_ready_buffs(self._get_buffs_to_cast(include_upcoming=True))
        self._random_sleep(0.8, 1.2)
        return True

    def _get_buffs_to_cast(self, include_upcoming: bool) -> List[BuffConfig]:
        now = time.time()
        window = self.BATCH_CAST_WINDOW if include_upcoming else 0
        return [
            buff for buff in self.buffs
            if self.buff_next_cast.get(buff.key, 0) - now <= window
        ]

    def _cast_all_ready_buffs(self, buffs: List[BuffConfig]) -> bool:
        if not buffs or not self.is_running:
            return False
        self._release_held_heal_key()
        self.human.stop_move()
        if not self._ensure_game_focus("释放 BUFF"):
            return False
        for index, buff in enumerate(buffs):
            if not self.is_running:
                break
            self.log_update.emit(f"释放 BUFF: {buff.key}")
            pressed_at = self._tap_named_key(buff.key, (0.05, 0.15))
            self._random_sleep(0.1, 0.3)
            final_pressed_at = self._tap_named_key(buff.key, (0.05, 0.15))
            if final_pressed_at is None:
                final_pressed_at = pressed_at
            if final_pressed_at is not None:
                release_at = next_release_time(final_pressed_at, buff.duration)
                self.buff_next_cast[buff.key] = release_at
                self._update_countdown_display(now=final_pressed_at)
                self.log_update.emit(
                    f"BUFF {buff.key} 倒计时 {remaining_seconds(release_at, final_pressed_at)} 秒，"
                    f"下次释放 {format_release_time(release_at)}"
                )
            if index < len(buffs) - 1:
                self._random_sleep(0.25, 0.65)
        return True

    def _interruptible_heal_hold(self, hold_range: Tuple[float, float]):
        key = self._resolve_key(self.heal_key)
        try:
            self.human.keyboard.press(key)
            self._held_heal_key = key
        except Exception as exc:
            self.error_signal.emit(f"加血键错误: {exc}")
            return
        end_at = time.time() + random.uniform(*hold_range)
        while self.is_running and time.time() < end_at:
            if self._get_buffs_to_cast(include_upcoming=False):
                self._release_held_heal_key()
                self._cast_if_buff_due()
                return
            self._random_sleep(0.10, 0.15)
        self._release_held_heal_key()

    def _tap_named_key(self, key_str: str, hold_range: Tuple[float, float]) -> Optional[float]:
        key = self._resolve_key(key_str)
        pressed_at = None
        try:
            self.human.keyboard.press(key)
            pressed_at = time.time()
            self._interruptible_sleep(random.uniform(*hold_range))
            self.human.keyboard.release(key)
            return pressed_at
        except Exception as exc:
            self.error_signal.emit(f"按键 {key_str} 失败: {exc}")
            try:
                self.human.keyboard.release(key)
            except Exception:
                pass
            return None

    def _release_held_heal_key(self):
        if self._held_heal_key is None:
            return
        try:
            self.human.keyboard.release(self._held_heal_key)
        except Exception:
            pass
        self._held_heal_key = None

    def _move_direction(self, direction: str):
        if direction == "left":
            self.human.move_left()
        else:
            self.human.move_right()

    def _resolve_key(self, key_str: str):
        normalized_key = normalize_key_name(key_str)
        return self.SPECIAL_KEY_MAP.get(normalized_key.lower(), normalized_key)

    def _interruptible_sleep(self, seconds: float):
        end_at = time.time() + max(0.0, seconds)
        while self.is_running and time.time() < end_at:
            time.sleep(min(0.05, end_at - time.time()))
            self._update_countdown_display()

    def _random_sleep(self, min_sec: float, max_sec: float):
        self._interruptible_sleep(random.uniform(min_sec, max_sec))

    def _update_countdown_display(self, now: Optional[float] = None):
        current_time = time.time() if now is None else now
        self.countdown_update.emit({
            buff.key: remaining_seconds(self.buff_next_cast[buff.key], current_time)
            for buff in self.buffs
            if buff.key in self.buff_next_cast
        })

    def _ensure_game_focus(self, reason: str) -> bool:
        try:
            if self.window_selector.is_window_foreground(self.hwnd):
                return True
            if self.window_selector.ensure_window_focus(self.hwnd, attempts=12, delay=0.15):
                self.log_update.emit(f"✅ {reason}：游戏窗口焦点已恢复")
                return True
            foreground = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(foreground) if foreground else "未知"
            self.log_update.emit(f"❌ {reason}：无法恢复游戏窗口焦点，当前前台窗口为 {title}")
            return False
        except Exception as exc:
            self.log_update.emit(f"❌ {reason}：恢复游戏焦点失败：{exc}")
            return False

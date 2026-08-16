"""Windows 跟补模式：混合模式与瞬移回位的实现。"""

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
from utils.follow_heal_navigation import (
    HEAL_GAP_RANGE as FOLLOW_HEAL_GAP_RANGE,
    HEAL_HOLD_RANGE as FOLLOW_HEAL_HOLD_RANGE,
    TeleportExcursionGuard,
    is_near_anchor,
    is_outside_walking_boundary,
    next_center_adjust_interval,
    next_walking_keepalive_interval,
    opposite_walking_direction,
    opposite_direction,
    outward_teleport_direction,
    protective_anchor_tolerance,
    requires_immediate_left_recovery,
    teleport_direction_to_base,
    updated_center_adjust_deadline,
    walking_direction_to_base,
    walking_keepalive_direction,
    WALKING_KEEPALIVE_FIRST_STEP_RANGE,
    WALKING_KEEPALIVE_SECOND_STEP_REDUCTION_RANGE,
    WALKING_RECOVERY_MAXIMUM_ATTEMPTS,
)
from utils.key_names import normalize_key_name
from utils.window_selector import WindowSelector


class FollowHealWorker(QThread):
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    countdown_update = pyqtSignal(dict)

    BATCH_CAST_WINDOW = 10.0
    HEAL_HOLD_RANGE = FOLLOW_HEAL_HOLD_RANGE
    HEAL_GAP_RANGE = FOLLOW_HEAL_GAP_RANGE
    BUFF_RECOVERY_GAP_RANGE = (0.18, 0.42)
    MARKER_SETTLE_RANGE = (0.50, 0.80)
    EMERGENCY_MIN_SETTLE_RANGE = (0.15, 0.25)
    EMERGENCY_MAX_SETTLE = 0.40
    STABILITY_POLL_RANGE = (0.03, 0.05)
    STABLE_MARKER_DELTA = 0.75
    POSITION_POLL_RANGE = (0.035, 0.065)

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
        teleport_key: str,
        anchor_pos: Tuple[int, int],
        minimap_region: Optional[Tuple[int, int, int, int]] = None,
        boundary_tolerance: float = 6.0,
        return_strategy: str = "walk",
    ):
        super().__init__()
        self.hwnd = hwnd
        self.buffs = [
            buff for buff in buffs
            if buff.enabled and buff.key and buff.duration > 0
        ]
        self.heal_key = heal_key
        self.teleport_key = teleport_key
        self.anchor_pos = anchor_pos
        self.base_x = float(anchor_pos[0])
        self.minimap_region = minimap_region
        self.boundary_tolerance = max(1.0, min(50.0, float(boundary_tolerance)))
        self.return_strategy = "teleport" if return_strategy == "teleport" else "walk"
        self.protective_tolerance = protective_anchor_tolerance(
            self.boundary_tolerance
        )

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
            self.log_update.emit("跟补模式启动...")
            if not self.heal_key:
                self.error_signal.emit("请先设置加血技能键")
                return
            if not self.teleport_key:
                self.error_signal.emit("请先设置瞬移技能键")
                return
            if (
                self.teleport_key.lower() == self.heal_key.lower()
            ):
                self.error_signal.emit("瞬移技能键不能和加血技能键重复")
                return
            if not self.anchor_pos:
                self.error_signal.emit("请先标记跟补基准点")
                return
            if not self.buffs:
                self.log_update.emit("未启用 BUFF，将只执行补血和位置修正")
            if not self._ensure_game_focus("跟补启动"):
                self.error_signal.emit("无法将游戏窗口置于前台")
                return

            self.log_update.emit(
                f"使用手动跟补基准点 X={self.base_x:.1f}，"
                f"左右界限 ±{self.boundary_tolerance:.1f}，"
                f"回位方案：{'瞬移回位' if self.return_strategy == 'teleport' else '混合模式'}"
            )
            if self.return_strategy == "teleport":
                self.log_update.emit(f"瞬移提前保护 ±{self.protective_tolerance:.1f}")
            if self.minimap_region:
                self.monitor.set_minimap_region(*self.minimap_region)
                self.log_update.emit(
                    "使用标记时的小地图区域 "
                    f"{self.minimap_region[2]}x{self.minimap_region[3]}"
                )
            else:
                self.log_update.emit("未保存小地图区域，将在补血后再识别，避免开局空等")

            next_adjust_at = time.time() + next_center_adjust_interval()
            next_walking_keepalive_at = time.time() + next_walking_keepalive_interval()
            excursion_guard = TeleportExcursionGuard()
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

                due = self._get_buffs_to_cast(include_upcoming=False)
                if due:
                    self._cast_all_ready_buffs(
                        self._get_buffs_to_cast(include_upcoming=True)
                    )
                    self._random_sleep(*self.BUFF_RECOVERY_GAP_RANGE)
                    continue

                next_adjust_at, next_walking_keepalive_at = self._continuous_heal_cycle(
                    next_adjust_at,
                    next_walking_keepalive_at,
                    excursion_guard,
                )

                if self.monitor.get_minimap_size() is None and self.is_running:
                    rect = self.monitor.auto_detect_dark_region()
                    if rect:
                        self.log_update.emit(f"小地图识别完成：{rect[2]}x{rect[3]}")
                    else:
                        self.log_update.emit("⚠️ 暂未识别到小地图")
        except Exception as exc:
            self.error_signal.emit(f"跟补模式运行错误: {exc}")
        finally:
            self._release_held_heal_key()
            self.human.release_all()
            self.is_running = False
            self.countdown_update.emit({})
            self.log_update.emit("跟补模式已停止")
            self.finished_signal.emit()

    def _continuous_heal_cycle(
        self,
        next_adjust_at: float,
        next_walking_keepalive_at: float,
        excursion_guard: TeleportExcursionGuard,
    ) -> Tuple[float, float]:
        if not self._ensure_game_focus("持续释放加血技能"):
            return next_adjust_at, next_walking_keepalive_at

        heal_key = self._resolve_key(self.heal_key)
        try:
            self.human.keyboard.press(heal_key)
            self._held_heal_key = heal_key
        except Exception as exc:
            self.error_signal.emit(f"加血键错误: {exc}")
            return next_adjust_at, next_walking_keepalive_at

        end_at = time.time() + random.uniform(*self.HEAL_HOLD_RANGE)
        missing_player_count = 0
        while self.is_running and time.time() < end_at:
            if self._get_buffs_to_cast(include_upcoming=False):
                self._release_held_heal_key()
                self._cast_if_buff_due()
                return next_adjust_at, next_walking_keepalive_at
            if (
                not self.window_selector.is_window_valid(self.hwnd)
                or not self.window_selector.is_window_foreground(self.hwnd)
            ):
                self._release_held_heal_key()
                return next_adjust_at, next_walking_keepalive_at

            if self.monitor.get_minimap_size() is not None:
                player = self.monitor.find_player_position()
                if player:
                    missing_player_count = 0
                    player_x = float(player[0])
                    now = time.time()
                    if self.return_strategy == "walk":
                        if is_outside_walking_boundary(
                            player_x, self.base_x, self.boundary_tolerance
                        ):
                            self._release_held_heal_key()
                            self._teleport_back_for_walking_strategy(player_x)
                            return next_adjust_at, next_walking_keepalive_at
                        if now >= next_walking_keepalive_at:
                            self._release_held_heal_key()
                            self._walk_for_skill_keepalive(player_x)
                            next_walking_keepalive_at = (
                                time.time() + next_walking_keepalive_interval()
                            )
                            return next_adjust_at, next_walking_keepalive_at
                        self._random_sleep(*self.POSITION_POLL_RANGE)
                        continue
                    is_new_excursion = excursion_guard.should_correct(
                        player_x,
                        self.base_x,
                        self.protective_tolerance,
                        priority_left_recovery_tolerance=self.protective_tolerance,
                    )
                    is_scheduled = now >= next_adjust_at
                    should_perform_near_anchor_excursion = (
                        not is_new_excursion
                        and is_scheduled
                        and is_near_anchor(
                            player_x,
                            self.base_x,
                            self.boundary_tolerance,
                        )
                    )
                    if should_perform_near_anchor_excursion:
                        return_direction = self._perform_near_anchor_excursion(player_x)
                        if return_direction:
                            excursion_guard.record_teleport(return_direction)
                    elif is_new_excursion or is_scheduled:
                        direction = teleport_direction_to_base(player_x, self.base_x)
                        if direction:
                            teleported = self._teleport_toward_base(
                                direction,
                                player_x,
                                urgent=is_new_excursion,
                            )
                            if teleported:
                                excursion_guard.record_teleport(direction)
                    next_adjust_at = updated_center_adjust_deadline(
                        next_adjust_at,
                        now,
                        is_scheduled,
                    )
                else:
                    missing_player_count += 1
                    if missing_player_count == 1 or missing_player_count % 8 == 0:
                        self.log_update.emit(
                            f"⚠️ 暂时丢失玩家黄点 {missing_player_count} 次"
                        )
            self._random_sleep(*self.POSITION_POLL_RANGE)

        self._release_held_heal_key()
        if self.is_running:
            self._random_sleep(*self.HEAL_GAP_RANGE)
        return next_adjust_at, next_walking_keepalive_at

    def _teleport_back_for_walking_strategy(self, player_x: float):
        latest_x = player_x
        for attempt in range(1, WALKING_RECOVERY_MAXIMUM_ATTEMPTS + 1):
            direction = walking_direction_to_base(latest_x, self.base_x)
            if direction is None:
                return
            self.log_update.emit(
                f"混合模式越界：当前X={latest_x:.1f}，"
                f"第 {attempt} 次朝标记点方向瞬移"
            )
            try:
                self.human.perform_directional_skill(
                    direction,
                    self._resolve_key(self.teleport_key),
                )
            except Exception as exc:
                self.error_signal.emit(f"瞬移键错误: {exc}")
                return
            landing_x = self._wait_for_walking_strategy_landing()
            if landing_x is None:
                self.log_update.emit("⚠️ 越界瞬移后未识别到稳定黄点，停止连续瞬移")
                return
            latest_x = landing_x
            if not is_outside_walking_boundary(
                landing_x,
                self.base_x,
                self.boundary_tolerance,
            ):
                self.log_update.emit(
                    f"越界瞬移已回到安全区：当前X={landing_x:.1f}"
                )
                return
        self.log_update.emit(
            f"⚠️ 连续瞬移 {WALKING_RECOVERY_MAXIMUM_ATTEMPTS} 次后"
            "仍在界外，恢复补血并等待下轮检测"
        )

    def _wait_for_walking_strategy_landing(self) -> Optional[float]:
        started_at = time.time()
        minimum_end = started_at + 0.15
        deadline = started_at + 0.45
        previous_x = None
        latest_x = None
        stable_frames = 0
        while self.is_running and time.time() < deadline:
            player = self.monitor.find_player_position()
            if player:
                current_x = float(player[0])
                latest_x = current_x
                if (
                    previous_x is not None
                    and abs(current_x - previous_x) <= self.STABLE_MARKER_DELTA
                ):
                    stable_frames += 1
                else:
                    stable_frames = 1
                previous_x = current_x
                if time.time() >= minimum_end and stable_frames >= 2:
                    return current_x
            else:
                previous_x = None
                stable_frames = 0
            self._random_sleep(*self.STABILITY_POLL_RANGE)
        return latest_x

    def _walk_for_skill_keepalive(self, player_x: float):
        direction = walking_keepalive_direction(player_x, self.base_x)
        return_direction = opposite_walking_direction(direction)
        first_step = random.uniform(*WALKING_KEEPALIVE_FIRST_STEP_RANGE)
        second_step = first_step - random.uniform(
            *WALKING_KEEPALIVE_SECOND_STEP_REDUCTION_RANGE
        )
        self.log_update.emit(
            f"防卡技能双向短走：先向{'左' if direction == 'left' else '右'} "
            f"{round(first_step * 1000)}ms，再向"
            f"{'左' if return_direction == 'left' else '右'} "
            f"{round(second_step * 1000)}ms"
        )
        if self._cast_if_buff_due() or not self._ensure_game_focus("防卡技能小走"):
            return
        self._move_walking_direction(direction)
        self._interruptible_sleep(first_step)
        if not self.is_running:
            self.human.stop_move()
            return
        self._move_walking_direction(return_direction)
        self._interruptible_sleep(second_step)
        self.human.stop_move()

    def _move_walking_direction(self, direction: str):
        if direction == "left":
            self.human.move_left()
        else:
            self.human.move_right()

    def _teleport_toward_base(
        self,
        direction: str,
        player_x: float,
        urgent: bool,
        settle_range=None,
    ):
        direction_text = "左" if direction == "left" else "右"
        phase = "快速回位" if urgent else "跟补修正"
        self.log_update.emit(
            f"{phase}：当前X={player_x:.1f}，按住{direction_text}方向并短按瞬移"
        )
        try:
            self.human.perform_directional_skill(
                direction,
                self._resolve_key(self.teleport_key),
            )
            if urgent:
                self._wait_for_player_marker_stability(
                    self.base_x,
                    self.protective_tolerance,
                )
            else:
                # 定时修正保持较自然的稳定等待。
                self._random_sleep(*(settle_range or self.MARKER_SETTLE_RANGE))
            return True
        except Exception as exc:
            self.error_signal.emit(f"瞬移键错误: {exc}")
            return False

    def _perform_near_anchor_excursion(self, player_x: float) -> Optional[str]:
        outward = outward_teleport_direction(player_x, self.base_x)
        return_direction = opposite_direction(outward)
        self.log_update.emit(
            f"近点拟人往返：先向{'左' if outward == 'left' else '右'}侧瞬移，"
            "短暂间隔后回位"
        )
        if not self._teleport_toward_base(
            outward,
            player_x,
            urgent=False,
            settle_range=(0.12, 0.24),
        ):
            return None
        if not self._teleport_toward_base(
            return_direction,
            player_x,
            urgent=False,
            settle_range=(0.15, 0.28),
        ):
            return None
        return return_direction

    def _wait_for_player_marker_stability(
        self,
        base_x: float,
        left_recovery_tolerance: float,
    ):
        """紧急回位后高频采样，黄点连续两帧稳定即可继续判断。"""
        started_at = time.time()
        minimum_end = started_at + random.uniform(*self.EMERGENCY_MIN_SETTLE_RANGE)
        deadline = started_at + self.EMERGENCY_MAX_SETTLE
        previous_x = None
        stable_frames = 0

        while self.is_running and time.time() < deadline:
            player = self.monitor.find_player_position()
            if player:
                current_x = float(player[0])
                # 首帧发现左侧危险落点就结束等待，让主循环立即向右回位。
                if requires_immediate_left_recovery(
                    current_x,
                    base_x,
                    left_recovery_tolerance,
                ):
                    return
                if (
                    previous_x is not None
                    and abs(current_x - previous_x) <= self.STABLE_MARKER_DELTA
                ):
                    stable_frames += 1
                else:
                    stable_frames = 1
                previous_x = current_x
                if time.time() >= minimum_end and stable_frames >= 2:
                    return
            else:
                previous_x = None
                stable_frames = 0
            self._random_sleep(*self.STABILITY_POLL_RANGE)

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

    def _ensure_game_focus(self, reason: str) -> bool:
        try:
            if self.window_selector.is_window_foreground(self.hwnd):
                return True
            if self.window_selector.ensure_window_focus(self.hwnd, attempts=12, delay=0.15):
                self.log_update.emit(f"✅ {reason}：游戏窗口焦点已恢复")
                return True
            foreground = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(foreground) if foreground else "未知"
            self.log_update.emit(
                f"❌ {reason}：无法恢复游戏窗口焦点，当前前台窗口为 {title}"
            )
            return False
        except Exception as exc:
            self.log_update.emit(f"❌ {reason}：恢复游戏焦点失败：{exc}")
            return False

    def _get_buffs_to_cast(self, include_upcoming: bool) -> List[BuffConfig]:
        now = time.time()
        window = self.BATCH_CAST_WINDOW if include_upcoming else 0
        return [
            buff for buff in self.buffs
            if self.buff_next_cast.get(buff.key, 0) - now <= window
        ]

    def _update_countdown_display(self, now: Optional[float] = None):
        current_time = time.time() if now is None else now
        self.countdown_update.emit({
            buff.key: remaining_seconds(self.buff_next_cast[buff.key], current_time)
            for buff in self.buffs
            if buff.key in self.buff_next_cast
        })

    def _tap_named_key(self, key_str: str, hold_range: Tuple[float, float]):
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

    def _cast_buff(self, buff: BuffConfig):
        self.log_update.emit(f"释放 BUFF: {buff.key}")
        pressed_at = self._tap_named_key(buff.key, (0.05, 0.15))
        self._random_sleep(0.1, 0.3)
        final_pressed_at = self._tap_named_key(buff.key, (0.05, 0.15))
        final_pressed_at = final_pressed_at or pressed_at
        if final_pressed_at is None:
            return
        release_at = next_release_time(final_pressed_at, buff.duration)
        self.buff_next_cast[buff.key] = release_at
        self._update_countdown_display(now=final_pressed_at)
        self.log_update.emit(
            f"BUFF {buff.key} 倒计时 "
            f"{remaining_seconds(release_at, final_pressed_at)} 秒，"
            f"下次释放 {format_release_time(release_at)}"
        )

    def _cast_all_ready_buffs(self, buffs: List[BuffConfig]) -> bool:
        if not buffs or not self.is_running:
            return False
        self._release_held_heal_key()
        self.human.stop_move()
        self.log_update.emit(f"准备释放 {len(buffs)} 个 BUFF")
        if not self._ensure_game_focus("释放 BUFF"):
            return False
        for index, buff in enumerate(buffs):
            if not self.is_running:
                break
            self._cast_buff(buff)
            if index < len(buffs) - 1:
                self._random_sleep(0.25, 0.65)
        return True

    def _cast_if_buff_due(self) -> bool:
        if not self._get_buffs_to_cast(include_upcoming=False):
            return False
        self._cast_all_ready_buffs(self._get_buffs_to_cast(include_upcoming=True))
        self._random_sleep(*self.BUFF_RECOVERY_GAP_RANGE)
        return True

    def _release_held_heal_key(self):
        if self._held_heal_key is None:
            return
        try:
            self.human.keyboard.release(self._held_heal_key)
        except Exception:
            pass
        self._held_heal_key = None

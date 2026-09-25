"""Background smart-walk controller for one MuMu ADB stream."""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional

import win32api
import win32con
import win32gui

from utils.countdown import next_release_time, remaining_seconds
from utils.keyboard_utils import KEY_HOLD_MAX_MS, KEY_HOLD_MIN_MS
from utils.smart_walk import next_smart_walk_deadline, smart_walk_can_continue, smart_walk_direction


_KEYCODES = {
    **{str(index): 7 + index for index in range(10)},
    **{chr(ord("A") + index): 29 + index for index in range(26)},
    "SPACE": 62,
    "ENTER": 66,
    "TAB": 61,
    "ALT": 57,
    "CTRL": 113,
    "SHIFT": 59,
}

# Keep each key transaction intact when several emulator workers fire together.
_MUMU_INPUT_LOCK = threading.RLock()


class MumuSmartWalkWorker:
    """Run smart-walk independently from Qt and video decoding threads."""

    def __init__(
        self,
        serial: str,
        adb_path: str,
        analysis_provider: Callable,
        window_handle=None,
        countdown_callback: Optional[Callable] = None,
        status_callback: Optional[Callable] = None,
    ):
        self.serial = serial
        self.adb_path = adb_path
        self.analysis_provider = analysis_provider
        self.window_handle = window_handle
        self.countdown_callback = countdown_callback
        self.status_callback = status_callback
        self._lock = threading.RLock()
        self._config = {"enabled": False, "anchor": None, "half_width": 10, "min_minutes": 15, "max_minutes": 30, "buffs": [], "random_behavior_enabled": True, "random_behavior_value": 20, "jump_key": "Alt"}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._deadline = None
        # Key and duration of each slot. Turning a skill or the controller off
        # and on must not forget a deadline that was already counting down.
        self._buff_identity = None
        # Buff keys do nothing while the character is walking or jumping.
        self._needs_settle = False
        self._settle_not_before = 0.0

    def update_config(self, config: dict):
        with self._lock:
            normalized = {
                "enabled": bool(config.get("enabled")),
                "anchor": tuple(config.get("anchor")) if config.get("anchor") else None,
                "half_width": max(1, int(config.get("half_width", 10))),
                "min_minutes": max(1, min(1440, int(config.get("min_minutes", 15)))),
                "max_minutes": max(1, min(1440, int(config.get("max_minutes", 30)))),
                # Preserve the UI slot indexes, including empty slots, so one
                # stream can never show another slot's countdown/status.
                "buffs": [
                    {
                        "enabled": bool(buff.get("enabled")),
                        "key": str(buff.get("key") or "").strip(),
                        "duration": max(1.0, float(buff.get("duration", 270) or 270)),
                    }
                    for buff in (config.get("buffs") or [])
                    if isinstance(buff, dict)
                ],
                "random_behavior_enabled": bool(config.get("random_behavior_enabled", True)),
                "random_behavior_value": max(1, min(60, int(config.get("random_behavior_value", 20)))),
                "jump_key": str(config.get("jump_key") or "Alt").strip() or "Alt",
            }
            if normalized["max_minutes"] < normalized["min_minutes"]:
                normalized["max_minutes"] = normalized["min_minutes"]
            if normalized == self._config:
                return
            self._config = normalized
            self._deadline = None

    def update_window_handle(self, window_handle):
        with self._lock:
            self.window_handle = window_handle

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"mumu-smart-walk-{self.serial}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        self._emit_countdown({})

    def _get_window_handle(self):
        with self._lock:
            hwnd = self.window_handle
        return hwnd if hwnd and win32gui.IsWindow(hwnd) else None

    @staticmethod
    def _virtual_key(key: str):
        normalized = str(key or "").strip().lower()
        special = {
            "space": win32con.VK_SPACE,
            "enter": win32con.VK_RETURN,
            "tab": win32con.VK_TAB,
            "alt": win32con.VK_MENU,
            "ctrl": win32con.VK_CONTROL,
            "control": win32con.VK_CONTROL,
            "shift": win32con.VK_SHIFT,
            "esc": win32con.VK_ESCAPE,
            "escape": win32con.VK_ESCAPE,
            "backspace": win32con.VK_BACK,
            "caps": win32con.VK_CAPITAL,
            "insert": win32con.VK_INSERT,
            "home": win32con.VK_HOME,
            "pageup": win32con.VK_PRIOR,
            "delete": win32con.VK_DELETE,
            "end": win32con.VK_END,
            "pagedown": win32con.VK_NEXT,
            "up": win32con.VK_UP,
            "down": win32con.VK_DOWN,
            "left": win32con.VK_LEFT,
            "right": win32con.VK_RIGHT,
        }
        if normalized.startswith("f") and normalized[1:].isdigit():
            number = int(normalized[1:])
            if 1 <= number <= 12:
                return win32con.VK_F1 + number - 1
        if normalized in special:
            return special[normalized]
        if len(normalized) == 1:
            value = win32api.VkKeyScan(normalized)
            if value != -1:
                return value & 0xFF
        return None

    @staticmethod
    def _post_key(hwnd: int, virtual_key: int, pressed: bool):
        scan_code = win32api.MapVirtualKey(virtual_key, 0)
        lparam = 1 | (scan_code << 16)
        if virtual_key in {
            win32con.VK_LEFT,
            win32con.VK_RIGHT,
            win32con.VK_UP,
            win32con.VK_DOWN,
            win32con.VK_INSERT,
            win32con.VK_DELETE,
            win32con.VK_HOME,
            win32con.VK_END,
            win32con.VK_PRIOR,
            win32con.VK_NEXT,
        }:
            lparam |= 1 << 24
        message = win32con.WM_KEYDOWN if pressed else win32con.WM_KEYUP
        if not pressed:
            lparam |= (1 << 30) | (1 << 31)
        win32gui.PostMessage(hwnd, message, virtual_key, lparam)

    def _press_key(self, key: str):
        virtual_key = self._virtual_key(key)
        hwnd = self._get_window_handle()
        if virtual_key is None or hwnd is None:
            return False
        try:
            with _MUMU_INPUT_LOCK:
                self._post_key(hwnd, virtual_key, True)
                # Same hold as Windows live-flower press_key: 50–150 ms.
                time.sleep(random.randint(KEY_HOLD_MIN_MS, KEY_HOLD_MAX_MS) / 1000.0)
                self._post_key(hwnd, virtual_key, False)
            return True
        except Exception:
            return False

    def _emit_status(self, message: str):
        callback = self.status_callback
        if callback is not None:
            callback(str(message))

    def _emit_countdown(self, due: dict, config: Optional[dict] = None, now=None):
        callback = self.countdown_callback
        if callback is None:
            return
        if config is None:
            callback({})
            return
        current = time.monotonic() if now is None else now
        callback(
            {
                index: remaining_seconds(release_at, current)
                for index, release_at in due.items()
                if release_at > 0
                and 0 <= index < len(config.get("buffs", []))
                and config["buffs"][index].get("enabled")
                and config["buffs"][index].get("key")
            }
        )

    def _align_due_buffs(self, due: dict, config: dict) -> dict:
        """Keep deadlines when a skill is only switched off and back on."""
        identity = [
            (str(buff.get("key") or ""), float(buff.get("duration") or 0))
            for buff in (config.get("buffs") or [])
        ]
        if identity == self._buff_identity:
            return due
        previous = self._buff_identity or []
        aligned = {}
        for index, item in enumerate(identity):
            if index < len(previous) and item == previous[index] and index in due:
                aligned[index] = due[index]
            else:
                aligned[index] = 0.0
        self._buff_identity = identity
        return aligned

    def _note_motion(self, kind: str):
        """Remember that a walk or jump must finish before the next BUFF.

        The minimap marker is often hidden, so this does not look at it.
        Direction keys wait about half a second; a jump waits about one second.
        """
        low, high = (0.8, 1.2) if kind == "jump" else (0.4, 0.6)
        settle_at = time.monotonic() + random.uniform(low, high)
        if settle_at > self._settle_not_before:
            self._settle_not_before = settle_at
        self._needs_settle = True

    def _wait_until_settled(self) -> bool:
        """Wait out the random post-move delay before pressing a BUFF."""
        if not self._needs_settle:
            return True
        remaining = self._settle_not_before - time.monotonic()
        if remaining > 0:
            self._emit_status("移动结束，稍等后再释放 BUFF")
            if self._stop.wait(remaining):
                return False
        self._needs_settle = False
        return True

    def _find_position_with_jump(self):
        """Recover the player marker after effects or animation hide it."""
        if self._press_key(self._config.get("jump_key", "Alt")):
            self._note_motion("jump")
        for _ in range(6):
            if self._stop.wait(0.05):
                return None
            analysis = self.analysis_provider()
            position = getattr(analysis, "player_position", None) if analysis is not None else None
            if position is not None:
                return position
        return None

    def _release_due_buffs(self, config: dict, due: dict, now: float):
        due_buffs = [
            (index, buff)
            for index, buff in enumerate(config.get("buffs", []))
            if buff.get("enabled")
            and buff.get("key")
            and now >= due.get(index, 0)
        ]
        if not due_buffs:
            return
        if not self._wait_until_settled():
            return
        for position, (index, buff) in enumerate(due_buffs):
            if self._stop.is_set():
                return
            self._emit_status(f"准备释放 BUFF {index + 1}：{buff['key']}")
            # Match live flower: two short taps, 100–300 ms apart.
            # The countdown starts at the second key-down.
            first_sent = self._press_key(buff["key"])
            pressed_at = None
            if first_sent and not self._stop.wait(random.uniform(0.1, 0.3)):
                pressed_at = time.monotonic()
                second_sent = self._press_key(buff["key"])
            else:
                second_sent = False
            if not (first_sent and second_sent):
                self._emit_status(
                    f"BUFF {index + 1}（{buff['key']}）发送失败，等待下次重试"
                )
                continue
            early = (
                random.uniform(0, config["random_behavior_value"])
                if config["random_behavior_enabled"]
                else 0
            )
            due[index] = next_release_time(
                pressed_at,
                buff["duration"],
                early,
            )
            countdown = remaining_seconds(due[index], pressed_at)
            self._emit_countdown(due, config, pressed_at)
            self._emit_status(
                f"BUFF {index + 1}（{buff['key']}）已释放，下次约 {countdown} 秒"
            )

            # Same gap as live flower: 2–3 seconds between different BUFFs.
            if position < len(due_buffs) - 1:
                gap = random.randint(2000, 3000) / 1000.0
                if self._stop.wait(gap):
                    return

    def _walk_once(self, direction: str, duration: float):
        virtual_key = win32con.VK_LEFT if direction == "left" else win32con.VK_RIGHT
        hwnd = self._get_window_handle()
        if hwnd is None:
            return False
        with _MUMU_INPUT_LOCK:
            self._post_key(hwnd, virtual_key, True)
            try:
                self._stop.wait(duration)
            finally:
                self._post_key(hwnd, virtual_key, False)
        self._note_motion("walk")
        return not self._stop.is_set()

    def _move_into_horizontal_range(self, config: dict) -> bool:
        """Move into the configured X band before the initial BUFF batch."""
        anchor = config.get("anchor")
        if not anchor:
            return True
        center_x = float(anchor[0])
        half_width = float(config.get("half_width", 10))
        minimum_x = center_x - half_width
        maximum_x = center_x + half_width

        analysis = self.analysis_provider()
        position = (
            getattr(analysis, "player_position", None)
            if analysis is not None
            else None
        )
        if position is None:
            position = self._find_position_with_jump()
        if position is None:
            self._emit_status("启动定位：暂未识别到玩家黄点，等待重试")
            return False

        # Only X participates in startup positioning. The marker's Y value is
        # deliberately ignored because platforms may be at different heights.
        if minimum_x <= float(position[0]) <= maximum_x:
            self._emit_status("启动定位：玩家已在智能走左右范围内")
            return True

        self._emit_status(
            f"启动定位：玩家 X={position[0]} 在范围外，正在左右走回范围"
        )
        for _ in range(16):
            if self._stop.is_set():
                return False
            direction = smart_walk_direction(float(position[0]), center_x)
            if not self._walk_once(direction, random.uniform(0.3, 0.6)):
                return False
            if self._stop.wait(0.08):
                return False
            analysis = self.analysis_provider()
            position = (
                getattr(analysis, "player_position", None)
                if analysis is not None
                else None
            )
            if position is None:
                position = self._find_position_with_jump()
            if position is None:
                self._emit_status("启动定位：移动后黄点暂时丢失，等待重试")
                return False
            if minimum_x <= float(position[0]) <= maximum_x:
                self._emit_status(
                    f"启动定位完成：玩家 X={position[0]} 已进入左右范围"
                )
                return True

        self._emit_status("启动定位：本轮未能进入左右范围，稍后继续重试")
        return False

    def _service_once(self, due_buffs, was_enabled, initial_position_pending):
        """Advance one control cycle and always publish a running countdown."""
        with self._lock:
            config = dict(self._config)
        due_buffs = self._align_due_buffs(due_buffs, config)
        just_enabled = bool(config.get("enabled") and not was_enabled)
        if just_enabled:
            initial_position_pending = bool(config.get("anchor"))
        was_enabled = bool(config.get("enabled"))
        if not config.get("enabled"):
            self._emit_countdown({})
            self._deadline = None
            return due_buffs, was_enabled, False

        # Publish before walking back into range. Reopening the settings
        # window, or turning the controller off and on, must not sit on "--"
        # until positioning and the next key press both succeed.
        self._emit_countdown(due_buffs, config)
        anchor = config.get("anchor")
        if not anchor:
            self._release_due_buffs(config, due_buffs, time.monotonic())
            self._emit_countdown(due_buffs, config)
            self._deadline = None
            return due_buffs, was_enabled, False

        now = time.monotonic()
        if initial_position_pending:
            if not self._move_into_horizontal_range(config):
                self._deadline = None
                return due_buffs, was_enabled, True
            initial_position_pending = False
            now = time.monotonic()
        self._release_due_buffs(config, due_buffs, now)
        self._emit_countdown(due_buffs, config)
        if self._deadline is None:
            self._deadline = next_smart_walk_deadline(
                now, config["min_minutes"], config["max_minutes"]
            )
        if now < self._deadline:
            return due_buffs, was_enabled, initial_position_pending

        analysis = self.analysis_provider()
        position = getattr(analysis, "player_position", None) if analysis is not None else None
        if position is None:
            position = self._find_position_with_jump()
        if position is not None:
            direction = smart_walk_direction(position[0], anchor[0])
            started = time.monotonic()
            self._walk_once(direction, random.uniform(0.3, 0.6))
            while not self._stop.is_set() and time.monotonic() - started < 1.2:
                current = self.analysis_provider()
                current_position = getattr(current, "player_position", None) if current is not None else None
                if current_position is None:
                    current_position = self._find_position_with_jump()
                    if current_position is None:
                        break
                if not smart_walk_can_continue(direction, current_position[0], anchor[0], config["half_width"]):
                    break
                time.sleep(0.08)
        self._deadline = next_smart_walk_deadline(
            time.monotonic(), config["min_minutes"], config["max_minutes"]
        )
        return due_buffs, was_enabled, initial_position_pending

    def _run(self):
        due_buffs = {}
        was_enabled = False
        initial_position_pending = False
        while not self._stop.wait(0.2):
            due_buffs, was_enabled, initial_position_pending = self._service_once(
                due_buffs, was_enabled, initial_position_pending
            )

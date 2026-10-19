"""Per-emulator market / BUFF cycle using background keys and ADB touch."""

import random
import subprocess
import time
from contextlib import contextmanager
from collections import deque
from statistics import median

import cv2
import numpy as np

from detection.emulator_frame_analysis import analyze_emulator_frame, analyze_known_emulator_minimap
from detection.emulator_market import EmulatorMarketRecognizer, MARKET_POINT, MENU_POINT
from utils.countdown import next_release_time
from workers.mumu_smart_walk_worker import (
    BUFF_HOLD_MIN_MS, BUFF_HOLD_MAX_MS, MumuSmartWalkWorker, _MUMU_INPUT_LOCK,
)


class MumuDeadFlowerWorker(MumuSmartWalkWorker):
    # Minimap pixels/second at the fixed stream size. Verified on the live
    # client; each instance also refines this from its own visible movement.
    DEFAULT_WALK_SPEED = 10.0
    PORTAL_TOLERANCE = 1.5
    POSITION_SEARCH_SECONDS = 8.0
    MAX_NAVIGATION_SECONDS = 12.0

    def __init__(self, *args, snapshot_provider, redetect_callback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot_provider = snapshot_provider
        self.redetect_callback = redetect_callback or (lambda: None)
        self.recognizer = EmulatorMarketRecognizer()
        self._phase = "locate"
        self._transition_until = 0.0
        self._last_sequence = None
        self._scene_candidate = None
        self._scene_since = 0.0
        self._scene = None
        self._native_size = None
        self._last_status = None
        self._menu_retry_at = 0.0
        self._navigation_rect = None
        self._navigation_ground_y = None
        self._navigation_portal = None
        self._verify_portal_position = False
        self._walk_speeds = {}
        self.analysis_provider = self._fresh_analysis

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None:
            import threading
            if thread is not threading.current_thread():
                thread.join(timeout=5)
        if thread is None or not thread.is_alive():
            self._thread = None
        self._emit_countdown({})

    def update_config(self, config):
        with self._lock:
            super().update_config(config)
            anchor = config.get("portal_anchor")
            self._config["portal_anchor"] = tuple(anchor) if anchor else None
            # Legacy right-left configurations now use a single right step,
            # including starts directly from the instance list.
            self._config["pre_skill_move_mode"] = (
                "left_only" if config.get("pre_skill_move_mode") == "left_only" else "right_only"
            )

    def _emit_status(self, message):
        if message != self._last_status:
            self._last_status = message
            super()._emit_status(message)

    def _snapshot(self):
        snap = self.snapshot_provider()
        age = snap.get("frame_age_ms")
        frame = snap.get("frame")
        if age is None or age > 350 or frame is None or frame.shape[:2] != (540, 960):
            return None
        return snap

    def _fresh_analysis(self):
        snap = self._snapshot()
        return analyze_emulator_frame(snap["frame"]) if snap else None

    def _observe(self):
        snap = self._snapshot()
        if snap is None:
            self._scene_candidate = None
            self._scene = None
            return None, None
        scene = self.recognizer.scene(snap["frame"])
        sequence = snap.get("frame_sequence")
        if sequence == self._last_sequence:
            return None, snap
        self._last_sequence = sequence
        if scene != self._scene_candidate:
            self._scene_candidate = scene
            self._scene_since = time.monotonic()
            return None, snap
        if time.monotonic() - self._scene_since < 0.3 or scene == "unknown":
            return None, snap
        if scene != self._scene:
            self._scene = scene
            self._navigation_rect = None
            self._navigation_portal = None
            self._verify_portal_position = False
            self.redetect_callback()
        return scene, snap

    def _tap(self, point):
        if self._stop.is_set() or self._snapshot() is None:
            return False
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if self._native_size is None:
            import re
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "shell", "wm", "size"],
                capture_output=True, timeout=3, creationflags=flags,
            )
            sizes = re.findall(rb"(?:Physical|Override) size:\s*(\d+)x(\d+)", result.stdout)
            if result.returncode or not sizes:
                raise RuntimeError("无法读取模拟器尺寸")
            w, h = sorted(map(int, sizes[-1]), reverse=True)
            if abs(w / h - 16 / 9) > 0.01:
                raise RuntimeError("死花模式需要 16:9 横屏")
            self._native_size = (w, h)
        w, h = self._native_size
        if self._stop.is_set() or self._snapshot() is None:
            return False
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, "shell", "input", "tap",
             str(round(point[0] * w / 960)), str(round(point[1] * h / 540))],
            capture_output=True, timeout=3, creationflags=flags,
        )
        if result.returncode:
            raise RuntimeError("ADB 点击发送失败")
        return True

    @staticmethod
    def _portal(analysis):
        if analysis is None or analysis.minimap_image is None:
            return None
        hsv = cv2.cvtColor(analysis.minimap_image, cv2.COLOR_BGR2HSV)
        # The translucent portal becomes pale blue over bright scenery. Its
        # complete oval is more reliable than only the saturated blue core.
        mask = cv2.inRange(hsv, np.array([85, 45, 90]), np.array([130, 255, 255]))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if cv2.contourArea(contour) >= 12 and w >= 4 and h >= 6 and 0.3 < w / h < 2:
                candidates.append((x + w / 2, y + h / 2))
        return min(candidates, default=None)

    def _navigation_observation(self):
        """Use a stable market crop, never an old frame or a field minimap."""
        snap = self._snapshot()
        if snap is None or self.recognizer.scene(snap["frame"]) != "market":
            return None
        if self._navigation_rect is None:
            analysis = analyze_emulator_frame(snap["frame"])
            self._navigation_rect = analysis.minimap_rect
        else:
            analysis = analyze_known_emulator_minimap(snap["frame"], self._navigation_rect)
        return snap, analysis

    @contextmanager
    def _hold_navigation_key(self, key):
        """Release the original HWND's key on stop, missing frames or errors.

        Only lock individual messages: a long navigation hold on one instance
        must not postpone another instance's BUFF key transaction.
        """
        hwnd, vk = self._get_window_handle(), self._virtual_key(key)
        if self._stop.is_set() or hwnd is None or vk is None:
            yield False
            return
        try:
            with _MUMU_INPUT_LOCK:
                self._post_key(hwnd, vk, True)
            yield True
        finally:
            with _MUMU_INPUT_LOCK:
                self._post_key(hwnd, vk, False)

    def _find_position_with_jump(self):
        """Keep jump held until new minimap observations reveal a moving dot."""
        self._emit_status("出口定位：持续按住跳跃键寻找黄点")
        found, previous = None, None
        last_sequence = None
        deadline = time.monotonic() + self.POSITION_SEARCH_SECONDS
        with self._hold_navigation_key(self._config.get("jump_key", "Alt")) as held:
            if not held:
                return None
            try:
                while not self._stop.wait(0.04) and time.monotonic() < deadline:
                    observation = self._navigation_observation()
                    if observation is None:
                        break
                    snap, analysis = observation
                    sequence = snap.get("frame_sequence")
                    if sequence == last_sequence:
                        continue
                    last_sequence = sequence
                    position = analysis.player_position
                    if position is None:
                        continue
                    ground = self._navigation_ground_y
                    if ground is not None and not ground - 24 <= position[1] <= ground + 8:
                        continue
                    # A frozen dot (including a yellow decoration) cannot
                    # establish identity. Wait for the actual jump's Y motion.
                    if previous is not None and abs(position[0] - previous[0]) <= 2 and 2 <= abs(position[1] - previous[1]) <= 24:
                        found = position
                        break
                    previous = position
            finally:
                self._note_motion("jump")
        if not self._wait_until_settled("跳跃定位：已松开跳跃键，等待落地后再移动"):
            return None
        if found is None:
            self._emit_status("持续跳跃后仍未确认黄点，等待画面恢复后重试")
            return None
        observation = self._navigation_observation()
        landed = observation[1].player_position if observation else None
        if landed is not None and abs(landed[0] - found[0]) <= 2:
            return landed
        # Ground-level dots may overlap again after landing. The confirmed
        # airborne X stays valid because no horizontal key was held.
        return found

    def _learn_walk_speed(self, direction, samples):
        """Use several progressing observations, not one catch-up frame."""
        if len(samples) < 3:
            return
        estimates = []
        for index, (at, x) in enumerate(samples):
            for end_at, end_x in list(samples)[index + 1:]:
                elapsed, distance = end_at - at, abs(end_x - x)
                if 0.3 <= elapsed <= 1.5 and distance >= 3:
                    value = distance / elapsed
                    reference = self._walk_speeds.get(direction, self.DEFAULT_WALK_SPEED)
                    if reference * 0.5 <= value <= reference * 1.7:
                        estimates.append(value)
        if estimates:
            self._walk_speeds[direction] = median(estimates)

    def _walk_to_portal(self, portal, position):
        """One uninterrupted hold, with visual stop and bounded dead reckoning."""
        direction = "right" if portal[0] > position[0] else "left"
        sign = 1 if direction == "right" else -1
        started = time.monotonic()
        last_x, last_at = position[0], started
        speed = self._walk_speeds.get(direction, self.DEFAULT_WALK_SPEED)
        deadline = started + min(self.MAX_NAVIGATION_SECONDS,
                                 max(0.15, abs(portal[0] - last_x) / speed * 1.5))
        samples = deque([(started, float(last_x))], maxlen=24)
        sequence = None
        result = "estimated"
        self._emit_status(f"连续走向市场出口，参考步速 {speed:.1f} 小地图像素/秒")
        with self._hold_navigation_key("Right" if sign > 0 else "Left") as held:
            if not held:
                return "stopped"
            try:
                while not self._stop.is_set():
                    now = time.monotonic()
                    observation = self._navigation_observation()
                    if observation is None:
                        result = "unavailable"
                        break
                    snap, analysis = observation
                    if snap.get("frame_sequence") != sequence:
                        sequence = snap.get("frame_sequence")
                        point = analysis.player_position
                        if point is not None and abs(point[1] - portal[1]) <= 8:
                            progress = sign * (point[0] - last_x)
                            elapsed = now - last_at
                            # Reject dots that teleport across the map or
                            # appear behind us when another player uncovers.
                            plausible = -1 <= progress <= max(3, speed * elapsed * 2 + 2)
                            if plausible and progress >= 1:
                                last_x, last_at = point[0], now
                                samples.append((now, float(last_x)))
                                self._learn_walk_speed(direction, samples)
                                speed = self._walk_speeds.get(direction, speed)
                            if plausible and sign * (portal[0] - point[0]) <= self.PORTAL_TOLERANCE:
                                result = "observed"
                                break
                    # Identical X does not refresh last_at: scrcpy can keep
                    # sending fresh full frames while the minimap is frozen.
                    projected_x = last_x + sign * speed * (now - last_at)
                    if sign * (portal[0] - projected_x) <= 0.5 or now >= deadline:
                        break
                    if self._stop.wait(0.025):
                        break
            finally:
                self._note_motion("walk")
        if self._stop.is_set():
            return "stopped"
        if result == "estimated":
            self._emit_status("已按步速估算到达出口附近，松开方向键后重新跳跃定位")
        elif result == "observed":
            self._emit_status("黄点已到出口，已松开方向键")
        self._verify_portal_position = result != "observed"
        return result

    def _enter_portal(self, portal, confirmed_x=None):
        if not self._wait_until_settled() or self._stop.is_set():
            return
        latest = self._navigation_observation()
        if latest is None:
            self._verify_portal_position = True
            return
        position = latest[1].player_position
        x = position[0] if position is not None else confirmed_x
        # A delayed minimap can show arrival while the character is still
        # travelling. Check again after releasing and settling; never spend
        # 30 seconds waiting for a portal entered from the wrong position.
        if x is None or abs(x - portal[0]) > self.PORTAL_TOLERANCE:
            self._verify_portal_position = True
            return
        if self._press_key("Up", (180, 260)):
            self._phase = "leaving"
            self._transition_until = time.monotonic() + 30
            self._emit_status("已按上进入出口，等待离开市场")

    def _leave_step(self, config):
        observation = self._navigation_observation()
        if observation is None:
            return
        _, analysis = observation
        detected = self._portal(analysis) if not config.get("portal_anchor") else None
        if detected is not None:
            self._navigation_portal = detected
        portal = config.get("portal_anchor") or self._navigation_portal
        if portal is None:
            self._emit_status("未找到市场出口，请在死花选项卡的小地图上标记出口")
            return
        self._navigation_ground_y = portal[1]
        position = analysis.player_position if analysis else None
        recovered = False
        if position is None or self._verify_portal_position:
            position = self._find_position_with_jump()
            if position is None:
                return
            recovered = True
            self._verify_portal_position = False
        # Jump recovery already waits for landing; its airborne observation
        # is useful for X even if the yellow marker is hidden again at rest.
        if not recovered and abs(position[1] - portal[1]) > 8:
            self._emit_status("角色与市场出口不在同一层，请先将角色放到出口层")
            return
        delta = portal[0] - position[0]
        if abs(delta) <= self.PORTAL_TOLERANCE:
            self._enter_portal(portal, position[0] if recovered else None)
            return
        if not self._wait_until_settled():
            return
        if self._walk_to_portal(portal, position) == "observed":
            # Direction is already up; verify a fresh dot before entering.
            latest = self._navigation_observation()
            point = latest[1].player_position if latest else None
            if point is not None and abs(point[0] - portal[0]) <= self.PORTAL_TOLERANCE:
                self._enter_portal(portal)
            else:
                self._verify_portal_position = True

    def _cast(self, config, due):
        ready = [(i, b) for i, b in enumerate(config["buffs"])
                 if b["enabled"] and b["key"] and due.get(i, 0) <= time.monotonic() + 10]
        for slot, (index, buff) in enumerate(ready):
            for press in range(2):
                snap = self._snapshot()
                if self._stop.is_set() or not snap or self.recognizer.scene(snap["frame"]) != "field":
                    return False
                pressed_at = time.monotonic()
                if not self._press_key(buff["key"], (BUFF_HOLD_MIN_MS, BUFF_HOLD_MAX_MS)):
                    self._emit_status(f"BUFF {index + 1} 发送失败，等待重试")
                    return False
                if press == 0 and self._stop.wait(random.uniform(0.1, 0.3)):
                    return False
            early = random.uniform(0, config["random_behavior_value"]) if config["random_behavior_enabled"] else 0
            due[index] = next_release_time(pressed_at, buff["duration"], early)
            self._emit_countdown(due, config)
            if slot < len(ready) - 1 and self._stop.wait(random.uniform(1, 2)):
                return False
        return True

    def _service_once(self, due, was_enabled, unused):
        with self._lock:
            config = dict(self._config)
        due = self._align_due_buffs(due, config)
        enabled = config["enabled"]
        if not enabled:
            self._emit_countdown({})
            return due, False, False
        if not was_enabled:
            self._phase = "locate"
            self._menu_retry_at = 0.0
            self._navigation_rect = None
            self._navigation_portal = None
            self._verify_portal_position = False
            self._last_sequence = self._scene_candidate = self._scene = None
            for i, buff in enumerate(config["buffs"]):
                if buff["enabled"] and buff["key"]:
                    due[i] = 0.0
        self._emit_countdown(due, config)
        scene, snap = self._observe()
        if scene is None:
            self._emit_status("等待新的游戏画面 / 过图中")
            return due, True, False
        needed = any(b["enabled"] and b["key"] and due.get(i, 0) <= time.monotonic()
                     for i, b in enumerate(config["buffs"]))
        if not any(b["enabled"] and b["key"] for b in config["buffs"]):
            self._emit_status("请至少启用并配置一个 BUFF")
            return due, True, False
        if self._phase == "returning":
            if scene == "market":
                self._phase = "locate"
                self._emit_status("已回到自由市场，等待 BUFF 到期")
            elif time.monotonic() >= self._transition_until:
                self._phase = "return"
            return due, True, False
        if self._phase == "leaving":
            if scene == "field":
                mode = config["pre_skill_move_mode"]
                direction = "left" if mode == "left_only" else "right"
                if not self._stop.is_set():
                    self._walk_once(direction, random.uniform(0.1, 0.3))
                self._wait_until_settled()
                self._phase = "locate"
            elif time.monotonic() >= self._transition_until:
                self._phase = "locate"
            return due, True, False
        if self._phase == "return" or scene == "menu":
            if scene == "market":
                self._phase = "locate"
            elif scene == "field":
                # MENU is a toggle: give slow instances time to publish the
                # open menu instead of tapping again and immediately closing it.
                if time.monotonic() >= self._menu_retry_at and self._tap(MENU_POINT):
                    self._menu_retry_at = time.monotonic() + 2
                    self._phase = "return"
                    self._emit_status("已打开 MENU，等待自由市场列表")
            elif scene == "menu" and self._tap(MARKET_POINT):
                self._phase = "returning"
                self._transition_until = time.monotonic() + 30
                self._emit_status("已点击自由市场，等待传送完成")
            return due, True, False
        if scene == "market":
            if needed:
                self._leave_step(config)
            else:
                self._emit_status("自由市场内等待 BUFF 到期")
        elif scene == "field":
            if needed:
                self._emit_status("正在怪物地图释放 BUFF")
                if not self._cast(config, due):
                    return due, True, False
                if self._stop.wait(random.uniform(1.2, 1.8)):
                    return due, True, False
            self._phase = "return"
        return due, True, False

    def _run(self):
        due, enabled = {}, False
        while not self._stop.wait(0.2):
            try:
                due, enabled, _ = self._service_once(due, enabled, False)
            except Exception as exc:
                self._emit_status(f"死花流程暂停重试：{exc}")
                self._stop.wait(1)

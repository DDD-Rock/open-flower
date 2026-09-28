"""One-shot, per-emulator smoke and friend-channel refresh controller."""

from __future__ import annotations

import random
import re
import subprocess
import threading
import time

import cv2
import win32con
import win32gui

from detection.emulator_smoke_recognizer import (
    is_social_panel, online_friend, read_text, together_action,
)
from workers.mumu_smart_walk_worker import (
    BUFF_HOLD_MAX_MS, BUFF_HOLD_MIN_MS, MumuSmartWalkWorker, _MUMU_INPUT_LOCK,
)


class SmokeError(RuntimeError):
    pass


class MumuSmokeWorker:
    SOCIAL_POINT = (882, 36)
    LOGIN_POINT = (740, 355)
    CHARACTER_POINT = (650, 205)
    LOGIN_EVIDENCE = ("密码", "登录", "登入")
    CHARACTER_EVIDENCE = "新建角色"

    def __init__(self, serial, adb_path, snapshot_provider, window_provider,
                 status_callback=None, finished_callback=None):
        self.serial = serial
        self.adb_path = adb_path
        self.snapshot_provider = snapshot_provider
        self.window_provider = window_provider
        self.status_callback = status_callback or (lambda message: None)
        self.finished_callback = finished_callback or (lambda success: None)
        self._stop = threading.Event()
        self._thread = None
        self._native_size = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, config):
        if self.running:
            return False
        self._stop.clear()
        self._native_size = None
        self._thread = threading.Thread(
            target=self._run, args=(dict(config),),
            name=f"mumu-smoke-{self.serial}", daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _status(self, message):
        self.status_callback(str(message))

    def _snapshot(self):
        warned = False
        while not self._stop.is_set():
            snapshot = self.snapshot_provider()
            frame_age = snapshot.get("frame_age_ms")
            if frame_age is not None and frame_age <= 1000:
                return snapshot
            if not warned:
                self._status("等待新的视频帧")
                warned = True
            self._stop.wait(0.25)
        raise SmokeError("用户已停止")

    def _wait_for(self, predicate, timeout, message, poll=0.4):
        self._status(message)
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop.is_set() and (deadline is None or time.monotonic() < deadline):
            result = predicate(self._snapshot())
            if result is not None and result is not False:
                return result
            self._stop.wait(poll)
        if self._stop.is_set():
            raise SmokeError("用户已停止")
        raise SmokeError(f"等待超时：{message}")

    def _position(self, snapshot):
        analysis = snapshot.get("analysis")
        # The settings panel and smoke flow must use the same yellow-point
        # result.  Analysis can be older than one second while OCR/full-map
        # recognition is running, even though the panel already displays its
        # valid coordinates; rejecting it here caused false "marker missing"
        # decisions.
        if analysis is None or analysis.player_position is None:
            return None
        return analysis.player_position

    def _key(self, key, minimum=80, maximum=120):
        hwnd = self.window_provider()
        vk = MumuSmartWalkWorker._virtual_key(key)
        if not hwnd or not win32gui.IsWindow(hwnd) or vk is None:
            raise SmokeError(f"无法发送按键 {key}：模拟器窗口或按键无效")
        with _MUMU_INPUT_LOCK:
            MumuSmartWalkWorker._post_key(hwnd, vk, True)
            try:
                if self._stop.wait(random.randint(minimum, maximum) / 1000):
                    raise SmokeError("用户已停止")
            finally:
                MumuSmartWalkWorker._post_key(hwnd, vk, False)

    def _down_jump(self, jump_key):
        hwnd = self.window_provider()
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise SmokeError("模拟器窗口已断开")
        with _MUMU_INPUT_LOCK:
            MumuSmartWalkWorker._post_key(hwnd, win32con.VK_DOWN, True)
            try:
                self._key(jump_key)
            finally:
                MumuSmartWalkWorker._post_key(hwnd, win32con.VK_DOWN, False)

    def _locate_position(self, jump_key, down=False):
        """Keep jumping until the player marker is visible again."""
        jumped = False
        while not self._stop.is_set():
            position = self._position(self._snapshot())
            if position is not None:
                if jumped:
                    self._status("黄点已出现，等待跳跃落地")
                    if self._stop.wait(1.2):
                        raise SmokeError("用户已停止")
                return position
            if down:
                self._status("黄点暂时不可见，继续下跳寻找位置")
                self._down_jump(jump_key)
            else:
                self._status("黄点不可见，原地跳跃确认位置")
                self._key(jump_key)
            jumped = True
            if self._stop.wait(1.2):
                raise SmokeError("用户已停止")
        raise SmokeError("用户已停止")

    def _move_to_anchor(self, config):
        anchor = config["anchor"]
        x_tolerance = int(config["half_width"])
        y_tolerance = int(config["half_height"])
        position = self._locate_position(config["jump_key"])
        while not self._stop.is_set():
            if position[1] > anchor[1] + y_tolerance:
                raise SmokeError("角色位于烟雾标点下方，不能继续下跳")
            if abs(position[1] - anchor[1]) <= y_tolerance:
                break
            self._status("下跳到标点同层")
            self._down_jump(config["jump_key"])
            if self._stop.wait(1.2):
                raise SmokeError("用户已停止")
            position = self._locate_position(config["jump_key"], down=True)
        while not self._stop.is_set():
            if abs(position[1] - anchor[1]) > y_tolerance:
                raise SmokeError("左右移动时离开目标层，已停止")
            delta = anchor[0] - position[0]
            if abs(delta) <= x_tolerance:
                self._status(f"已到达烟雾位置：X={position[0]} Y={position[1]}")
                return
            direction = "Right" if delta > 0 else "Left"
            hold = (120, 200) if abs(delta) <= 15 else (250, 420)
            self._key(direction, *hold)
            self._stop.wait(0.25)
            position = self._wait_for(lambda snap: self._position(snap), None, "短走后复核位置")
        raise SmokeError("用户已停止")

    def _tap(self, point, label):
        if self._stop.is_set():
            raise SmokeError("用户已停止")
        frame = self._snapshot()["frame"]
        if frame is None:
            raise SmokeError("模拟器没有画面")
        width, height = frame.shape[1], frame.shape[0]
        if (width, height) != (960, 540):
            raise SmokeError("烟雾模式需要 960 × 540 视频流")
        x, y = point
        if not (0 <= x < width and 0 <= y < height):
            raise SmokeError(f"{label}点击坐标超出画面")
        native_width, native_height = self._display_size()
        native_x = min(native_width - 1, round(x * native_width / width))
        native_y = min(native_height - 1, round(y * native_height / height))
        self._status(f"点击{label} ({native_x}, {native_y})")
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "shell", "input", "tap",
                 str(native_x), str(native_y)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise SmokeError(f"点击{label}失败：{exc}") from exc
        if result.returncode:
            raise SmokeError(f"点击{label}失败：ADB 返回 {result.returncode}")

    def _display_size(self):
        if self._native_size is None:
            try:
                result = subprocess.run(
                    [self.adb_path, "-s", self.serial, "shell", "wm", "size"],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                sizes = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",
                                   result.stdout.decode("ascii", errors="replace"))
                if result.returncode or not sizes:
                    raise SmokeError("无法读取模拟器显示尺寸")
                width, height = sorted(map(int, sizes[-1]), reverse=True)
                if not width or not height or abs(width / height - 16 / 9) > 0.01:
                    raise SmokeError("烟雾模式仅支持 16:9 横屏布局")
                self._native_size = (width, height)
            except OSError as exc:
                raise SmokeError(f"读取模拟器显示尺寸失败：{exc}") from exc
        return self._native_size

    def _text(self, snap):
        frame = snap["frame"]
        if frame is None or frame.shape[:2] != (540, 960):
            return []
        enlarged = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_NEAREST)
        blocks = read_text(enlarged)
        return [
            {**block, "box": [[x / 2, y / 2] for x, y in block["box"]]}
            for block in blocks
        ]

    def _dismiss_login_overlays(self):
        while not self._stop.is_set():
            texts = [block.get("text", "") for block in self._text(self._snapshot())]
            if any("每日" in value and ("奖励" in value or "獎勵" in value) for value in texts):
                self._tap((610, 335), "每日奖励确认")
            elif any("連續簽到" in value or "连续签到" in value for value in texts):
                self._tap((682, 146), "签到窗口关闭")
            else:
                return
            if self._stop.wait(1):
                raise SmokeError("用户已停止")
        raise SmokeError("用户已停止")

    def _tap_until_page_disappears(self, evidence, point, label):
        def visible(snapshot):
            return any(
                any(word in block.get("text", "") for word in evidence)
                for block in self._text(snapshot)
            )

        self._wait_for(visible, None, f"等待{label}页面", 1)
        missing = 0
        while not self._stop.is_set():
            if visible(self._snapshot()):
                missing = 0
                self._tap(point, label)
                if self._stop.wait(1.5):
                    break
            else:
                missing += 1
                if missing >= 2:
                    return
                if self._stop.wait(0.7):
                    break
        raise SmokeError("用户已停止")

    def _login_to_character(self):
        """Handle login reappearing while the server finishes the transition."""
        character_seen = False
        missing = 0
        while not self._stop.is_set():
            texts = self._text(self._snapshot())
            has_character = self._page_visible(texts, (self.CHARACTER_EVIDENCE,))
            has_login = self._page_visible(texts, self.LOGIN_EVIDENCE)
            if has_character:
                character_seen = True
                missing = 0
                self._tap(self.CHARACTER_POINT, "进入角色")
                if self._stop.wait(1.5):
                    break
                continue
            if has_login:
                missing = 0
                self._tap(self.LOGIN_POINT, "登录")
                if self._stop.wait(1.5):
                    break
                continue
            if character_seen:
                missing += 1
                if missing >= 2:
                    return
            else:
                self._status("等待登录/角色选择页面")
            if self._stop.wait(0.7):
                break
        raise SmokeError("用户已停止")

    def _page_visible(self, blocks, evidence):
        evidence = tuple("".join(str(word).split()) for word in evidence)
        return any(
            any(word in "".join(str(block.get("text", "")).split()) for word in evidence)
            for block in blocks
        )

    def _run(self, config):
        success = False
        try:
            friend_name = config.get("friend_name", "").strip()
            initial_text = self._text(self._snapshot())
            login_open = self._page_visible(initial_text, self.LOGIN_EVIDENCE)
            character_open = self._page_visible(initial_text, (self.CHARACTER_EVIDENCE,))

            # Starting on either authentication page should bootstrap into the
            # game, then continue through the usual smoke/channel workflow.
            if login_open or character_open:
                page = "登录" if login_open else "角色选择"
                self._status(f"启动时检测到{page}页面，继续进入游戏")
                self._login_to_character()
                self._dismiss_login_overlays()
                initial_text = self._text(self._snapshot())

            if not friend_name:
                raise SmokeError("请设置好友名称")

            # The operator may start while the social panel is already open.
            # In that case go straight to the friend/channel refresh flow.
            social_open = is_social_panel(initial_text) or online_friend(initial_text, friend_name) is not None
            while not self._stop.is_set():
                if not social_open:
                    if not config.get("anchor"):
                        raise SmokeError("请标记烟雾位置")
                    self._move_to_anchor(config)
                    self._stop.wait(0.5)
                    self._status("连续两次释放烟雾技能")
                    for index in range(2):
                        self._key(config["smoke_key"], BUFF_HOLD_MIN_MS, BUFF_HOLD_MAX_MS)
                        if index == 0 and self._stop.wait(random.uniform(0.1, 0.3)):
                            raise SmokeError("用户已停止")
                    # The social entry is opened immediately after the second
                    # key press; there is intentionally no fixed cooldown.
                    self._status("烟雾双按完成，立即打开社交列表")
                    self._tap(self.SOCIAL_POINT, "社交入口")

                self._wait_for(
                    lambda snap: (
                        True if is_social_panel(blocks := self._text(snap))
                        else online_friend(blocks, friend_name) is not None
                    ),
                    None, "等待社交好友列表", 0.25,
                )
                friend = self._wait_for(
                    lambda snap: online_friend(self._text(snap), friend_name),
                    None, "识别指定在线好友", 0.25,
                )
                self._tap(friend, "在线好友")
                action = self._wait_for(
                    lambda snap: together_action(self._text(snap)),
                    None, "识别一起畅游游戏", 0.25,
                )
                self._tap(action, "一起畅游游戏")
                self._wait_for(
                    lambda snap: (
                        self._page_visible(self._text(snap), self.LOGIN_EVIDENCE)
                        or self._page_visible(self._text(snap), (self.CHARACTER_EVIDENCE,))
                    ),
                    None,
                    "等待登录/角色选择页面",
                    0.7,
                )
                self._login_to_character()
                self._wait_for(lambda snap: self._position(snap), None, "等待重新进入游戏")
                self._dismiss_login_overlays()
                self._wait_for(lambda snap: self._position(snap), None, "确认游戏内小地图")
                success = True
                self._status("本轮频道刷新完成，继续下一轮烟雾流程")
                # The next iteration starts from the game screen and performs
                # the next smoke release.  A social panel is only a startup
                # shortcut, never a persistent state for later iterations.
                social_open = False
        except SmokeError as exc:
            self._status(str(exc))
        except Exception as exc:
            self._status(f"烟雾流程异常：{exc}")
        finally:
            self.finished_callback(success)

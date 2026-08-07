"""只读监控会话：持续捕获小地图，不发送任何键盘或鼠标输入。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QThread, pyqtSignal

from detection.exp_recognizer import EXPRapidOCRRecognizer, EXPRecognitionStabilizer
from detection.minimap_monitor import MinimapMonitor
from detection.mouse_follow_verification_detector import (
    MouseFollowVerificationDetector,
    MouseFollowVerificationStabilizer,
)
from detection.rune_alert_detector import RuneAlertDetector, RuneAlertStabilizer
from models.map_topology import MinimapVisualMatcher
from utils.verification_region_recorder import VerificationRegionRecorder


class MonitorWorker(QThread):
    frame_ready = pyqtSignal(object)
    status_update = pyqtSignal(str)
    rune_update = pyqtSignal(bool, object)
    verification_update = pyqtSignal(bool, object)
    verification_recording_update = pyqtSignal(str)
    exp_update = pyqtSignal(object, str)
    error_signal = pyqtSignal(str)
    stopped = pyqtSignal()

    TARGET_INTERVAL = 1 / 30
    MAP_MATCH_INTERVAL_FRAMES = 6
    RUNE_INTERVAL_FRAMES = 30
    VERIFICATION_INTERVAL_FRAMES = 15
    VERIFICATION_RECORDING_INTERVAL_FRAMES = 3
    EXP_INTERVAL_FRAMES = 15
    WINDOW_CHECK_INTERVAL_FRAMES = 30
    MAP_MISS_LIMIT = 5

    def __init__(self, hwnd: int, maps=None, window_selector=None, parent=None):
        super().__init__(parent)
        self.hwnd = hwnd
        self.maps = list(maps or [])
        self.window_selector = window_selector
        self._running = False
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self._matched_map = None
        self._map_misses = 0

    def stop(self):
        self._running = False
        self.requestInterruption()
        if self.isRunning() and QThread.currentThread() is not self:
            self.wait(2000)

    def run(self):
        self._running = True
        rune_state = RuneAlertStabilizer()
        verification_state = MouseFollowVerificationStabilizer()
        verification_recorder = VerificationRegionRecorder()
        exp_recognizer = EXPRapidOCRRecognizer()
        exp_state = EXPRecognitionStabilizer()
        exp_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exp-ocr")
        exp_future = None
        frame_index = 0
        fps_started_at = time.monotonic()
        fps_frames = 0
        measured_fps = 0.0
        try:
            self.status_update.emit("正在识别小地图")
            if self.monitor.auto_detect_dark_region() is None:
                raise RuntimeError(self.monitor.last_detection_summary or "无法识别小地图")
            self.status_update.emit("小地图已识别，正在监控")

            while self._running and not self.isInterruptionRequested():
                started = time.monotonic()
                if (
                    frame_index % self.WINDOW_CHECK_INTERVAL_FRAMES == 0
                    and self.window_selector is not None
                    and not self.window_selector.is_window_valid(self.hwnd)
                ):
                    raise RuntimeError("游戏窗口已关闭或失效")

                image = self.monitor.capture_minimap()
                if image is None:
                    self.status_update.emit("小地图截图失败，正在重新识别")
                    if self.monitor.auto_detect_dark_region() is None:
                        self._interruptible_sleep(0.3)
                        continue
                    image = self.monitor.capture_minimap()
                    if image is None:
                        self._interruptible_sleep(0.1)
                        continue

                player, _ = MinimapMonitor.find_player_position_in_image(image)
                teammates = MinimapMonitor.find_teammate_positions_in_image(image)
                others = MinimapMonitor.find_other_player_positions_in_image(image)
                if frame_index % self.MAP_MATCH_INTERVAL_FRAMES == 0:
                    self._match_map(image)

                fps_frames += 1
                elapsed = time.monotonic() - fps_started_at
                if elapsed >= 1:
                    measured_fps = fps_frames / elapsed
                    fps_frames = 0
                    fps_started_at = time.monotonic()

                self.frame_ready.emit(
                    {
                        "image": image,
                        "player": player,
                        "teammates": teammates,
                        "others": others,
                        "map": self._matched_map,
                        "fps": measured_fps,
                        "capturedAt": int(time.time() * 1000),
                    }
                )

                verification_interval = (
                    self.VERIFICATION_RECORDING_INTERVAL_FRAMES
                    if verification_state.is_present
                    else self.VERIFICATION_INTERVAL_FRAMES
                )
                verification_due = frame_index % verification_interval == 0
                if (
                    frame_index % self.RUNE_INTERVAL_FRAMES == 0
                    or frame_index % self.EXP_INTERVAL_FRAMES == 0
                    or verification_due
                ):
                    full_image = self.monitor.capture_game_screen()
                else:
                    full_image = None
                if exp_future is not None and exp_future.done():
                    try:
                        reading = exp_future.result()
                    except Exception:
                        reading = None
                    exp_future = None
                    stable = exp_state.update(reading)
                    self.exp_update.emit(
                        stable,
                        stable.display_text if stable else "尚未识别到 EXP",
                    )
                if (
                    frame_index % self.EXP_INTERVAL_FRAMES == 0
                    and full_image is not None
                    and exp_future is None
                ):
                    exp_future = exp_executor.submit(
                        exp_recognizer.recognize,
                        full_image.copy(),
                    )
                if frame_index % self.RUNE_INTERVAL_FRAMES == 0:
                    detection = (
                        RuneAlertDetector.detect(full_image)
                        if full_image is not None
                        else None
                    )
                    changed = rune_state.update(detection)
                    if changed or rune_state.is_present:
                        self.rune_update.emit(rune_state.is_present, rune_state.latest_detection)
                if verification_due:
                    detection = (
                        MouseFollowVerificationDetector.detect(full_image)
                        if full_image is not None
                        else None
                    )
                    changed = verification_state.update(detection)
                    try:
                        if verification_state.is_present and full_image is not None:
                            body_rect = (
                                verification_state.latest_detection.body_rect
                                if verification_state.latest_detection is not None
                                else None
                            )
                            if not verification_recorder.is_recording and body_rect is not None:
                                path = verification_recorder.start(full_image, body_rect)
                                self.verification_recording_update.emit(
                                    f"已开始录制验证区域：{path.name}"
                                )
                            elif verification_recorder.is_recording:
                                verification_recorder.append(full_image, body_rect)
                        elif verification_recorder.is_recording:
                            path = verification_recorder.stop()
                            self.verification_recording_update.emit(
                                f"验证区域录像已保存：{path}"
                            )
                    except Exception as error:
                        verification_recorder.stop()
                        self.verification_recording_update.emit(
                            f"验证区域录制失败：{error}"
                        )
                    if changed or verification_state.is_present:
                        self.verification_update.emit(
                            verification_state.is_present,
                            verification_state.latest_detection,
                        )

                frame_index += 1
                remaining = self.TARGET_INTERVAL - (time.monotonic() - started)
                if remaining > 0:
                    self._interruptible_sleep(remaining)
        except Exception as error:
            self.error_signal.emit(str(error))
        finally:
            completed_recording = verification_recorder.stop()
            if completed_recording is not None:
                self.verification_recording_update.emit(
                    f"验证区域录像已保存：{completed_recording}"
                )
            exp_executor.shutdown(wait=False, cancel_futures=True)
            self._running = False
            self.stopped.emit()

    def _match_map(self, image):
        if not self.maps:
            self._matched_map = None
            return
        signature = MinimapVisualMatcher.signature(image)
        matches = []
        for topology in self.maps:
            if topology.visual_signature:
                comparison = MinimapVisualMatcher.comparison(
                    signature,
                    topology.visual_signature,
                )
                if comparison["isMatch"]:
                    matches.append((comparison["similarityPercentage"], topology))
        candidate = max(matches, default=(0, None), key=lambda item: item[0])[1]
        if candidate is not None:
            self._map_misses = 0
            if self._matched_map is None or candidate.map_name != self._matched_map.map_name:
                self._matched_map = candidate
                self.status_update.emit(f"已匹配：{candidate.map_name}")
        elif self._matched_map is not None:
            self._map_misses += 1
            if self._map_misses >= self.MAP_MISS_LIMIT:
                self._matched_map = None
                self.status_update.emit("未匹配到已标注地图")

    def _interruptible_sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))

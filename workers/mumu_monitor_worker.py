"""Experimental multi-instance MuMu video monitor."""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QThread, pyqtSignal

from detection.emulator_frame_analysis import (
    analyze_emulator_frame,
    analyze_known_emulator_minimap,
    apply_game_state_grace,
)
from utils.mumu_adb import connect_adb_device, list_adb_devices, resolve_adb_path
from utils.mumu_manager import (
    MumuManagerError,
    launch_mumu_instance,
    list_mumu_instances,
    resolve_mumu_cli_path,
)
from utils.mumu_scrcpy_stream import ScrcpyVideoStream
from workers.mumu_smart_walk_worker import MumuSmartWalkWorker


class MumuMonitorWorker(QThread):
    devices_update = pyqtSignal(object)
    frame_ready = pyqtSignal(str, object, float)
    analysis_ready = pyqtSignal(str, object)
    minimap_frame_ready = pyqtSignal(str, object, object)
    smart_walk_countdown = pyqtSignal(str, object)
    smart_walk_status = pyqtSignal(str, str)
    status_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    stopped = pyqtSignal()

    SCAN_INTERVAL = 2.0
    UI_FRAME_INTERVAL = 1 / 12
    ANALYSIS_INTERVAL = 0.10
    FULL_ANALYSIS_INTERVAL = 2.0
    MAX_ANALYSIS_AGE = 0.25

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._stop_event = threading.Event()
        self._refresh_requested = True
        self._lock = threading.RLock()
        self._streams = {}
        self._devices = {}
        self._latest_frames = {}
        self._latest_fps = {}
        self._frame_sequences = {}
        self._latest_frame_at = {}
        self._frame_times = {}
        self._last_ui_frame_at = {}
        self._last_analysis_at = {}
        self._last_full_analysis_at = {}
        self._minimap_rects = {}
        self._last_game_evidence_at = {}
        self._latest_analysis = {}
        self._analysis_sequences = {}
        self._latest_analysis_frame_at = {}
        self._analysis_processing_ms = {}
        self._dropped_analysis = {}
        self._analysis_inflight = set()
        self._recognition_generations = {}
        self._force_full_analysis = set()
        self._analysis_executor = ThreadPoolExecutor(
            max_workers=5,
            thread_name_prefix="mumu-analysis",
        )
        self._restart_after = {}
        self._stream_errors = {}
        self._smart_walk_workers = {}
        self._window_handles = {}
        self._pending_launches = set()
        self._launching = set()
        self._launch_started_at = {}
        self._launch_errors = {}
        self._adb_connect_after = {}
        self._last_manager_error = ""
        self._manager_instances = []
        self.adb_path = resolve_adb_path()
        self.mumu_cli_path = resolve_mumu_cli_path()

    def request_refresh(self):
        self._refresh_requested = True

    def request_minimap_redetection(self, serial: str):
        """Forget one locked minimap region and locate it on the newest frame."""
        if not serial:
            return
        with self._lock:
            self._minimap_rects.pop(serial, None)
            self._latest_analysis.pop(serial, None)
            self._recognition_generations[serial] = (
                self._recognition_generations.get(serial, 0) + 1
            )
            self._force_full_analysis.add(serial)
            self._last_full_analysis_at.pop(serial, None)

    def update_smart_walk_config(self, serial: str, config: dict):
        """Update one stream's smart-walk configuration without touching others."""
        if not serial:
            return
        with self._lock:
            controller = self._smart_walk_workers.get(serial)
            if controller is None:
                controller = MumuSmartWalkWorker(
                    serial,
                    self.adb_path,
                    lambda current=serial: self.get_latest_analysis(current),
                    window_handle=self._window_handles.get(serial),
                    countdown_callback=lambda countdown, current=serial: self.smart_walk_countdown.emit(
                        current, countdown
                    ),
                    status_callback=lambda message, current=serial: self.smart_walk_status.emit(
                        current, message
                    ),
                )
                self._smart_walk_workers[serial] = controller
                controller.start()
        controller.update_config(config or {})

    def request_launch(self, vm_index: str):
        """Queue one instance launch without blocking the Qt UI thread."""
        index = str(vm_index).strip()
        if not index.isdigit():
            self.error_signal.emit("MuMu 实例编号无效")
            return
        with self._lock:
            if index in self._launching or index in self._pending_launches:
                return
            self._pending_launches.add(index)
            self._launching.add(index)
            self._launch_started_at[index] = time.monotonic()
            self._launch_errors.pop(index, None)
        self._refresh_requested = True

    def get_latest_frame(self, serial: str):
        """Return the latest BGR frame for future recognition workers."""
        with self._lock:
            return self._latest_frames.get(serial)

    def get_latest_fps(self, serial: str) -> float:
        with self._lock:
            return float(self._latest_fps.get(serial, 0.0))

    def get_latest_stream_snapshot(self, serial: str):
        """Return latest references plus revisions so the UI can drop stale work."""
        with self._lock:
            now = time.monotonic()
            frame_at = self._latest_frame_at.get(serial)
            analysis_frame_at = self._latest_analysis_frame_at.get(serial)
            return {
                "frame": self._latest_frames.get(serial),
                "fps": float(self._latest_fps.get(serial, 0.0)),
                "frame_age_ms": (
                    max(0.0, (now - frame_at) * 1000)
                    if frame_at is not None
                    else None
                ),
                "frame_sequence": int(self._frame_sequences.get(serial, 0)),
                "analysis": self._latest_analysis.get(serial),
                "analysis_age_ms": (
                    max(0.0, (now - analysis_frame_at) * 1000)
                    if analysis_frame_at is not None
                    else None
                ),
                "analysis_processing_ms": self._analysis_processing_ms.get(serial),
                "dropped_analysis": int(self._dropped_analysis.get(serial, 0)),
                "analysis_sequence": int(self._analysis_sequences.get(serial, 0)),
            }

    def get_latest_analysis(self, serial: str):
        """Return the latest minimap/game-state result for a stream."""
        with self._lock:
            return self._latest_analysis.get(serial)

    def get_latest_stream_serials(self):
        """Return serials that currently have decoded frames, without copying frames."""
        with self._lock:
            return tuple(self._latest_frames)

    def stop(self):
        self._running = False
        self._stop_event.set()
        self.requestInterruption()
        with self._lock:
            streams = list(self._streams.values())
            smart_walkers = list(self._smart_walk_workers.values())
        for stream in streams:
            stream.stop()
        for controller in smart_walkers:
            controller.stop()
        if self.isRunning() and QThread.currentThread() is not self:
            self.wait(10000)

    def run(self):
        if self._stop_event.is_set():
            self.stopped.emit()
            return
        self._running = True
        next_scan_at = 0.0
        try:
            while (
                self._running
                and not self._stop_event.is_set()
                and not self.isInterruptionRequested()
            ):
                now = time.monotonic()
                with self._lock:
                    has_launch_request = bool(self._pending_launches)
                if has_launch_request:
                    self._process_launch_requests()
                if self._refresh_requested or now >= next_scan_at:
                    self._refresh_requested = False
                    self._scan_once()
                    next_scan_at = time.monotonic() + self.SCAN_INTERVAL
                self.msleep(100)
        finally:
            self._running = False
            with self._lock:
                streams = list(self._streams.values())
                smart_walkers = list(self._smart_walk_workers.values())
                self._streams.clear()
                self._smart_walk_workers.clear()
            for stream in streams:
                stream.stop()
            for controller in smart_walkers:
                controller.stop()
            self._analysis_executor.shutdown(wait=True, cancel_futures=True)
            self.stopped.emit()

    def _process_launch_requests(self):
        with self._lock:
            indexes = sorted(self._pending_launches, key=int)
            self._pending_launches.clear()
        for index in indexes:
            if not self._running or self._stop_event.is_set():
                return
            try:
                launch_mumu_instance(index, self.mumu_cli_path)
            except MumuManagerError as exc:
                message = str(exc)
                with self._lock:
                    self._launching.discard(index)
                    self._launch_errors[index] = message
                self.error_signal.emit(f"MuMu-{index} 启动失败：{message}")
            else:
                self.status_update.emit(f"已发送 MuMu-{index} 启动指令")
        self._refresh_requested = True

    def _scan_once(self):
        instances = None
        manager_error = ""
        try:
            instances = list_mumu_instances(self.mumu_cli_path)
            with self._lock:
                self._manager_instances = instances
        except MumuManagerError as exc:
            manager_error = str(exc)
            with self._lock:
                instances = [dict(item) for item in self._manager_instances] or None

        devices = list_adb_devices(self.adb_path)
        if not self._running or self.isInterruptionRequested():
            return
        adb_error = ""
        if len(devices) == 1 and devices[0].get("state") == "error":
            adb_error = devices[0].get("error") or "ADB 连接失败"
            devices = []

        preferred_serials = {
            item.get("adb_serial")
            for item in (instances or [])
            if item.get("adb_serial")
        }
        devices = self._deduplicate_adb_aliases(devices, preferred_serials)
        discovered = {item["serial"]: item for item in devices if item.get("serial")}
        now = time.monotonic()
        connected_any = False
        for instance in instances or []:
            serial = instance.get("adb_serial") or ""
            if not instance.get("is_android_started") or not serial:
                continue
            if discovered.get(serial, {}).get("state") == "device":
                continue
            if now < self._adb_connect_after.get(serial, 0):
                continue
            self._adb_connect_after[serial] = now + 4
            success, _ = connect_adb_device(serial, self.adb_path)
            connected_any = connected_any or success
        if connected_any:
            refreshed = list_adb_devices(self.adb_path)
            if not (len(refreshed) == 1 and refreshed[0].get("state") == "error"):
                refreshed = self._deduplicate_adb_aliases(
                    refreshed, preferred_serials
                )
                discovered = {
                    item["serial"]: item for item in refreshed if item.get("serial")
                }

        online_serials = {
            serial
            for serial, item in discovered.items()
            if item.get("state") == "device"
        }
        with self._lock:
            removed = set(self._streams) - online_serials
            removed_streams = [self._streams.pop(serial) for serial in removed]
            removed_walkers = [self._smart_walk_workers.pop(serial, None) for serial in removed]
            for serial in removed:
                self._latest_frames.pop(serial, None)
                self._latest_fps.pop(serial, None)
                self._frame_sequences.pop(serial, None)
                self._latest_frame_at.pop(serial, None)
                self._frame_times.pop(serial, None)
                self._last_ui_frame_at.pop(serial, None)
                self._last_analysis_at.pop(serial, None)
                self._last_full_analysis_at.pop(serial, None)
                self._minimap_rects.pop(serial, None)
                self._last_game_evidence_at.pop(serial, None)
                self._latest_analysis.pop(serial, None)
                self._analysis_sequences.pop(serial, None)
                self._latest_analysis_frame_at.pop(serial, None)
                self._analysis_processing_ms.pop(serial, None)
                self._dropped_analysis.pop(serial, None)
                self._recognition_generations.pop(serial, None)
                self._force_full_analysis.discard(serial)
                self._stream_errors.pop(serial, None)
            self._devices = discovered
        for stream in removed_streams:
            stream.stop()
        for controller in removed_walkers:
            if controller is not None:
                controller.stop()

        for serial in online_serials:
            with self._lock:
                existing = self._streams.get(serial)
                retry_at = self._restart_after.get(serial, 0)
            if existing is not None and existing.is_alive:
                continue
            if now < retry_at:
                continue
            if existing is not None:
                existing.stop()
            stream = ScrcpyVideoStream(
                serial,
                on_frame=lambda frame, current=serial: self._on_frame(current, frame),
                on_error=lambda message, current=serial: self._on_stream_error(
                    current, message
                ),
                adb_path=self.adb_path,
            )
            with self._lock:
                self._streams[serial] = stream
                self._restart_after[serial] = now + 3
            stream.start()

        payload = []
        matched_serials = set()
        with self._lock:
            self._window_handles = {
                item.get("adb_serial"): self._parse_window_handle(
                    item.get("render_wnd") or item.get("main_wnd")
                )
                for item in (instances or [])
                if item.get("adb_serial")
                and (item.get("render_wnd") or item.get("main_wnd"))
            }
            for serial, controller in self._smart_walk_workers.items():
                controller.update_window_handle(self._window_handles.get(serial))
            for instance in instances or []:
                item = dict(instance)
                index = item["vm_index"]
                serial = item.get("adb_serial") or ""
                device = discovered.get(serial, {})
                if serial:
                    matched_serials.add(serial)
                if item.get("is_android_started"):
                    self._launching.discard(index)
                    self._launch_started_at.pop(index, None)
                elif (
                    index in self._launching
                    and now - self._launch_started_at.get(index, now) > 90
                ):
                    self._launching.discard(index)
                    self._launch_errors[index] = "启动超时，请在 MuMu 多开器中检查"
                item["id"] = f"mumu:{index}"
                item["serial"] = serial
                item["model"] = device.get("model") or (
                    f"Android {item['android_version']}" if item.get("android_version") else ""
                )
                if device.get("state") == "device":
                    item["state"] = "device"
                elif item.get("is_android_started"):
                    item["state"] = "connecting"
                elif item.get("is_process_started") or index in self._launching:
                    item["state"] = "booting"
                else:
                    item["state"] = "offline"
                item["launching"] = index in self._launching
                item["launch_error"] = self._launch_errors.get(index, "")
                stream = self._streams.get(serial)
                frame = self._latest_frames.get(serial)
                item["streaming"] = bool(stream and stream.is_alive)
                item["frame_error"] = self._stream_errors.get(serial, "")
                if frame is not None:
                    item["frame_width"] = int(frame.shape[1])
                    item["frame_height"] = int(frame.shape[0])
                payload.append(item)
            for serial, device in discovered.items():
                if serial in matched_serials:
                    continue
                item = dict(device)
                item.update(
                    {
                        "id": f"adb:{serial}",
                        "name": "未映射的 Android 模拟器",
                        "vm_index": "",
                        "is_process_started": True,
                        "is_android_started": item.get("state") == "device",
                    }
                )
                stream = self._streams.get(serial)
                frame = self._latest_frames.get(serial)
                item["streaming"] = bool(stream and stream.is_alive)
                item["frame_error"] = self._stream_errors.get(serial, "")
                if frame is not None:
                    item["frame_width"] = int(frame.shape[1])
                    item["frame_height"] = int(frame.shape[0])
                payload.append(item)
            self._devices = {item["id"]: item for item in payload}
        stream_count = sum(bool(item.get("streaming")) for item in payload)
        powered_count = sum(bool(item.get("is_process_started")) for item in payload)
        if instances is not None:
            status = (
                f"已发现 {len(payload)} 个实例，开机 {powered_count} 路，"
                f"视频流 {stream_count} 路"
            )
        else:
            status = f"已发现 {len(payload)} 路在线模拟器，视频流 {stream_count} 路"
        self.status_update.emit(status)
        self.devices_update.emit(payload)
        if manager_error and manager_error != self._last_manager_error:
            self.error_signal.emit(f"MuMu 实例列表读取失败：{manager_error}")
        self._last_manager_error = manager_error
        if adb_error:
            self.error_signal.emit(adb_error)

    @staticmethod
    def _deduplicate_adb_aliases(devices, preferred_serials=None):
        """Collapse multiple ADB serials pointing at the same Android boot."""
        preferred = set(preferred_serials or ())
        selected = {}
        order = []
        for device in devices or []:
            serial = device.get("serial") or ""
            boot_id = device.get("boot_id") or ""
            identity = ("boot", boot_id) if boot_id else ("serial", serial)
            existing = selected.get(identity)
            if existing is None:
                selected[identity] = device
                order.append(identity)
                continue
            existing_serial = existing.get("serial") or ""
            if serial in preferred and existing_serial not in preferred:
                selected[identity] = device
        return [selected[identity] for identity in order]

    @staticmethod
    def _parse_window_handle(value):
        try:
            return int(str(value), 16)
        except (TypeError, ValueError):
            return None

    def _on_frame(self, serial: str, frame):
        now = time.monotonic()
        with self._lock:
            self._latest_frames[serial] = frame
            self._latest_frame_at[serial] = now
            self._frame_sequences[serial] = self._frame_sequences.get(serial, 0) + 1
            self._stream_errors.pop(serial, None)
            times = self._frame_times.setdefault(serial, deque())
            times.append(now)
            while times and times[0] < now - 1.0:
                times.popleft()
            fps = float(len(times))
            self._latest_fps[serial] = fps
            last_ui = self._last_ui_frame_at.get(serial, 0)
            emit_ui_frame = now - last_ui >= self.UI_FRAME_INTERVAL
            if emit_ui_frame:
                self._last_ui_frame_at[serial] = now
            last_analysis = self._last_analysis_at.get(serial, 0)
            known_rect = self._minimap_rects.get(serial)
            force_full_analysis = serial in self._force_full_analysis
            last_full_analysis = self._last_full_analysis_at.get(serial, 0)
            full_analysis_due = (
                known_rect is None
                and (
                    force_full_analysis
                    or now - last_full_analysis >= self.FULL_ANALYSIS_INTERVAL
                )
            )
            analyze_frame = (
                now - last_analysis >= self.ANALYSIS_INTERVAL
                and serial not in self._analysis_inflight
                and self._running
                and not self._stop_event.is_set()
                and (known_rect is not None or full_analysis_due)
            )
            if analyze_frame:
                self._last_analysis_at[serial] = now
                self._analysis_inflight.add(serial)
            run_full_analysis = analyze_frame and full_analysis_due
            if run_full_analysis:
                self._last_full_analysis_at[serial] = now
                self._force_full_analysis.discard(serial)
            recognition_generation = self._recognition_generations.get(serial, 0)

        if analyze_frame:
            try:
                self._analysis_executor.submit(
                    self._analyze_latest_frame,
                    serial,
                    known_rect,
                    run_full_analysis,
                    recognition_generation,
                )
            except RuntimeError:
                with self._lock:
                    self._analysis_inflight.discard(serial)

        if emit_ui_frame:
            self.frame_ready.emit(serial, frame, fps)

    def _analyze_latest_frame(
        self,
        serial: str,
        known_rect,
        run_full_analysis: bool,
        recognition_generation: int,
    ):
        try:
            # The executor may be busy with other emulator streams. Read the
            # newest frame only when this task actually starts so queued work
            # can never analyze an old video frame.
            with self._lock:
                frame = self._latest_frames.get(serial)
                captured_at = self._latest_frame_at.get(serial, time.monotonic())
            analysis = None
            if run_full_analysis:
                analysis = analyze_emulator_frame(frame)
                with self._lock:
                    if (
                        self._recognition_generations.get(serial, 0)
                        != recognition_generation
                    ):
                        return
                    if analysis.minimap_rect is None:
                        self._minimap_rects.pop(serial, None)
                    else:
                        self._minimap_rects[serial] = analysis.minimap_rect
            elif known_rect is not None:
                analysis = analyze_known_emulator_minimap(frame, known_rect)

            if analysis is None or self._stop_event.is_set():
                return
            with self._lock:
                if (
                    self._recognition_generations.get(serial, 0)
                    != recognition_generation
                ):
                    return
                last_evidence = self._last_game_evidence_at.get(serial)
            analysis, last_evidence = apply_game_state_grace(
                analysis, last_evidence, captured_at
            )
            completed_at = time.monotonic()
            with self._lock:
                if (
                    self._recognition_generations.get(serial, 0)
                    != recognition_generation
                ):
                    return
                latest_frame_at = self._latest_frame_at.get(serial, captured_at)
                if (
                    latest_frame_at > captured_at
                    and completed_at - captured_at > self.MAX_ANALYSIS_AGE
                ):
                    self._dropped_analysis[serial] = (
                        self._dropped_analysis.get(serial, 0) + 1
                    )
                    return
                if last_evidence is not None:
                    self._last_game_evidence_at[serial] = last_evidence
                self._latest_analysis[serial] = analysis
                self._latest_analysis_frame_at[serial] = captured_at
                self._analysis_processing_ms[serial] = max(
                    0.0, (completed_at - captured_at) * 1000
                )
                self._analysis_sequences[serial] = (
                    self._analysis_sequences.get(serial, 0) + 1
                )
            self.analysis_ready.emit(serial, analysis)
            if analysis.minimap_image is not None:
                self.minimap_frame_ready.emit(
                    serial, analysis.minimap_image, analysis.minimap_rect
                )
        finally:
            with self._lock:
                self._analysis_inflight.discard(serial)

    def _on_stream_error(self, serial: str, message: str):
        with self._lock:
            self._stream_errors[serial] = message
            self._restart_after[serial] = time.monotonic() + 3
        self.error_signal.emit(f"{serial}：{message}")

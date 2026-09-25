"""Low-latency scrcpy 4.1 video stream for one Android emulator."""

from __future__ import annotations

import os
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import av

from utils.mumu_adb import resolve_adb_path


SCRCPY_SERVER_VERSION = "4.1"
REMOTE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"


def resolve_scrcpy_server_path(adb_path: Optional[str] = None) -> Optional[str]:
    """Find the scrcpy server shipped beside adb or the packaged app."""
    candidates = []
    configured = os.environ.get("SCRCPY_DIR")
    if configured:
        candidates.append(Path(configured) / "scrcpy-server")
    if adb_path and adb_path.lower() != "adb.exe":
        candidates.append(Path(adb_path).resolve().parent / "scrcpy-server")
    executable_dir = Path(sys.executable).resolve().parent
    bundle_dir = Path(getattr(sys, "_MEIPASS", executable_dir))
    candidates.extend(
        (
            bundle_dir / "scrcpy-server",
            bundle_dir / "scrcpy" / "scrcpy-server",
            executable_dir / "scrcpy-server",
            executable_dir / "scrcpy" / "scrcpy-server",
            Path(r"D:\scrcpy-win64-v4.1\scrcpy-server"),
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


class ScrcpyVideoStream:
    """Receive and decode a continuous raw H.264 stream from scrcpy-server."""

    def __init__(
        self,
        serial: str,
        on_frame: Callable,
        on_error: Callable[[str], None],
        max_size: int = 960,
        bit_rate: int = 3_000_000,
        max_fps: int = 30,
        adb_path: Optional[str] = None,
        server_path: Optional[str] = None,
    ):
        self.serial = serial
        self.on_frame = on_frame
        self.on_error = on_error
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.max_fps = max_fps
        self.adb_path = adb_path or resolve_adb_path()
        self.server_path = server_path or resolve_scrcpy_server_path(self.adb_path)
        self._stop_event = threading.Event()
        self._thread = None
        self._server_process = None
        self._socket = None
        self._container = None
        self._local_port = None

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.is_alive:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"scrcpy-video-{self.serial}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        process = self._server_process
        if process is not None and process.poll() is None:
            process.terminate()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _run(self):
        try:
            self._stream_frames()
        except Exception as exc:
            if not self._stop_event.is_set():
                self.on_error(str(exc))
        finally:
            self._cleanup()

    def _stream_frames(self):
        if not self.server_path:
            raise RuntimeError(
                "找不到 scrcpy-server，请设置 SCRCPY_DIR 或将 scrcpy 放到 D:\\scrcpy-win64-v4.1"
            )
        self._run_adb(["push", self.server_path, REMOTE_SERVER_PATH], timeout=12)
        scid = random.randint(1, 0x7FFFFFFF)
        socket_name = f"scrcpy_{scid:08x}"
        local_port = self._reserve_local_port()
        self._local_port = local_port
        self._run_adb(
            ["forward", f"tcp:{local_port}", f"localabstract:{socket_name}"],
            timeout=5,
        )

        command = [
            self.adb_path,
            "-s",
            self.serial,
            "shell",
            f"CLASSPATH={REMOTE_SERVER_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_SERVER_VERSION,
            f"scid={scid:08x}",
            "log_level=warn",
            "tunnel_forward=true",
            "audio=false",
            "control=false",
            "cleanup=false",
            "raw_stream=true",
            f"max_size={self.max_size}",
            f"video_bit_rate={self.bit_rate}",
            f"max_fps={self.max_fps}",
        ]
        self._server_process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._socket = self._connect(local_port)
        self._socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            256 * 1024,
        )
        stream_file = self._socket.makefile("rb", buffering=0)
        decoded_frames = 0
        try:
            self._container = av.open(
                stream_file,
                mode="r",
                format="h264",
            )
            video_stream = self._container.streams.video[0]
            video_stream.codec_context.thread_count = 1
            for decoded in self._container.decode(video=0):
                if self._stop_event.is_set():
                    return
                decoded_frames += 1
                self.on_frame(decoded.to_ndarray(format="bgr24"))
        finally:
            container = self._container
            self._container = None
            if container is not None:
                container.close()
            stream_file.close()
        if not decoded_frames and not self._stop_event.is_set():
            raise RuntimeError(self._read_server_error() or "scrcpy 视频流未返回画面")

    def _run_adb(self, args: list[str], timeout: float):
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(message or f"ADB 命令失败：{' '.join(args)}")

    @staticmethod
    def _reserve_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _connect(self, port: int) -> socket.socket:
        deadline = time.monotonic() + 6
        last_error = None
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            if self._server_process and self._server_process.poll() is not None:
                raise RuntimeError("scrcpy-server 启动失败")
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                # Some emulator encoders need several seconds before emitting
                # the SPS/PPS. Closing their first accepted socket after one
                # second also terminates scrcpy-server, so use the whole startup
                # deadline for this initial byte.
                remaining = max(0.1, deadline - time.monotonic())
                sock.settimeout(remaining)
                first_byte = sock.recv(1, socket.MSG_PEEK)
                if first_byte:
                    sock.settimeout(None)
                    return sock
                sock.close()
            except OSError as exc:
                last_error = exc
                try:
                    sock.close()
                except (OSError, UnboundLocalError):
                    pass
                time.sleep(0.1)
        server_error = self._read_server_error()
        detail = server_error or str(last_error or "等待首帧超时")
        raise RuntimeError(f"无法连接 scrcpy 视频端口：{detail}")

    def _cleanup(self):
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        process = self._server_process
        self._server_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        if self._local_port is not None:
            try:
                subprocess.run(
                    [
                        self.adb_path,
                        "-s",
                        self.serial,
                        "forward",
                        "--remove",
                        f"tcp:{self._local_port}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._local_port = None

    def _read_server_error(self) -> str:
        process = self._server_process
        if process is None or process.poll() is None or process.stdout is None:
            return ""
        try:
            data = process.stdout.read()
        except OSError:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace").strip()
        return str(data).strip()

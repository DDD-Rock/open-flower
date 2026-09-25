"""Small ADB helpers used by the experimental MuMu mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def _query_adb_boot_id(serial: str, adb: str) -> str:
    """Return one Android boot identity, shared by ADB aliases of one VM."""
    try:
        result = subprocess.run(
            [adb, "-s", serial, "shell", "cat", "/proc/sys/kernel/random/boot_id"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip().lower()


def resolve_adb_path() -> Optional[str]:
    """Find adb next to scrcpy first, then fall back to PATH."""
    candidates = []
    scrcpy_dir = os.environ.get("SCRCPY_DIR")
    if scrcpy_dir:
        candidates.append(Path(scrcpy_dir) / "adb.exe")
    executable_dir = Path(sys.executable).resolve().parent
    bundle_dir = Path(getattr(sys, "_MEIPASS", executable_dir))
    candidates.extend(
        (
            bundle_dir / "adb.exe",
            bundle_dir / "scrcpy" / "adb.exe",
            executable_dir / "adb.exe",
            executable_dir / "scrcpy" / "adb.exe",
            Path(r"D:\scrcpy-win64-v4.1\adb.exe"),
            Path(r"D:\scrcpy\adb.exe"),
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "adb.exe"


def list_adb_devices(adb_path: Optional[str] = None) -> list[dict]:
    """Return ADB devices that look like Android emulators."""
    adb = adb_path or resolve_adb_path()
    try:
        result = subprocess.run(
            [adb, "devices", "-l"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [{"serial": "", "state": "error", "error": str(exc)}]

    devices = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[:2]
        # MuMu normally exposes emulator-XXXX or a localhost TCP serial.
        # Keep model hints as a fallback for custom MuMu serial formats.
        details = {"serial": serial, "state": state, "model": ""}
        for token in parts[2:]:
            if token.startswith("model:"):
                details["model"] = token[6:].replace("_", " ")
            elif token.startswith("transport_id:"):
                details["transport_id"] = token.split(":", 1)[1]
        model_lower = details["model"].lower()
        serial_lower = serial.lower()
        likely_emulator = (
            serial_lower.startswith(("emulator-", "127.0.0.1:", "localhost:"))
            or "mumu" in model_lower
            or "emulator" in model_lower
        )
        if likely_emulator:
            if state == "device":
                details["boot_id"] = _query_adb_boot_id(serial, adb)
            devices.append(details)
    return devices


def connect_adb_device(serial: str, adb_path: Optional[str] = None) -> tuple[bool, str]:
    """Connect the shared ADB server to one MuMu localhost endpoint."""
    if not serial.startswith(("127.0.0.1:", "localhost:")):
        return False, "ADB 地址不是本机端口"
    adb = adb_path or resolve_adb_path()
    try:
        result = subprocess.run(
            [adb, "connect", serial],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    message = (result.stdout or result.stderr).strip()
    lowered = message.lower()
    success = result.returncode == 0 and (
        "connected to" in lowered or "already connected" in lowered
    )
    return success, message


def capture_adb_frame(serial: str, adb_path: Optional[str] = None) -> tuple[Optional[np.ndarray], str]:
    """Capture one PNG frame from an online ADB device."""
    adb = adb_path or resolve_adb_path()
    try:
        result = subprocess.run(
            [adb, "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        return None, message or f"adb exited with code {result.returncode}"
    # exec-out is binary-safe; do not normalize line endings because PNG chunks
    # may legitimately contain arbitrary CR/LF byte sequences.
    image = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None, "无法解码 ADB 返回的 PNG 画面"
    return image, ""

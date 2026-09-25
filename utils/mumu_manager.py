"""MuMu Player multi-instance manager integration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


class MumuManagerError(RuntimeError):
    """Raised when the installed MuMu manager cannot complete a request."""


def resolve_mumu_cli_path() -> Optional[str]:
    """Locate the official mumu-cli shipped with MuMu Player 6."""
    candidates: list[Path] = []
    configured = os.environ.get("MUMU_CLI")
    if configured:
        candidates.append(Path(configured))

    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        (
            executable_dir / "mumu-cli.exe",
            executable_dir / "MuMuPlayer" / "nx_main" / "mumu-cli.exe",
        )
    )

    appdata = os.environ.get("APPDATA")
    if appdata:
        install_config = (
            Path(appdata)
            / "Netease"
            / "MuMuPlayerGlobal"
            / "install_config.json"
        )
        try:
            config = json.loads(install_config.read_text(encoding="utf-8"))
            install_dir = config.get("product", {}).get("install_dir")
            if install_dir:
                candidates.append(Path(install_dir) / "nx_main" / "mumu-cli.exe")
        except (OSError, ValueError, TypeError):
            pass

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(env_name)
        if program_files:
            candidates.append(
                Path(program_files)
                / "Netease"
                / "MuMuPlayer"
                / "nx_main"
                / "mumu-cli.exe"
            )
    candidates.append(
        Path(r"C:\Program Files\Netease\MuMuPlayer\nx_main\mumu-cli.exe")
    )

    seen = set()
    for candidate in candidates:
        normalized = str(candidate).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file():
            return str(candidate)
    return None


def _run_cli(cli_path: str, *args: str, timeout: float = 10) -> str:
    try:
        result = subprocess.run(
            [cli_path, *args],
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MumuManagerError(str(exc)) from exc
    stdout = _decode_cli_output(result.stdout)
    stderr = _decode_cli_output(result.stderr)
    if result.returncode != 0:
        message = (stderr or stdout).strip()
        raise MumuManagerError(message or f"mumu-cli exited with code {result.returncode}")
    return stdout.strip()


def _decode_cli_output(value) -> str:
    if isinstance(value, str):
        return value
    if not value:
        return ""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode(errors="replace")


def _adb_serial_for_instance(
    cli_path: str,
    android_version: str,
    vm_index: str,
) -> str:
    install_root = Path(cli_path).resolve().parent.parent
    vms_dir = install_root / "vms"
    patterns = []
    if android_version:
        patterns.append(f"*-{android_version}-{vm_index}")
    patterns.append(f"*-*-{vm_index}")
    for pattern in patterns:
        for vm_dir in sorted(vms_dir.glob(pattern)):
            config_path = vm_dir / "configs" / "vm_config.json"
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                port = config["vm"]["nat"]["port_forward"]["adb"]["host_port"]
                port_number = int(port)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if 1 <= port_number <= 65535:
                return f"127.0.0.1:{port_number}"
    return ""


def _list_instances_from_disk(cli_path: str) -> list[dict]:
    """Read the durable instance catalog when the MuMu RPC is unavailable."""
    vms_dir = Path(cli_path).resolve().parent.parent / "vms"
    instances = []
    for vm_dir in vms_dir.iterdir() if vms_dir.is_dir() else ():
        if not vm_dir.is_dir():
            continue
        match = re.search(r"-(\d+(?:\.\d+)?)-(\d+)$", vm_dir.name)
        if not match:
            continue
        android_version, vm_index = match.groups()
        name = f"MuMu-{vm_index}"
        try:
            extra = json.loads(
                (vm_dir / "configs" / "extra_config.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            name = str(extra.get("playerName") or name)
        except (OSError, ValueError, TypeError):
            pass
        instances.append(
            {
                "instance_id": vm_index,
                "vm_index": vm_index,
                "name": name,
                "android_version": android_version,
                "is_process_started": False,
                "is_android_started": False,
                "error_code": 0,
                # The disk fallback cannot distinguish an assigned port from
                # a template port, so keep offline instances unmapped.
                "adb_serial": "",
            }
        )
    return sorted(instances, key=lambda item: int(item["vm_index"]))


def list_mumu_instances(cli_path: Optional[str] = None) -> list[dict]:
    """Return every configured MuMu instance, including powered-off ones."""
    cli = cli_path or resolve_mumu_cli_path()
    if not cli:
        raise MumuManagerError("未找到 MuMuPlayer 的 mumu-cli.exe")
    try:
        output = _run_cli(cli, "info", "--vmindex", "all", timeout=3)
    except MumuManagerError:
        instances = _list_instances_from_disk(cli)
        if instances:
            return instances
        raise
    try:
        data = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise MumuManagerError("mumu-cli 返回了无法解析的实例列表") from exc
    if not isinstance(data, dict):
        raise MumuManagerError("mumu-cli 返回的实例列表格式不正确")

    instances = []
    for key, raw in data.items():
        if not isinstance(raw, dict):
            continue
        vm_index = str(raw.get("index", key)).strip()
        if not vm_index:
            continue
        android_version = str(raw.get("android_version") or "").strip()
        try:
            error_code = int(raw.get("error_code") or 0)
        except (TypeError, ValueError):
            error_code = -1
        is_process_started = bool(raw.get("is_process_started"))
        is_android_started = bool(raw.get("is_android_started"))
        adb_host = str(raw.get("adb_host_ip") or "127.0.0.1").strip()
        try:
            adb_port = int(raw.get("adb_port") or 0)
        except (TypeError, ValueError):
            adb_port = 0
        if adb_port and is_process_started:
            adb_serial = f"{adb_host}:{adb_port}"
        elif is_process_started or is_android_started:
            adb_serial = _adb_serial_for_instance(cli, android_version, vm_index)
        else:
            # Offline VM configs retain template ports which may be shared by
            # several never-started instances. They must not be matched to ADB.
            adb_serial = ""
        instances.append(
            {
                "instance_id": vm_index,
                "vm_index": vm_index,
                "name": str(raw.get("name") or f"MuMu-{vm_index}"),
                "android_version": android_version,
                "is_process_started": is_process_started,
                "is_android_started": is_android_started,
                "error_code": error_code,
                "adb_serial": adb_serial,
                "main_wnd": str(raw.get("main_wnd") or ""),
                "render_wnd": str(raw.get("render_wnd") or ""),
            }
        )
    return sorted(
        instances,
        key=lambda item: (
            0,
            int(item["vm_index"]),
        )
        if item["vm_index"].isdigit()
        else (1, item["vm_index"]),
    )


def launch_mumu_instance(vm_index: str, cli_path: Optional[str] = None) -> str:
    """Launch exactly one MuMu instance by its manager index."""
    index = str(vm_index).strip()
    if not index.isdigit():
        raise MumuManagerError("MuMu 实例编号无效")
    cli = cli_path or resolve_mumu_cli_path()
    if not cli:
        raise MumuManagerError("未找到 MuMuPlayer 的 mumu-cli.exe")
    return _run_cli(cli, "control", "--vmindex", index, "launch", timeout=20)

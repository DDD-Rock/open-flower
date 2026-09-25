"""Persistent settings dedicated to the experimental MuMu mode."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class MumuSettingsStore:
    """Store per-device settings keyed by the stable ADB serial."""

    def __init__(self, path: str | None = None):
        base = Path(path) if path else Path(os.environ.get("APPDATA") or Path.home()) / "YzY-Auto-Buff" / "mumu_settings.json"
        self.path = base

    def load(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        devices = payload.get("devices", {}) if isinstance(payload, dict) else {}
        if not isinstance(devices, dict):
            return {}
        # Runtime start/stop is deliberately not persistent. Every fresh app
        # launch starts all emulator controllers stopped while keeping the
        # remaining per-device configuration.
        return {
            str(serial): self._persistent_config(config)
            for serial, config in devices.items()
            if isinstance(config, dict)
        }

    @staticmethod
    def _persistent_config(config: dict) -> dict:
        saved = dict(config or {})
        saved["enabled"] = False
        saved.pop("half_height", None)
        # Remove legacy emulator-only chair settings now that the option no
        # longer exists in the MuMu live-flower mode.
        saved.pop("sit_chair_enabled", None)
        saved.pop("chair_key", None)
        return saved

    def save(self, devices: dict) -> bool:
        try:
            persistent_devices = {
                str(serial): self._persistent_config(config)
                for serial, config in (devices or {}).items()
                if isinstance(config, dict)
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="mumu_settings_", suffix=".tmp", dir=str(self.path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "devices": persistent_devices}, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
            return True
        except (OSError, TypeError, ValueError):
            try:
                os.unlink(temporary)
            except (OSError, UnboundLocalError):
                pass
            return False

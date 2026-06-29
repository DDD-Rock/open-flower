"""Simple offline activation for YzY - Auto Buff."""

import configparser
import hashlib
import os
import platform
import sys
import uuid
from typing import Optional


class LicenseManager:
    """Generate machine codes and validate offline activation codes."""

    PRODUCT_NAME = "AutoBuff"
    LICENSE_SECRET = "wxw752"
    MASTER_ACTIVATION_CODE = "ZHIMAKAIMENYZY"
    DEFAULT_LICENSE_FILE = "license.ini"

    def __init__(self, license_path: Optional[str] = None):
        self.license_path = (
            license_path
            or os.environ.get("AUTOBUFF_LICENSE_PATH")
            or self._default_license_path()
        )

    def current_machine_code(self) -> str:
        return self.machine_code_from_source(self._machine_source())

    @classmethod
    def machine_code_from_source(cls, source: str) -> str:
        return cls._md5_hex(f"{source}{cls.PRODUCT_NAME}")

    @classmethod
    def expected_activation_code(cls, machine_code: str) -> str:
        normalized_machine_code = cls.normalize(machine_code)
        return cls._md5_hex(
            f"{normalized_machine_code}{cls.PRODUCT_NAME}{cls.LICENSE_SECRET}"
        )

    @classmethod
    def normalize(cls, value: str) -> str:
        return "".join(ch for ch in str(value).upper() if ch.isalnum())

    def saved_activation_code(self) -> str:
        parser = configparser.ConfigParser()
        if not os.path.exists(self.license_path):
            return ""
        parser.read(self.license_path, encoding="utf-8")
        return parser.get("License", "activation_code", fallback="")

    def is_activated(self) -> bool:
        return self.is_valid_activation_code(self.saved_activation_code())

    def save_activation_code(self, code: str) -> bool:
        normalized = self.normalize(code)
        if not self.is_valid_activation_code(normalized):
            return False

        parser = configparser.ConfigParser()
        parser["License"] = {"activation_code": normalized}
        parent = os.path.dirname(os.path.abspath(self.license_path))
        os.makedirs(parent, exist_ok=True)
        with open(self.license_path, "w", encoding="utf-8") as file:
            parser.write(file)
        return True

    def clear_activation(self):
        if os.path.exists(self.license_path):
            os.remove(self.license_path)

    def is_valid_activation_code(self, code: str) -> bool:
        normalized = self.normalize(code)
        return (
            normalized == self.MASTER_ACTIVATION_CODE
            or normalized == self.expected_activation_code(self.current_machine_code())
        )

    @classmethod
    def _md5_hex(cls, value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest().upper()

    def _default_license_path(self) -> str:
        if os.name == "nt":
            app_data = os.environ.get("APPDATA") or os.path.expanduser("~")
            license_dir = os.path.join(app_data, "YzY-Auto-Buff")
            return os.path.join(license_dir, self.DEFAULT_LICENSE_FILE)
        return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), self.DEFAULT_LICENSE_FILE)

    def _machine_source(self) -> str:
        windows_guid = self._windows_machine_guid()
        if windows_guid:
            return windows_guid

        machine_id = self._linux_machine_id()
        if machine_id:
            return machine_id

        return f"{platform.node()}-{uuid.getnode()}"

    def _windows_machine_guid(self) -> Optional[str]:
        if os.name != "nt":
            return None
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(value).strip() or None
        except Exception:
            return None

    def _linux_machine_id(self) -> Optional[str]:
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    value = file.read().strip()
                if value:
                    return value
            except OSError:
                continue
        return None

"""Account authentication shared with the AutoBuff monitor service."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


class AccountError(Exception):
    """A user-facing account authentication error."""


class AccountManager:
    DEFAULT_SERVER_BASE_URL = "http://106.52.208.129:28671"

    def __init__(self, storage_path: Optional[str] = None, server_base_url: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else self._default_storage_path()
        self.server_base_url = (
            server_base_url
            or os.environ.get("AUTOBUFF_MONITOR_SERVER")
            or self.DEFAULT_SERVER_BASE_URL
        ).rstrip("/")

    def authenticate(self, username: str, password: str) -> str:
        response = self._request(
            "/api/auth/login",
            method="POST",
            body={"username": username.strip(), "password": password},
        )
        token = str(response.get("accessToken") or "")
        account = str((response.get("user") or {}).get("username") or "")
        if not token or not account:
            raise AccountError("监控服务器返回了无效数据")
        self._save(token, account)
        return account

    def restore(self) -> Optional[str]:
        credentials = self._load()
        if not credentials:
            return None
        token = str(credentials.get("accessToken") or "")
        if not token:
            return None
        try:
            response = self._request("/api/auth/me", token=token)
        except AccountError:
            self.logout()
            return None
        account = str(response.get("username") or "")
        if not account:
            self.logout()
            return None
        self._save(token, account)
        return account

    def logout(self):
        try:
            self.storage_path.unlink()
        except FileNotFoundError:
            pass

    @property
    def registration_url(self) -> str:
        return f"{self.server_base_url}/register"

    def _request(self, path: str, method: str = "GET", body=None, token: str = "") -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.server_base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data is not None else {}),
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                message = payload.get("message")
            except (ValueError, UnicodeDecodeError):
                message = None
            raise AccountError(message or f"登录请求失败（{error.code}）") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AccountError("无法连接监控服务器，请检查网络") from error

    def _load(self) -> Optional[dict]:
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None

    def _save(self, token: str, username: str):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(
                {"accessToken": token, "username": username},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _default_storage_path() -> Path:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or Path.home())
            return base / "YzY-Auto-Buff" / "account.json"
        return Path.home() / ".config" / "YzY-Auto-Buff" / "account.json"

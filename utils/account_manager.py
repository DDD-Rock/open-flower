"""Account authentication shared with the AutoBuff monitor service."""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional


class AccountError(Exception):
    """A user-facing account authentication error."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


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
        client_id = self._load_or_create_client_id()
        response = self._request(
            "/api/auth/login",
            method="POST",
            body={"username": username.strip(), "password": password},
        )
        token = str(response.get("accessToken") or "")
        account = str((response.get("user") or {}).get("username") or "")
        if not token or not account:
            raise AccountError("监控服务器返回了无效数据")
        binding = self._bind_client(token, client_id) or {}
        self._save(token, account, client_id, str(binding.get("name") or ""))
        return account

    def restore(self) -> Optional[str]:
        credentials = self._load()
        if not credentials:
            return None
        token = str(credentials.get("accessToken") or "")
        if not token:
            return None
        client_id = self._client_id_from(credentials)
        try:
            response = self._request("/api/auth/me", token=token)
            self._validate_client(token, client_id)
        except AccountError:
            self.logout()
            return None
        account = str(response.get("username") or "")
        if not account:
            self.logout()
            return None
        self._save(
            token,
            account,
            client_id,
            str(credentials.get("clientName") or ""),
        )
        return account

    def logout(self):
        credentials = self._load() or {}
        client_id = self._client_id_from(credentials)
        self._save("", "", client_id, str(credentials.get("clientName") or ""))

    def validate_session(self):
        credentials = self._load() or {}
        token = str(credentials.get("accessToken") or "")
        client_id = self._client_id_from(credentials, create=False)
        if not token or not client_id:
            raise AccountError("登录已失效，请重新登录", "invalid_token")
        self._validate_client(token, client_id)

    @property
    def registration_url(self) -> str:
        return f"{self.server_base_url}/register"

    def session_credentials(self) -> dict:
        """返回远程监控连接需要的当前会话，不暴露可写内部字典。"""
        credentials = dict(self._load() or {})
        return {
            "accessToken": str(credentials.get("accessToken") or ""),
            "username": str(credentials.get("username") or ""),
            "clientId": self._client_id_from(credentials, create=False),
            "clientName": str(credentials.get("clientName") or ""),
            "serverBaseURL": self.server_base_url,
        }

    def save_client_name(self, name: str):
        credentials = self._load() or {}
        self._save(
            str(credentials.get("accessToken") or ""),
            str(credentials.get("username") or ""),
            self._client_id_from(credentials),
            name.strip(),
        )

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
                payload = response.read()
                return json.loads(payload.decode("utf-8")) if payload else {}
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                message = payload.get("message")
                code = str(payload.get("error") or "")
            except (ValueError, UnicodeDecodeError):
                message = None
                code = ""
            raise AccountError(
                message or f"登录请求失败（{error.code}）",
                code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AccountError("无法连接监控服务器，请检查网络") from error

    def _load(self) -> Optional[dict]:
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None

    def _bind_client(self, token: str, client_id: str):
        return self._request(
            "/api/clients/bind",
            method="POST",
            body={"clientId": client_id},
            token=token,
        )

    def _validate_client(self, token: str, client_id: str):
        self._request(
            f"/api/clients/authorization?client_id={client_id}",
            token=token,
        )

    def _load_or_create_client_id(self) -> str:
        credentials = self._load() or {}
        client_id = self._client_id_from(credentials, create=False)
        if client_id:
            return client_id
        client_id = str(uuid.uuid4())
        self._save(
            str(credentials.get("accessToken") or ""),
            str(credentials.get("username") or ""),
            client_id,
            str(credentials.get("clientName") or ""),
        )
        return client_id

    @staticmethod
    def _client_id_from(credentials: dict, create: bool = True) -> str:
        client_id = str(credentials.get("clientId") or "").strip()
        if client_id:
            return client_id
        return str(uuid.uuid4()) if create else ""

    def _save(self, token: str, username: str, client_id: str, client_name: str = ""):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(
                {
                    "accessToken": token,
                    "username": username,
                    "clientId": client_id,
                    "clientName": client_name,
                },
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

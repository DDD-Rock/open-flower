"""Account authentication shared with the AutoBuff monitor service."""

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

import certifi

from config import APP_VERSION


class AccountError(Exception):
    """A user-facing account authentication error."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class AccountManager:
    DEFAULT_SERVER_BASE_URL = "https://buff.juanwang.cc"
    ALL_CLIENT_MODES = ("dead", "live", "temple", "follow_heal", "monitor")
    DEFAULT_AUTHORIZED_MODES = ("dead", "live", "temple")
    LEGACY_SERVER_BASE_URLS = {
        "http://106.52.208.129:28671",
        "https://106.52.208.129:28671",
        "http://buff.juanwang.cc",
    }

    def __init__(self, storage_path: Optional[str] = None, server_base_url: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else self._default_storage_path()
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        configured_server_base_url = (
            server_base_url
            or os.environ.get("AUTOBUFF_MONITOR_SERVER")
            or self.DEFAULT_SERVER_BASE_URL
        ).rstrip("/")
        self.server_base_url = (
            self.DEFAULT_SERVER_BASE_URL
            if configured_server_base_url in self.LEGACY_SERVER_BASE_URLS
            else configured_server_base_url
        )

    def authenticate(self, username: str, password: str) -> str:
        client_id = self._load_or_create_client_id()
        response = self._request(
            "/api/auth/login",
            method="POST",
            body={"username": username.strip(), "password": password},
        )
        token = str(response.get("accessToken") or "")
        user = response.get("user") or {}
        account = str(user.get("username") or "")
        nickname = str(user.get("nickname") or "未设置昵称")
        if not token or not account:
            raise AccountError("监控服务器返回了无效数据")
        binding = self._bind_client(token, client_id) or {}
        is_super_admin = bool(user.get("isSuperAdmin"))
        authorized_modes = self._authorized_modes_from(
            binding,
            user,
            is_super_admin=is_super_admin,
        )
        self._save(
            token, account, client_id, str(binding.get("name") or ""),
            is_super_admin, nickname,
            str(binding.get("roleName") or ""),
            authorized_modes,
        )
        return nickname

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
            authorization = self._validate_client(token, client_id) or {}
        except AccountError:
            self.logout()
            return None
        account = str(response.get("username") or "")
        nickname = str(response.get("nickname") or "未设置昵称")
        if not account:
            self.logout()
            return None
        is_super_admin = bool(response.get("isSuperAdmin"))
        authorized_modes = self._authorized_modes_from(
            authorization,
            response,
            is_super_admin=is_super_admin,
        )
        self._save(
            token,
            account,
            client_id,
            str(credentials.get("clientName") or ""),
            is_super_admin,
            nickname,
            str(authorization.get("roleName") or credentials.get("roleName") or ""),
            authorized_modes,
        )
        return nickname

    def logout(self):
        credentials = self._load() or {}
        client_id = self._client_id_from(credentials)
        self._save(
            "", "", client_id, str(credentials.get("clientName") or ""),
            False, "", str(credentials.get("roleName") or ""), []
        )

    def validate_session(self):
        credentials = self._load() or {}
        token = str(credentials.get("accessToken") or "")
        client_id = self._client_id_from(credentials, create=False)
        if not token or not client_id:
            raise AccountError("登录已失效，请重新登录", "invalid_token")
        authorization = self._validate_client(token, client_id) or {}
        current = self._load() or {}
        is_super_admin = bool(current.get("isSuperAdmin"))
        authorized_modes = self._authorized_modes_from(
            authorization,
            current,
            is_super_admin=is_super_admin,
        )
        self._save(
            token,
            str(current.get("username") or ""),
            client_id,
            str(current.get("clientName") or ""),
            role_name=str(authorization.get("roleName") or current.get("roleName") or ""),
            authorized_modes=authorized_modes,
        )
        return authorization

    @property
    def registration_url(self) -> str:
        return f"{self.server_base_url}/register"

    def session_credentials(self) -> dict:
        """返回远程监控连接需要的当前会话，不暴露可写内部字典。"""
        credentials = dict(self._load() or {})
        is_super_admin = bool(credentials.get("isSuperAdmin"))
        return {
            "accessToken": str(credentials.get("accessToken") or ""),
            "username": str(credentials.get("username") or ""),
            "nickname": str(credentials.get("nickname") or ""),
            "clientId": self._client_id_from(credentials, create=False),
            "clientName": str(credentials.get("clientName") or ""),
            "roleName": str(credentials.get("roleName") or ""),
            "serverBaseURL": self.server_base_url,
            "isSuperAdmin": is_super_admin,
            "authorizedModes": self._authorized_modes_from(
                credentials,
                is_super_admin=is_super_admin,
            ),
        }

    @classmethod
    def _authorized_modes_from(cls, *sources, is_super_admin: bool = False) -> list[str]:
        if is_super_admin:
            return list(cls.ALL_CLIENT_MODES)
        for source in sources:
            if not isinstance(source, dict) or "authorizedModes" not in source:
                continue
            raw_modes = source.get("authorizedModes")
            if not isinstance(raw_modes, (list, tuple, set)):
                continue
            allowed = set(cls.ALL_CLIENT_MODES)
            return list(dict.fromkeys(
                str(mode) for mode in raw_modes if str(mode) in allowed
            ))
        return list(cls.DEFAULT_AUTHORIZED_MODES)

    def list_cloud_maps(self) -> list[dict]:
        credentials = self.session_credentials()
        return list(self._request(
            "/api/admin/maps", token=credentials["accessToken"]
        ).get("maps") or [])

    def upload_cloud_maps(self, maps) -> int:
        from models.map_topology import MapTransferService
        package = json.loads(MapTransferService.export_data(maps).decode("utf-8"))
        response = self._request(
            "/api/admin/maps", method="POST", body=package,
            token=self.session_credentials()["accessToken"],
        )
        return int(response.get("uploadedCount") or 0)

    def download_cloud_map(self, map_id: int):
        from models.map_topology import MapTransferService
        response = self._request(
            f"/api/admin/maps/{int(map_id)}",
            token=self.session_credentials()["accessToken"],
        )
        return MapTransferService.import_data(json.dumps(response).encode("utf-8"))

    def save_client_name(self, name: str):
        credentials = self._load() or {}
        self._save(
            str(credentials.get("accessToken") or ""),
            str(credentials.get("username") or ""),
            self._client_id_from(credentials),
            name.strip(),
        )

    def save_role_name(self, role_name: str) -> str:
        role_name = role_name.strip()
        credentials = self.session_credentials()
        response = self._request(
            "/api/clients/role-name",
            method="PUT",
            body={"clientId": credentials["clientId"], "roleName": role_name},
            token=credentials["accessToken"],
        )
        saved = str(response.get("roleName") or role_name)
        current = self._load() or {}
        self._save(
            str(current.get("accessToken") or ""),
            str(current.get("username") or ""),
            self._client_id_from(current),
            str(current.get("clientName") or ""),
            role_name=saved,
        )
        return saved

    def _request(self, path: str, method: str = "GET", body=None, token: str = "") -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.server_base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "X-AutoBuff-Client-Platform": "windows",
                "X-AutoBuff-Client-Version": APP_VERSION,
                **({"Content-Type": "application/json"} if data is not None else {}),
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=10,
                context=self.ssl_context,
            ) as response:
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
        except urllib.error.URLError as error:
            raise AccountError(self._connection_error_message(error.reason)) from error
        except (TimeoutError, OSError) as error:
            raise AccountError(self._connection_error_message(error)) from error

    @staticmethod
    def _connection_error_message(error) -> str:
        if isinstance(error, ssl.SSLCertVerificationError):
            prefix = "监控服务器证书验证失败"
        elif isinstance(error, ssl.SSLError):
            prefix = "与监控服务器建立 TLS 连接失败"
        elif isinstance(error, socket.gaierror):
            prefix = "无法解析监控服务器域名"
        elif isinstance(error, (TimeoutError, socket.timeout)):
            return "连接监控服务器超时"
        else:
            prefix = "无法连接监控服务器"

        detail = " ".join(str(error).split())
        return f"{prefix}：{detail[:240]}" if detail else prefix

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
        return self._request(
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

    def _save(
        self, token: str, username: str, client_id: str,
        client_name: str = "", is_super_admin: Optional[bool] = None,
        nickname: Optional[str] = None, role_name: Optional[str] = None,
        authorized_modes: Optional[list[str]] = None,
    ):
        existing = self._load() or {}
        if is_super_admin is None:
            is_super_admin = bool(existing.get("isSuperAdmin"))
        if nickname is None:
            nickname = str(existing.get("nickname") or "")
        if role_name is None:
            role_name = str(existing.get("roleName") or "")
        if authorized_modes is None:
            authorized_modes = list(existing.get("authorizedModes") or [])
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(
                {
                    "accessToken": token,
                    "username": username,
                    "nickname": nickname,
                    "clientId": client_id,
                    "clientName": client_name,
                    "roleName": role_name,
                    "isSuperAdmin": is_super_admin,
                    "authorizedModes": authorized_modes,
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

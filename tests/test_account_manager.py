import importlib.util
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "account_manager",
    ROOT / "utils" / "account_manager.py",
)
ACCOUNT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCOUNT_MODULE)
AccountManager = ACCOUNT_MODULE.AccountManager
AccountError = ACCOUNT_MODULE.AccountError


class StubAccountManager(AccountManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bound_client_ids = []

    def _request(self, path, method="GET", body=None, token=""):
        if path == "/api/auth/login":
            return {
                "accessToken": "account-token",
                "user": {"username": body["username"], "nickname": "爱丽丝", "authorizedModes": ["dead"]},
            }
        if path == "/api/clients/bind":
            self.bound_client_ids.append(body["clientId"])
            return {"id": "session-1", "clientId": body["clientId"], "name": "测试电脑", "authorizedModes": ["dead"]}
        if path.startswith("/api/clients/authorization"):
            return {"authorizedModes": ["dead"]}
        return {"id": 1, "username": "alice", "nickname": "爱丽丝", "authorizedModes": ["dead"]}


class AccountManagerTests(unittest.TestCase):
    def test_mode_authorization_uses_account_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StubAccountManager(
                storage_path=str(Path(temp_dir) / "account.json")
            )

            manager.authenticate("alice", "password")

            self.assertEqual(manager.session_credentials()["authorizedModes"], ["dead"])

    def test_empty_mode_authorization_does_not_fall_back_to_defaults(self):
        class EmptyAuthorizationManager(StubAccountManager):
            def _request(self, path, method="GET", body=None, token=""):
                response = super()._request(path, method, body, token)
                if isinstance(response, dict):
                    response["authorizedModes"] = []
                    if isinstance(response.get("user"), dict):
                        response["user"]["authorizedModes"] = []
                return response

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmptyAuthorizationManager(
                storage_path=str(Path(temp_dir) / "account.json")
            )

            manager.authenticate("alice", "password")

            self.assertEqual(manager.session_credentials()["authorizedModes"], [])

    def test_legacy_account_defaults_to_standard_three_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AccountManager(
                storage_path=str(Path(temp_dir) / "account.json")
            )
            manager._save("token", "alice", "client-id", "测试电脑")

            self.assertEqual(
                manager.session_credentials()["authorizedModes"],
                ["dead", "live", "temple"],
            )

    def test_super_admin_without_cached_modes_receives_all_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AccountManager(
                storage_path=str(Path(temp_dir) / "account.json")
            )
            manager._save(
                "token", "admin", "client-id", "管理电脑",
                is_super_admin=True,
            )

            self.assertEqual(
                manager.session_credentials()["authorizedModes"],
                list(AccountManager.ALL_CLIENT_MODES),
            )

    def test_requests_report_windows_client_version(self):
        manager = AccountManager(server_base_url="http://example.test")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        response.__exit__.return_value = False
        with mock.patch.object(ACCOUNT_MODULE.urllib.request, "urlopen", return_value=response) as urlopen:
            manager._request("/api/auth/me")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-autobuff-client-platform"), "windows")
        self.assertEqual(request.get_header("X-autobuff-client-version"), "2.1.5")
        self.assertIs(urlopen.call_args.kwargs["context"], manager.ssl_context)

    def test_certificate_errors_are_reported_separately(self):
        manager = AccountManager(server_base_url="https://example.test")
        certificate_error = ACCOUNT_MODULE.ssl.SSLCertVerificationError(
            "certificate verify failed"
        )
        with mock.patch.object(
            ACCOUNT_MODULE.urllib.request,
            "urlopen",
            side_effect=ACCOUNT_MODULE.urllib.error.URLError(certificate_error),
        ):
            with self.assertRaisesRegex(AccountError, "证书验证失败"):
                manager._request("/api/auth/me")

    def test_dns_errors_are_reported_separately(self):
        manager = AccountManager(server_base_url="https://example.test")
        dns_error = ACCOUNT_MODULE.socket.gaierror(11001, "getaddrinfo failed")
        with mock.patch.object(
            ACCOUNT_MODULE.urllib.request,
            "urlopen",
            side_effect=ACCOUNT_MODULE.urllib.error.URLError(dns_error),
        ):
            with self.assertRaisesRegex(AccountError, "无法解析监控服务器域名"):
                manager._request("/api/auth/me")

    def test_login_token_is_reused_for_startup_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Path(temp_dir) / "account.json"
            manager = StubAccountManager(
                storage_path=str(storage),
                server_base_url="http://example.test/",
            )

            self.assertEqual(manager.authenticate(" alice ", "password"), "爱丽丝")
            self.assertEqual(manager.restore(), "爱丽丝")
            manager.validate_session()
            self.assertEqual(manager.registration_url, "http://example.test/register")
            self.assertEqual(len(set(manager.bound_client_ids)), 1)
            self.assertEqual(manager.session_credentials()["authorizedModes"], ["dead"])

            manager.logout()
            credentials = manager._load()
            self.assertTrue(storage.exists())
            self.assertEqual(credentials["clientId"], manager.bound_client_ids[0])
            self.assertEqual(credentials["accessToken"], "")

            self.assertEqual(manager.authenticate("alice", "password"), "爱丽丝")
            self.assertEqual(len(set(manager.bound_client_ids)), 1)

    def test_client_limit_failure_does_not_persist_login_token(self):
        class LimitedAccountManager(StubAccountManager):
            def _bind_client(self, token, client_id):
                raise AccountError("客户端数量已达到上限")

        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Path(temp_dir) / "account.json"
            manager = LimitedAccountManager(storage_path=str(storage))

            with self.assertRaisesRegex(AccountError, "达到上限"):
                manager.authenticate("alice", "password")

            credentials = manager._load()
            self.assertTrue(credentials["clientId"])
            self.assertEqual(credentials["accessToken"], "")


if __name__ == "__main__":
    unittest.main()

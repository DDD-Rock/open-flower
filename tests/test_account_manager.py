import importlib.util
import tempfile
import unittest
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
                "user": {"username": body["username"]},
            }
        if path == "/api/clients/bind":
            self.bound_client_ids.append(body["clientId"])
            return {"id": "session-1", "clientId": body["clientId"], "name": "测试电脑"}
        if path.startswith("/api/clients/authorization"):
            return {}
        return {"id": 1, "username": "alice"}


class AccountManagerTests(unittest.TestCase):
    def test_login_token_is_reused_for_startup_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = Path(temp_dir) / "account.json"
            manager = StubAccountManager(
                storage_path=str(storage),
                server_base_url="http://example.test/",
            )

            self.assertEqual(manager.authenticate(" alice ", "password"), "alice")
            self.assertEqual(manager.restore(), "alice")
            manager.validate_session()
            self.assertEqual(manager.registration_url, "http://example.test/register")
            self.assertEqual(len(set(manager.bound_client_ids)), 1)

            manager.logout()
            credentials = manager._load()
            self.assertTrue(storage.exists())
            self.assertEqual(credentials["clientId"], manager.bound_client_ids[0])
            self.assertEqual(credentials["accessToken"], "")

            self.assertEqual(manager.authenticate("alice", "password"), "alice")
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

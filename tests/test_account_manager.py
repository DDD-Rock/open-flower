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


class StubAccountManager(AccountManager):
    def _request(self, path, method="GET", body=None, token=""):
        if path == "/api/auth/login":
            return {
                "accessToken": "account-token",
                "user": {"username": body["username"]},
            }
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
            self.assertEqual(manager.registration_url, "http://example.test/register")

            manager.logout()
            self.assertFalse(storage.exists())


if __name__ == "__main__":
    unittest.main()

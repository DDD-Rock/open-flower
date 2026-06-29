import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "license_manager",
    ROOT / "utils" / "license_manager.py",
)
LICENSE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LICENSE_MODULE)
LicenseManager = LICENSE_MODULE.LicenseManager


class LicenseManagerTests(unittest.TestCase):
    def test_activation_code_uses_same_md5_rule_as_swift_app(self):
        self.assertEqual(
            LicenseManager.expected_activation_code("ABC123"),
            "1B9DD7E03E89921DCFC2B041F38B55E4",
        )

    def test_activation_code_accepts_grouped_machine_code(self):
        self.assertEqual(
            LicenseManager.expected_activation_code("ABC-123"),
            "1B9DD7E03E89921DCFC2B041F38B55E4",
        )

    def test_master_activation_code_is_always_valid(self):
        manager = LicenseManager()
        self.assertTrue(manager.is_valid_activation_code("zhimakaimenyzy"))

    def test_save_and_load_activation_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            license_path = Path(temp_dir) / "license.ini"
            manager = LicenseManager(license_path=str(license_path))
            code = LicenseManager.expected_activation_code(manager.current_machine_code())

            self.assertTrue(manager.save_activation_code(code))

            reloaded = LicenseManager(license_path=str(license_path))
            self.assertTrue(reloaded.is_activated())


if __name__ == "__main__":
    unittest.main()

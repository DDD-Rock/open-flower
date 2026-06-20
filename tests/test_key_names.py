import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "utils" / "key_names.py"
SPEC = importlib.util.spec_from_file_location("key_names", MODULE_PATH)
KEY_NAMES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KEY_NAMES)
normalize_key_name = KEY_NAMES.normalize_key_name


class NormalizeKeyNameTests(unittest.TestCase):
    def test_normalizes_uppercase_ascii_letters(self):
        for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            with self.subTest(key=key):
                self.assertEqual(normalize_key_name(key), key.lower())

    def test_preserves_lowercase_letters_and_number_row_keys(self):
        for key in "abcdefghijklmnopqrstuvwxyz1234567890":
            with self.subTest(key=key):
                self.assertEqual(normalize_key_name(key), key)

    def test_preserves_named_and_symbol_keys(self):
        for key in ("F1", "Space", "PageUp", "=", "-", "[", "]"):
            with self.subTest(key=key):
                self.assertEqual(normalize_key_name(key), key)


if __name__ == "__main__":
    unittest.main()

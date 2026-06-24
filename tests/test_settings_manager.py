import configparser
import importlib.util
import tempfile
import unittest
from pathlib import Path

from models.buff_config import BuffConfig


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "settings_manager",
    ROOT / "utils" / "settings_manager.py",
)
SETTINGS_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETTINGS_MODULE)
SettingsManager = SETTINGS_MODULE.SettingsManager


class SettingsManagerTests(unittest.TestCase):
    def test_legacy_empty_six_slots_collapse_to_three(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            config = configparser.ConfigParser()
            config["General"] = {}
            for index in range(1, 7):
                config[f"Buff{index}"] = {
                    "enabled": "False",
                    "key": "",
                    "duration": "0",
                }
            with path.open("w", encoding="utf-8") as stream:
                config.write(stream)

            settings = SettingsManager(str(path)).load_settings()

            self.assertEqual(len(settings["buffs"]), 3)
            self.assertEqual(settings["pre_skill_move_mode"], "right_only")

    def test_configured_additional_slots_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            config = configparser.ConfigParser()
            config["General"] = {}
            for index in range(1, 6):
                config[f"Buff{index}"] = {
                    "enabled": str(index == 5),
                    "key": "5" if index == 5 else "",
                    "duration": "200" if index == 5 else "0",
                }
            with path.open("w", encoding="utf-8") as stream:
                config.write(stream)

            settings = SettingsManager(str(path)).load_settings()

            self.assertEqual(len(settings["buffs"]), 5)
            self.assertTrue(settings["buffs"][4]["enabled"])

    def test_round_trip_preserves_portal_and_dynamic_buffs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            manager = SettingsManager(str(path))
            buffs = [
                BuffConfig(True, "1", 200),
                BuffConfig(True, "2", 200),
                BuffConfig(),
                BuffConfig(True, "4", 180),
            ]

            self.assertTrue(
                manager.save_settings(
                    buffs=buffs,
                    return_to_market=True,
                    pre_skill_move_mode="right_only",
                    manual_portal_pos=(37, 18),
                )
            )
            settings = SettingsManager(str(path)).load_settings()

            self.assertEqual(len(settings["buffs"]), 4)
            self.assertEqual(settings["manual_portal_pos"], (37, 18))
            self.assertEqual(settings["pre_skill_move_mode"], "right_only")


if __name__ == "__main__":
    unittest.main()

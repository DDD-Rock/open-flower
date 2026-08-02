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
    def test_monitor_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.ini"
            manager = SettingsManager(str(path))
            zone = {
                "center": {"x": 0.4, "y": 0.6},
                "width": 0.25,
                "height": 0.35,
            }

            manager.save_settings(
                buffs=[],
                mode="monitor",
                monitor_display_mode="annotations_only",
                monitor_safe_zone=zone,
            )
            settings = manager.load_settings()

            self.assertEqual(settings["mode"], "monitor")
            self.assertEqual(settings["monitor_display_mode"], "annotations_only")
            self.assertEqual(settings["monitor_safe_zone"], zone)

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

    def test_legacy_return_to_market_migrates_to_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            config = configparser.ConfigParser()
            config["General"] = {"return_to_market": "False"}
            config["Buff1"] = {"enabled": "True", "key": "1", "duration": "200"}
            with path.open("w", encoding="utf-8") as stream:
                config.write(stream)

            settings = SettingsManager(str(path)).load_settings()

            self.assertEqual(settings["mode"], "live")
            self.assertFalse(settings["return_to_market"])

    def test_follow_heal_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            manager = SettingsManager(str(path))
            buffs = [
                BuffConfig(True, "1", 200),
                BuffConfig(True, "2", 260),
                BuffConfig(),
            ]

            self.assertTrue(
                manager.save_settings(
                    buffs=buffs,
                    mode="follow_heal",
                    heal_skill_key="Q",
                    follow_heal_anchor_pos=(74, 58),
                    follow_heal_minimap_region=(6, 122, 164, 86),
                    follow_heal_adjust_hold_ms=(220, 330),
                )
            )
            settings = SettingsManager(str(path)).load_settings()

            self.assertEqual(settings["mode"], "follow_heal")
            self.assertFalse(settings["return_to_market"])
            self.assertEqual(settings["heal_skill_key"], "Q")
            self.assertEqual(settings["follow_heal_anchor_pos"], (74, 58))
            self.assertEqual(settings["follow_heal_minimap_region"], (6, 122, 164, 86))
            self.assertEqual(settings["follow_heal_adjust_hold_ms"], (220, 330))

    def test_auto_accept_party_invite_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            manager = SettingsManager(str(path))

            self.assertTrue(
                manager.save_settings(
                    buffs=[BuffConfig(True, "1", 200), BuffConfig(), BuffConfig()],
                    auto_accept_party_invite=True,
                )
            )
            settings = manager.load_settings()

            self.assertTrue(settings["auto_accept_party_invite"])

    def test_rope_party_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            manager = SettingsManager(str(path))
            self.assertTrue(manager.save_settings(
                buffs=[BuffConfig(), BuffConfig(), BuffConfig()],
                mode="temple",
                temple_function="rope_party",
                character_name="测试队长",
                rope_party_team_id=12,
                rope_party_is_leader=True,
                rope_party_invite_role_names=["队员甲", "队员乙"],
            ))
            settings = manager.load_settings()
            self.assertEqual(settings["mode"], "temple")
            self.assertEqual(settings["character_name"], "测试队长")
            self.assertEqual(settings["rope_party_team_id"], 12)
            self.assertTrue(settings["rope_party_is_leader"])
            self.assertEqual(settings["rope_party_invite_role_names"], ["队员甲", "队员乙"])


if __name__ == "__main__":
    unittest.main()

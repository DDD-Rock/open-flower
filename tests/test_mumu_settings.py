import json
import tempfile
import unittest
from pathlib import Path

from utils.mumu_settings import MumuSettingsStore


class MumuSettingsStoreTests(unittest.TestCase):
    def test_load_forces_each_emulator_to_stopped_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mumu_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "devices": {
                            "127.0.0.1:16384": {
                                "enabled": True,
                                "anchor": [48, 55],
                                "half_height": 10,
                                "sit_chair_enabled": True,
                                "chair_key": "=",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = MumuSettingsStore(str(path)).load()

            config = loaded["127.0.0.1:16384"]
            self.assertFalse(config["enabled"])
            self.assertEqual(config["anchor"], [48, 55])
            self.assertNotIn("half_height", config)
            self.assertNotIn("sit_chair_enabled", config)
            self.assertNotIn("chair_key", config)

    def test_save_never_persists_running_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mumu_settings.json"
            store = MumuSettingsStore(str(path))

            self.assertTrue(
                store.save(
                    {
                        "127.0.0.1:16384": {
                            "enabled": True,
                            "anchor": [48, 55],
                            "buffs": [{"enabled": True, "key": "1", "duration": 270}],
                        }
                    }
                )
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            config = payload["devices"]["127.0.0.1:16384"]
            self.assertFalse(config["enabled"])
            self.assertEqual(config["anchor"], [48, 55])
            self.assertEqual(config["buffs"][0]["key"], "1")


if __name__ == "__main__":
    unittest.main()

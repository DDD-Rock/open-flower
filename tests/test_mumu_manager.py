import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.mumu_manager import (
    MumuManagerError,
    _run_cli,
    launch_mumu_instance,
    list_mumu_instances,
)


class MumuManagerTests(unittest.TestCase):
    def _make_cli(self, directory: str) -> Path:
        root = Path(directory) / "MuMuPlayer"
        cli = root / "nx_main" / "mumu-cli.exe"
        cli.parent.mkdir(parents=True)
        cli.touch()
        config_dir = (
            root
            / "vms"
            / "MuMuPlayerGlobal-15.0-3"
            / "configs"
        )
        config_dir.mkdir(parents=True)
        (config_dir / "vm_config.json").write_text(
            json.dumps(
                {
                    "vm": {
                        "nat": {
                            "port_forward": {"adb": {"host_port": "16480"}}
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return cli

    @patch("utils.mumu_manager._run_cli")
    def test_lists_powered_off_instances_and_resolves_adb_port(self, run_cli):
        run_cli.return_value = json.dumps(
            {
                "3": {
                    "index": "3",
                    "name": "角色三",
                    "android_version": "15.0",
                    "is_process_started": False,
                    "is_android_started": False,
                    "error_code": 0,
                }
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            cli = self._make_cli(directory)
            instances = list_mumu_instances(str(cli))

        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]["vm_index"], "3")
        self.assertEqual(instances[0]["name"], "角色三")
        self.assertEqual(instances[0]["adb_serial"], "")
        self.assertFalse(instances[0]["is_process_started"])
        run_cli.assert_called_once_with(
            str(cli), "info", "--vmindex", "all", timeout=3
        )

    @patch("utils.mumu_manager._run_cli")
    def test_launches_only_selected_instance(self, run_cli):
        run_cli.return_value = "{}"
        launch_mumu_instance("7", "mumu-cli.exe")
        run_cli.assert_called_once_with(
            "mumu-cli.exe",
            "control",
            "--vmindex",
            "7",
            "launch",
            timeout=20,
        )

    @patch("utils.mumu_manager._run_cli")
    def test_uses_manager_assigned_adb_port_only_for_started_instance(self, run_cli):
        run_cli.return_value = json.dumps(
            {
                "1": {
                    "index": "1",
                    "name": "在线实例",
                    "android_version": "15.0",
                    "is_process_started": True,
                    "is_android_started": True,
                    "adb_host_ip": "127.0.0.1",
                    "adb_port": 16416,
                },
                "7": {
                    "index": "7",
                    "name": "离线实例",
                    "android_version": "15.0",
                    "is_process_started": False,
                    "is_android_started": False,
                },
            }
        )
        instances = list_mumu_instances("mumu-cli.exe")
        self.assertEqual(instances[0]["adb_serial"], "127.0.0.1:16416")
        self.assertEqual(instances[1]["adb_serial"], "")

    def test_rejects_invalid_instance_index(self):
        with self.assertRaises(MumuManagerError):
            launch_mumu_instance("all", "mumu-cli.exe")

    @patch("utils.mumu_manager._run_cli")
    def test_falls_back_to_instance_configs_when_cli_times_out(self, run_cli):
        run_cli.side_effect = MumuManagerError("timed out")
        with tempfile.TemporaryDirectory() as directory:
            cli = self._make_cli(directory)
            extra = (
                cli.parent.parent
                / "vms"
                / "MuMuPlayerGlobal-15.0-3"
                / "configs"
                / "extra_config.json"
            )
            extra.write_text(
                json.dumps({"playerName": "离线实例"}, ensure_ascii=False),
                encoding="utf-8",
            )
            instances = list_mumu_instances(str(cli))

        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]["name"], "离线实例")
        self.assertEqual(instances[0]["adb_serial"], "")

    @patch("utils.mumu_manager.subprocess.run")
    def test_decodes_gb18030_cli_output(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout="急速鸡".encode("gb18030"), stderr=b""
        )
        self.assertEqual(_run_cli("mumu-cli.exe", "version"), "急速鸡")


if __name__ == "__main__":
    unittest.main()

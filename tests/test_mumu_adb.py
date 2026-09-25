import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from utils.mumu_adb import (
    capture_adb_frame,
    connect_adb_device,
    list_adb_devices,
    resolve_adb_path,
)
from utils.mumu_scrcpy_stream import resolve_scrcpy_server_path


class MumuAdbTests(unittest.TestCase):
    def test_resolves_bundled_adb_and_server(self):
        with tempfile.TemporaryDirectory() as directory:
            adb = Path(directory) / "adb.exe"
            server = Path(directory) / "scrcpy-server"
            adb.touch()
            server.touch()
            with patch("utils.mumu_adb.sys._MEIPASS", directory, create=True):
                self.assertEqual(resolve_adb_path(), str(adb))
            with patch(
                "utils.mumu_scrcpy_stream.sys._MEIPASS", directory, create=True
            ):
                self.assertEqual(resolve_scrcpy_server_path(), str(server))

    @patch("utils.mumu_adb.subprocess.run")
    def test_lists_emulator_devices(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(
                [],
                0,
                stdout=(
                    "List of devices attached\n"
                    "emulator-5554 device product:test model:SM_G9980 transport_id:1\n"
                    "ABC123 device product:phone model:Pixel_8 transport_id:2\n"
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                [], 0, stdout="boot-id-1\n", stderr=""
            ),
        ]

        devices = list_adb_devices("adb.exe")

        self.assertEqual([device["serial"] for device in devices], ["emulator-5554"])
        self.assertEqual(devices[0]["model"], "SM G9980")
        self.assertEqual(devices[0]["boot_id"], "boot-id-1")

    @patch("utils.mumu_adb.subprocess.run")
    def test_decodes_screenshot_without_mutating_png_bytes(self, run):
        source = np.zeros((24, 32, 3), dtype=np.uint8)
        source[:, :, 1] = 180
        encoded, png = cv2.imencode(".png", source)
        self.assertTrue(encoded)
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=png.tobytes(), stderr=b""
        )

        frame, error = capture_adb_frame("emulator-5554", "adb.exe")

        self.assertEqual(error, "")
        self.assertEqual(frame.shape, (24, 32, 3))

    @patch("utils.mumu_adb.subprocess.run")
    def test_connects_local_mumu_adb_endpoint(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout="connected to 127.0.0.1:16384\n", stderr=""
        )

        success, message = connect_adb_device(
            "127.0.0.1:16384", "adb.exe"
        )

        self.assertTrue(success)
        self.assertIn("connected", message)
        run.assert_called_once()

    def test_refuses_non_local_adb_endpoint(self):
        success, message = connect_adb_device("192.168.1.5:5555", "adb.exe")
        self.assertFalse(success)
        self.assertIn("本机", message)


if __name__ == "__main__":
    unittest.main()

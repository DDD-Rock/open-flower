import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication

from detection.emulator_frame_analysis import (
    EmulatorFrameAnalysis,
    analyze_emulator_frame,
    apply_game_state_grace,
    detect_emulator_map_title_region,
    detect_emulator_minimap_region,
    ULU_MANOR_2_MINIMAP,
    ULU_MANOR_2_STREAM_MINIMAP,
)
from ui.emulator_panel import EmulatorRow


class EmulatorFrameAnalysisTests(unittest.TestCase):
    def test_ulu_manor_2_title_uses_fixed_canvas(self):
        image = np.full((1080, 1920, 3), 35, dtype=np.uint8)
        cv2.line(image, (12, 200), (260, 200), (225, 225, 225), 3)
        cv2.circle(image, (150, 180), 3, (0, 255, 255), -1)
        response = {"code": 100, "data": [
            {"text": "扁魯莊围 II", "score": 0.68},
        ]}
        with patch("detection.emulator_frame_analysis.EXPRapidOCRRecognizer") as ocr:
            ocr.return_value._run_engine.return_value = response
            with patch("detection.emulator_frame_analysis.detect_minimap_content_region",
                       return_value=(6, 129, 271, 329)):
                analysis = analyze_emulator_frame(image)
        self.assertEqual(analysis.minimap_rect, ULU_MANOR_2_MINIMAP)
        self.assertEqual(analysis.player_position, (144, 51))
        self.assertEqual(ocr.return_value._run_engine.call_args.args[0].shape, (45, 194, 3))

    def test_ulu_manor_2_stream_uses_half_resolution_canvas(self):
        image = np.full((540, 960, 3), 35, dtype=np.uint8)
        cv2.line(image, (8, 98), (130, 98), (225, 225, 225), 2)
        cv2.circle(image, (76, 90), 3, (0, 255, 255), -1)
        with patch("detection.emulator_frame_analysis.EXPRapidOCRRecognizer") as ocr:
            ocr.return_value._run_engine.return_value = {
                "code": 100, "data": [{"text": "扁魯莊圆 II", "score": 0.62}],
            }
            analysis = analyze_emulator_frame(image)
        self.assertEqual(analysis.minimap_rect, ULU_MANOR_2_STREAM_MINIMAP)
        self.assertEqual(analysis.player_position, (73, 25))
        self.assertEqual(ocr.return_value._run_engine.call_args.args[0].shape, (26, 100, 3))

    def test_other_title_falls_back_to_existing_detector(self):
        image = np.full((1080, 1920, 3), 35, dtype=np.uint8)
        generic = (6, 129, 271, 329)
        with patch("detection.emulator_frame_analysis.EXPRapidOCRRecognizer") as ocr:
            ocr.return_value._run_engine.return_value = {
                "code": 100, "data": [{"text": "其他地图 II", "score": 0.95}],
            }
            with patch("detection.emulator_frame_analysis.detect_minimap_content_region",
                       return_value=generic):
                self.assertEqual(detect_emulator_minimap_region(image), generic)

    def test_ulu_title_without_map_canvas_falls_back(self):
        image = np.full((1080, 1920, 3), 255, dtype=np.uint8)
        with patch("detection.emulator_frame_analysis.EXPRapidOCRRecognizer") as ocr:
            ocr.return_value._run_engine.return_value = {
                "code": 100, "data": [{"text": "魯莊 II", "score": 0.9}],
            }
            with patch("detection.emulator_frame_analysis.detect_minimap_content_region",
                       return_value=None), patch(
                           "detection.emulator_frame_analysis._detect_flexible_minimap_region",
                           return_value=None):
                self.assertIsNone(detect_emulator_minimap_region(image))

    @staticmethod
    def _framed_minimap(panel_width: int, panel_height: int):
        image = np.full((720, 1280, 3), 80, dtype=np.uint8)
        left, top = 8, 10
        right = left + panel_width - 1
        bottom = top + panel_height - 1
        cv2.rectangle(image, (left, top), (right, bottom), (225, 225, 225), 4)
        divider_y = top + 45
        cv2.rectangle(
            image,
            (left, divider_y),
            (right, divider_y + 4),
            (225, 225, 225),
            -1,
        )
        cv2.rectangle(
            image,
            (left + 6, divider_y + 5),
            (right - 6, bottom - 6),
            (28, 28, 28),
            -1,
        )
        cv2.circle(image, (left + 70, divider_y + 35), 4, (0, 255, 255), -1)
        return image

    def test_detects_unusually_wide_emulator_minimap(self):
        image = self._framed_minimap(610, 180)
        rect = detect_emulator_minimap_region(image)
        self.assertIsNotNone(rect)
        self.assertGreater(rect[2], 570)
        self.assertGreater(rect[3], 100)

    def test_detects_unusually_tall_emulator_minimap(self):
        image = self._framed_minimap(180, 610)
        rect = detect_emulator_minimap_region(image)
        self.assertIsNotNone(rect)
        self.assertGreater(rect[3], 500)
        self.assertGreater(rect[2], 150)

    def test_analysis_returns_player_coordinate_relative_to_crop(self):
        analysis = analyze_emulator_frame(self._framed_minimap(610, 180))
        self.assertEqual(analysis.game_state, "in_game")
        self.assertIsNotNone(analysis.minimap_image)
        self.assertIsNotNone(analysis.player_position)
        self.assertIsNotNone(analysis.minimap_rect)
        x, y = analysis.player_position
        crop_x, crop_y, _, _ = analysis.minimap_rect
        self.assertAlmostEqual(x, 78 - crop_x, delta=3)
        self.assertAlmostEqual(y, 90 - crop_y, delta=3)

    def test_pure_yellow_core_wins_over_dull_yellow_decoration(self):
        image = self._framed_minimap(360, 220)
        # Remove the normal marker, add one compressed marker core, then add a
        # larger dull-yellow decoration that passes the tolerant HSV shape.
        cv2.circle(image, (78, 90), 7, (28, 28, 28), -1)
        image[90, 98] = (0, 215, 215)
        cv2.rectangle(image, (150, 80), (153, 83), (40, 180, 180), -1)

        analysis = analyze_emulator_frame(image)

        crop_x, crop_y, _, _ = analysis.minimap_rect
        self.assertEqual(analysis.player_position, (98 - crop_x, 90 - crop_y))
        self.assertIn("核心", analysis.player_summary)

    def test_scaled_960_frame_keeps_anti_aliased_player_marker(self):
        image = cv2.resize(
            self._framed_minimap(610, 180),
            (960, 540),
            interpolation=cv2.INTER_AREA,
        )

        analysis = analyze_emulator_frame(image)

        self.assertIsNotNone(analysis.minimap_rect)
        self.assertIsNotNone(analysis.player_position)

    def test_hidden_map_title_strip_counts_as_game_evidence(self):
        image = np.full((720, 1280, 3), (245, 235, 225), dtype=np.uint8)
        cv2.rectangle(image, (4, 3), (290, 45), (95, 95, 95), 3)
        cv2.rectangle(image, (8, 7), (286, 41), (190, 190, 190), -1)
        cv2.putText(
            image,
            "Hidden map",
            (15, 31),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (25, 25, 25),
            2,
        )
        # Reproduce the nearby chat edge which used to complete a false
        # minimap frame around the bright background.
        cv2.rectangle(image, (300, 25), (690, 180), (230, 190, 210), -1)
        cv2.line(image, (300, 180), (690, 180), (25, 25, 25), 5)
        rect = detect_emulator_map_title_region(image)
        analysis = analyze_emulator_frame(image)
        self.assertIsNotNone(rect)
        self.assertEqual(analysis.game_state, "in_game")
        self.assertIsNone(analysis.minimap_image)
        self.assertIsNotNone(analysis.title_rect)

    def test_game_state_uses_five_and_thirty_second_grace_windows(self):
        missing = EmulatorFrameAnalysis(game_state="not_in_game")
        retained, _ = apply_game_state_grace(missing, 100.0, 104.9)
        loading, _ = apply_game_state_grace(missing, 100.0, 105.1)
        gone, _ = apply_game_state_grace(missing, 100.0, 130.1)
        self.assertEqual(retained.game_state, "in_game")
        self.assertEqual(loading.game_state, "loading")
        self.assertEqual(gone.game_state, "not_in_game")


class EmulatorRowActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_connected_row_always_exposes_settings(self):
        row = EmulatorRow()
        row.set_controls_enabled(True)
        row.update_metadata(
            1,
            {
                "vm_index": "0",
                "name": "角色一",
                "serial": "127.0.0.1:16384",
                "state": "device",
            },
        )
        self.assertFalse(row.start_button.isHidden())
        self.assertEqual(row.start_button.text(), "设置")

        emitted = []
        row.settings_requested.connect(emitted.append)
        row.start_button.click()
        self.assertEqual(emitted[0]["serial"], "127.0.0.1:16384")


if __name__ == "__main__":
    unittest.main()

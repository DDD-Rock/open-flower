import json
import unittest
from pathlib import Path

from detection.exp_recognizer import (
    EXPFixedFontRecognizer,
    EXPRapidOCRRecognizer,
    EXPRecognitionResult,
    EXPRecognitionStabilizer,
    format_percent,
)
try:
    import cv2
    import numpy as np

    from detection.minimap_monitor import MinimapMonitor
    from detection.rune_alert_detector import RuneAlertDetector, RuneAlertStabilizer
    from models.map_topology import MinimapVisualMatcher
except ImportError:
    cv2 = None
    np = None
    MinimapMonitor = None
    RuneAlertDetector = None
    RuneAlertStabilizer = None
    MinimapVisualMatcher = None

from models.map_topology import (
    MapPlatform,
    MapPortal,
    MapRope,
    MapTopology,
    MapTopologyValidator,
    MapTransferService,
    NormalizedMapPoint,
    PlatformTraceBuilder,
    RopeTraceBuilder,
)
from models.monitor_state import MonitorSafeZone, SafeZoneStabilizer


class MapTopologyTests(unittest.TestCase):
    def test_mac_compatible_map_round_trip(self):
        topology = MapTopology(
            map_name="测试地图",
            reference_width=240,
            reference_height=120,
            visual_signature=[12] * (24 * 16),
            reference_bgr=b"\x00\x01\x02",
            platforms=[
                MapPlatform(
                    points=[NormalizedMapPoint(0.1, 0.4), NormalizedMapPoint(0.8, 0.4)]
                )
            ],
            ropes=[MapRope(0.5, 0.2, 0.7)],
            portals=[MapPortal(NormalizedMapPoint(0.9, 0.4), "mapExit")],
        )

        encoded = MapTransferService.export_data([topology])
        root = json.loads(encoded)
        self.assertEqual(root["maps"][0]["referenceBGR"], "AAEC")
        decoded = MapTransferService.import_data(encoded)

        self.assertEqual(decoded[0].map_name, topology.map_name)
        self.assertEqual(decoded[0].platforms[0].points, topology.platforms[0].points)
        self.assertEqual(decoded[0].reference_bgr, topology.reference_bgr)

    @unittest.skipIf(cv2 is None, "OpenCV is not installed")
    def test_visual_signature_ignores_saturated_marker(self):
        first = np.full((160, 240, 3), 20, dtype=np.uint8)
        second = first.copy()
        cv2.line(first, (10, 80), (230, 80), (90, 90, 90), 2)
        cv2.line(second, (10, 80), (230, 80), (90, 90, 90), 2)
        cv2.circle(second, (100, 75), 3, (0, 255, 255), -1)

        comparison = MinimapVisualMatcher.comparison(
            MinimapVisualMatcher.signature(first),
            MinimapVisualMatcher.signature(second),
        )

        self.assertTrue(comparison["isMatch"])

    def test_platform_trace_merges_return_trip_and_preserves_slope(self):
        samples = []
        for x in range(10, 91, 2):
            samples.extend(((x, 30 + x * 0.08), (x, 31 + x * 0.08)))
        samples.extend(reversed(samples))
        points = PlatformTraceBuilder.build_polyline(samples, (100, 80))
        self.assertGreaterEqual(len(points), 2)
        self.assertLess(points[0].x, 0.2)
        self.assertGreater(points[-1].x, 0.8)
        self.assertGreater(points[-1].y, points[0].y)

    def test_platform_trace_bridges_a_short_detection_gap(self):
        samples = [(x, 42) for x in range(8, 51, 2)]
        samples += [(x, 42.5) for x in range(62, 113, 2)]

        points = PlatformTraceBuilder.build_polyline(samples, (120, 90))

        self.assertLess(points[0].x, 0.1)
        self.assertGreater(points[-1].x, 0.9)

    def test_rope_trace_discards_outliers_and_builds_vertical_range(self):
        samples = [
            (50 + index % 3, y)
            for y in range(10, 71, 2)
            for index in range(2)
        ]
        samples.extend(((2, 1), (98, 78)))
        rope = RopeTraceBuilder.build_rope(samples, (100, 80))
        self.assertIsNotNone(rope)
        self.assertAlmostEqual(rope.x, 0.51, delta=0.02)
        self.assertLess(rope.top_y, 0.2)
        self.assertGreater(rope.bottom_y, 0.8)

    def test_validator_reports_unreachable_portal(self):
        topology = MapTopology(
            "校验地图",
            100,
            80,
            platforms=[
                MapPlatform(
                    [NormalizedMapPoint(0.1, 0.7), NormalizedMapPoint(0.9, 0.7)]
                )
            ],
            portals=[MapPortal(NormalizedMapPoint(0.5, 0.1))],
        )
        messages = MapTopologyValidator.messages(topology)
        self.assertTrue(any("传送点 T1" in item for item in messages))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class MarkerDetectionTests(unittest.TestCase):
    def test_detects_multiple_teammates_and_other_players(self):
        image = np.full((120, 240, 3), 25, dtype=np.uint8)
        for point in ((30, 40), (90, 70)):
            cv2.circle(image, point, 3, (10, 125, 235), -1)
        for point in ((150, 30), (200, 90)):
            cv2.circle(image, point, 3, (15, 20, 235), -1)
        cv2.rectangle(image, (10, 100), (180, 102), (15, 20, 235), -1)

        self.assertEqual(
            MinimapMonitor.find_teammate_positions_in_image(image),
            [(30, 40), (90, 70)],
        )
        self.assertEqual(
            MinimapMonitor.find_other_player_positions_in_image(image),
            [(150, 30), (200, 90)],
        )


class AlertStateTests(unittest.TestCase):
    @unittest.skipIf(cv2 is None, "OpenCV is not installed")
    def test_rune_detector_and_stabilizer(self):
        image = np.full((300, 500, 3), (45, 25, 70), dtype=np.uint8)
        image[100:104, 100:400] = (180, 55, 130)
        image[145:149, 100:400] = (180, 55, 130)
        image[104:145, 100:400] = (90, 35, 65)

        detection = RuneAlertDetector.detect(image)

        self.assertIsNotNone(detection)
        stabilizer = RuneAlertStabilizer()
        self.assertFalse(stabilizer.update(detection))
        self.assertTrue(stabilizer.update(detection))
        self.assertTrue(stabilizer.is_present)
        self.assertFalse(stabilizer.update(None))
        self.assertTrue(stabilizer.update(None))
        self.assertFalse(stabilizer.is_present)

    def test_safe_zone_uses_duration_and_lost_marker_grace(self):
        zone = MonitorSafeZone(NormalizedMapPoint(0.5, 0.5), 0.2, 0.4)
        self.assertTrue(zone.contains((50, 50), (100, 100)))
        self.assertFalse(zone.contains((90, 50), (100, 100)))

        state = SafeZoneStabilizer()
        self.assertEqual(state.update(True, now=0), "none")
        self.assertEqual(state.update(True, now=1.4), "none")
        self.assertEqual(state.update(True, now=1.5), "breached")
        self.assertEqual(state.update(None, now=10), "none")
        self.assertEqual(state.update(None, now=20), "lost_track")

    def test_exp_stabilizer(self):
        reading = EXPRecognitionResult(123456, 12.3400, 0.91)
        state = EXPRecognitionStabilizer()

        self.assertEqual(format_percent(reading.percent), "12.34")
        self.assertIsNone(state.update(reading))
        self.assertEqual(state.update(reading), reading)
        for _ in range(3):
            self.assertEqual(state.update(None), reading)
        self.assertIsNone(state.update(None))

    def test_rapidocr_exp_parser_accepts_supported_row_formats(self):
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("EXP 7,192,723[12.09%]"),
            (7_192_723, 12.09),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("7192723 (12,09%)"),
            (7_192_723, 12.09),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("EXP35801709160.72%1"),
            (358_017_091, 60.72),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("XP223944737[37.98%]"),
            (223_944_737, 37.98),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("223944737[37.98%"),
            (223_944_737, 37.98),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("EXP18248207[55.19%"),
            (18_248_207, 55.19),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("EXP 0 (0.0%)"),
            (0, 0.0),
        )
        self.assertEqual(
            EXPRapidOCRRecognizer.parse_text("EXP 123 (12.09%)"),
            (123, 12.09),
        )

    def test_rapidocr_exp_parser_rejects_incomplete_or_invalid_rows(self):
        self.assertIsNone(EXPRapidOCRRecognizer.parse_text("EXP 7192723"))
        self.assertIsNone(EXPRapidOCRRecognizer.parse_text("7192723[120.09%]"))
        self.assertIsNone(EXPRapidOCRRecognizer.parse_text("123"))

    def test_rapidocr_payload_uses_confidence_from_matching_block(self):
        parsed = EXPRapidOCRRecognizer.parse_payload(
            {
                "code": 100,
                "data": [
                    {"text": "unrelated", "score": 0.99},
                    {"text": "EXP7192723[12.09%]", "score": 0.94},
                ],
            }
        )
        self.assertEqual(parsed, (7_192_723, 12.09, 0.94))

    def test_rapidocr_runtime_resources_are_present(self):
        root = Path(__file__).resolve().parents[1] / "resources" / "rapidocr"
        expected = (
            "RapidOCR-json.exe",
            "models/ch_PP-OCRv4_det_infer.onnx",
            "models/ch_ppocr_mobile_v2.0_cls_infer.onnx",
            "models/rec_ch_PP-OCRv4_infer.onnx",
            "models/ppocr_keys_v1.txt",
            "LICENSE-RapidOCR-json.txt",
            "LICENSE-PaddleOCR.txt",
            "THIRD_PARTY_NOTICES.md",
        )
        self.assertTrue(all((root / relative).is_file() for relative in expected))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class EXPPanelLocatorTests(unittest.TestCase):
    class TrackingLocator(EXPFixedFontRecognizer):
        def __init__(self):
            super().__init__()
            self.full_searches = 0

        def _find_anchor(self, image, template):
            self.full_searches += 1
            return super()._find_anchor(image, template)

    def setUp(self):
        self.locator = self.TrackingLocator()
        self.templates = self.locator._load_templates()

    def test_cached_anchor_is_reused_until_window_size_changes(self):
        first = self._frame(900, 500, anchor_x=358, anchor_y=443, bracket_x=500)
        self.assertIsNotNone(self.locator.locate_panel(first))
        self.assertEqual(self.locator.full_searches, 1)

        self.assertIsNotNone(self.locator.locate_panel(first.copy()))
        self.assertEqual(self.locator.full_searches, 1)

        resized = self._frame(1000, 600, anchor_x=410, anchor_y=543, bracket_x=565)
        self.assertIsNotNone(self.locator.locate_panel(resized))
        self.assertEqual(self.locator.full_searches, 2)

    def test_line_end_expands_crop_beyond_canonical_width(self):
        anchor_x = 358
        bracket_x = anchor_x + 210
        frame = self._frame(
            900,
            500,
            anchor_x=anchor_x,
            anchor_y=443,
            bracket_x=bracket_x,
        )

        panel, _, _ = self.locator.locate_panel(frame)

        self.assertGreater(panel.shape[1], self.locator.CANONICAL_PANEL_WIDTH)
        self.assertGreaterEqual(panel.shape[1], bracket_x + 3 + 8 - (anchor_x - 8))

    def test_missing_line_end_uses_conservative_maximum_width(self):
        frame = np.full((500, 900, 3), 18, dtype=np.uint8)
        self._paste(frame, self.templates["anchor"], 358, 443)

        panel, _, _ = self.locator.locate_panel(frame)

        self.assertGreaterEqual(
            panel.shape[1],
            self.locator.MAXIMUM_PANEL_SEARCH_WIDTH,
        )

    def _frame(self, width, height, anchor_x, anchor_y, bracket_x):
        frame = np.full((height, width, 3), 18, dtype=np.uint8)
        self._paste(frame, self.templates["anchor"], anchor_x, anchor_y)
        self._paste(frame, self.templates["percent"], bracket_x - 16, anchor_y)
        self._paste(frame, self.templates["right_parenthesis"], bracket_x, anchor_y)
        return frame

    @staticmethod
    def _paste(frame, template, x, y):
        region = frame[y:y + template.shape[0], x:x + template.shape[1]]
        region[:] = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)


if __name__ == "__main__":
    unittest.main()

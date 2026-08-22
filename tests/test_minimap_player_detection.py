import sys
import types
import unittest
from unittest import mock

try:
    import cv2
    import numpy as np

    # Color detection is platform-independent; these modules are only used by
    # the live Windows capture methods.
    sys.modules.setdefault("win32gui", types.SimpleNamespace())
    sys.modules.setdefault("mss", types.SimpleNamespace())
    from detection.minimap_monitor import MinimapMonitor
except ImportError:
    cv2 = None
    np = None
    MinimapMonitor = None


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class MinimapPlayerDetectionTests(unittest.TestCase):
    def test_single_frame_detection_captures_only_once(self):
        minimap = np.full((120, 260, 3), 30, dtype=np.uint8)
        cv2.circle(minimap, (83, 61), 3, (8, 252, 255), -1)
        monitor = MinimapMonitor()
        monitor.capture_minimap = mock.Mock(return_value=minimap)

        point = monitor.find_player_position_once()

        self.assertEqual(point, (83, 61))
        monitor.capture_minimap.assert_called_once_with()

    def test_finds_antialiased_dim_yellow_player_marker(self):
        minimap = np.full((120, 260, 3), 30, dtype=np.uint8)
        cv2.circle(minimap, (83, 61), 3, (38, 208, 218), -1)
        cv2.circle(minimap, (83, 61), 1, (12, 246, 250), -1)

        point, summary = MinimapMonitor.find_player_position_in_image(minimap)

        self.assertEqual(point, (83, 61))
        self.assertIn("玩家黄点", summary)

    def test_finds_small_scaled_marker(self):
        minimap = np.full((120, 260, 3), 30, dtype=np.uint8)
        minimap[42:44, 117:120] = (25, 210, 220)

        point, _ = MinimapMonitor.find_player_position_in_image(minimap)

        self.assertEqual(point, (118, 42))

    def test_rejects_large_yellow_map_decoration(self):
        minimap = np.full((120, 260, 3), 30, dtype=np.uint8)
        cv2.rectangle(minimap, (20, 40), (180, 44), (20, 220, 230), -1)

        point, summary = MinimapMonitor.find_player_position_in_image(minimap)

        self.assertIsNone(point)
        self.assertIn("有效候选=0", summary)

    def test_pure_yellow_marker_wins_over_dim_market_decorations(self):
        minimap = np.full((180, 280, 3), 30, dtype=np.uint8)
        for x, y in ((40, 30), (180, 55), (235, 110)):
            cv2.rectangle(
                minimap,
                (x, y),
                (x + 5, y + 5),
                (25, 205, 225),
                -1,
            )
        cv2.circle(minimap, (84, 152), 4, (8, 252, 255), -1)

        point, summary = MinimapMonitor.find_player_position_in_image(minimap)

        self.assertEqual(point, (84, 152))
        self.assertIn("来源=纯黄色", summary)

    def test_rejects_ambiguous_dim_yellow_market_decorations(self):
        minimap = np.full((180, 280, 3), 30, dtype=np.uint8)
        for index in range(8):
            x = 20 + index * 28
            cv2.rectangle(
                minimap,
                (x, 60),
                (x + 4, 64),
                (25, 205, 225),
                -1,
            )

        point, summary = MinimapMonitor.find_player_position_in_image(minimap)

        self.assertIsNone(point)
        self.assertIn("候选过多", summary)

    def test_counts_multiple_valid_yellow_candidates_for_lounge(self):
        minimap = np.full((120, 260, 3), 30, dtype=np.uint8)
        cv2.circle(minimap, (50, 40), 3, (8, 252, 255), -1)
        cv2.circle(minimap, (150, 80), 3, (8, 252, 255), -1)

        count = MinimapMonitor.count_player_marker_candidates_in_image(minimap)

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()

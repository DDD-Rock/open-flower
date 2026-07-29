import unittest

try:
    import cv2
    import numpy as np

    from detection.minimap_region_detector import (
        crop_minimap_content,
        detect_minimap_content_region,
    )
except ImportError:
    cv2 = None
    np = None
    crop_minimap_content = None
    detect_minimap_content_region = None


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class MinimapRegionDetectorTests(unittest.TestCase):
    @staticmethod
    def _make_frame(
        frame_width=1_280,
        frame_height=720,
        panel_x=6,
        panel_y=8,
        panel_width=300,
        panel_height=230,
    ):
        image = np.full((frame_height, frame_width, 3), 105, dtype=np.uint8)

        # A large dark distraction reproduces the old detector selecting some
        # other UI region instead of the upper-left minimap.
        cv2.rectangle(image, (50, 280), (390, 610), (20, 20, 20), -1)

        right = panel_x + panel_width - 1
        bottom = panel_y + panel_height - 1
        frame_color = (225, 225, 225)
        cv2.rectangle(
            image,
            (panel_x, panel_y),
            (right, bottom),
            frame_color,
            4,
        )
        divider_y = panel_y + 82
        cv2.rectangle(
            image,
            (panel_x, divider_y),
            (right, divider_y + 4),
            frame_color,
            -1,
        )
        cv2.rectangle(
            image,
            (panel_x + 5, divider_y + 5),
            (right - 5, bottom - 5),
            (30, 30, 30),
            -1,
        )
        cv2.line(
            image,
            (panel_x + 25, divider_y + 45),
            (right - 25, divider_y + 45),
            (205, 205, 205),
            3,
        )
        cv2.circle(
            image,
            (panel_x + 80, divider_y + 42),
            4,
            (0, 255, 255),
            -1,
        )
        return image, (panel_x, divider_y, right, bottom)

    def test_white_frame_wins_over_larger_dark_ui_region(self):
        image, geometry = self._make_frame()

        region = detect_minimap_content_region(image)

        self.assertIsNotNone(region)
        x, y, width, height = region
        panel_x, divider_y, right, bottom = geometry
        self.assertAlmostEqual(x, panel_x + 5, delta=3)
        self.assertAlmostEqual(y, divider_y + 5, delta=3)
        self.assertGreater(width, 275)
        self.assertLess(x + width, right + 1)
        self.assertLess(y + height, bottom + 1)

    def test_wide_free_market_minimap_is_not_truncated_to_200_by_150(self):
        image, _ = self._make_frame(
            frame_width=1_920,
            frame_height=1_080,
            panel_width=390,
            panel_height=250,
        )

        minimap = crop_minimap_content(image)

        self.assertIsNotNone(minimap)
        self.assertGreater(minimap.shape[1], 350)
        self.assertGreater(minimap.shape[0], 140)

    def test_rejects_unframed_dark_rectangle(self):
        image = np.full((720, 1_280, 3), 110, dtype=np.uint8)
        cv2.rectangle(image, (0, 0), (360, 300), (20, 20, 20), -1)

        self.assertIsNone(detect_minimap_content_region(image))


if __name__ == "__main__":
    unittest.main()

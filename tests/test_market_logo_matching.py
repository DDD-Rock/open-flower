import sys
import types
import unittest

try:
    import cv2
    import numpy as np

    # The matcher itself is platform-independent; these modules are only used
    # by the live Windows capture methods.
    sys.modules.setdefault("win32gui", types.SimpleNamespace())
    sys.modules.setdefault("mss", types.SimpleNamespace())
    from detection.market_button import MarketButtonDetector
except ImportError:
    cv2 = None
    np = None
    MarketButtonDetector = None


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class MarketLogoMatchingTests(unittest.TestCase):
    @staticmethod
    def _game_frame_with_minimap(panel_width=390, panel_height=300):
        image = np.full((720, 1_280, 3), 95, dtype=np.uint8)
        left, top = 6, 8
        right = left + panel_width - 1
        bottom = top + panel_height - 1
        light = (225, 225, 225)
        cv2.rectangle(image, (left, top), (right, bottom), light, 4)
        divider_y = top + 92
        cv2.rectangle(image, (left, divider_y), (right, divider_y + 4), light, -1)
        cv2.rectangle(
            image,
            (left + 5, divider_y + 5),
            (right - 5, bottom - 5),
            (28, 28, 28),
            -1,
        )
        return image, (left, divider_y)

    def test_matches_high_dpi_logo_outside_legacy_200_by_150_crop(self):
        detector = MarketButtonDetector()
        template = cv2.imread(detector.MARKET_LOGO_TEMPLATE)
        self.assertIsNotNone(template)

        scale = 1.65
        scaled = cv2.resize(
            template,
            (
                round(template.shape[1] * scale),
                round(template.shape[0] * scale),
            ),
            interpolation=cv2.INTER_CUBIC,
        )
        region = np.full((300, 430, 3), 28, dtype=np.uint8)
        x, y = 275, 165
        region[
            y : y + scaled.shape[0],
            x : x + scaled.shape[1],
        ] = scaled

        confidence = detector._match_logo_multiscale(region, template)

        self.assertGreater(confidence, 0.90)

    def test_market_check_uses_detected_wide_minimap_content(self):
        detector = MarketButtonDetector(hwnd=1)
        image, (panel_left, divider_y) = self._game_frame_with_minimap()
        template = cv2.imread(detector.MARKET_LOGO_TEMPLATE)
        scale = 1.65
        scaled = cv2.resize(
            template,
            (
                round(template.shape[1] * scale),
                round(template.shape[0] * scale),
            ),
            interpolation=cv2.INTER_CUBIC,
        )
        x, y = panel_left + 255, divider_y + 35
        image[y : y + scaled.shape[0], x : x + scaled.shape[1]] = scaled
        detector.capture_game_screen = lambda: image

        self.assertTrue(detector.is_market_logo_visible(confidence=0.50))


if __name__ == "__main__":
    unittest.main()

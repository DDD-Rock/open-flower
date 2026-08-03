import unittest

import cv2
import numpy as np

from detection.mouse_follow_verification_detector import (
    MouseFollowVerificationDetection,
    MouseFollowVerificationDetector,
    MouseFollowVerificationStabilizer,
)


class MouseFollowVerificationDetectorTests(unittest.TestCase):
    def test_detects_popup_at_different_positions_and_sizes(self):
        cases = [
            ((800, 600), (180, 120, 420, 260)),
            ((1920, 1080), (760, 360, 420, 260)),
            ((1280, 1000), (90, 410, 520, 300)),
            ((900, 700), (120, 180, 620, 240)),
        ]
        for canvas, body in cases:
            with self.subTest(canvas=canvas, body=body):
                detection = MouseFollowVerificationDetector.detect(
                    self._frame(canvas, body)
                )
                self.assertIsNotNone(detection)
                self.assertGreaterEqual(detection.confidence, 0.72)

    def test_rejects_popup_without_centered_title_glyphs(self):
        image = self._frame(
            (800, 600),
            (180, 120, 420, 260),
            includes_title_glyphs=False,
        )
        self.assertIsNone(MouseFollowVerificationDetector.detect(image))

    def test_rejects_small_gold_ui_element(self):
        image = self._frame((800, 600), (340, 240, 120, 80))
        self.assertIsNone(MouseFollowVerificationDetector.detect(image))

    def test_strong_detection_triggers_immediately_and_two_misses_clear(self):
        detection = MouseFollowVerificationDetection(
            rect=(100, 70, 440, 365),
            body_rect=(110, 120, 420, 260),
            gold_coverage=0.9,
            title_bar_dark_coverage=0.8,
            instruction_bar_dark_coverage=0.8,
            title_glyph_coverage=0.1,
            bright_target_coverage=0.0,
            confidence=0.9,
        )
        state = MouseFollowVerificationStabilizer()

        self.assertTrue(state.update(detection))
        self.assertTrue(state.is_present)
        self.assertFalse(state.update(None))
        self.assertTrue(state.update(None))
        self.assertFalse(state.is_present)

    @staticmethod
    def _frame(canvas, body, includes_title_glyphs=True):
        canvas_width, canvas_height = canvas
        image = np.full(
            (canvas_height, canvas_width, 3),
            (155, 86, 38),
            dtype=np.uint8,
        )
        x, y, width, height = body
        title_height = round(height * 0.18)
        instruction_height = round(height * 0.22)
        expansion = round(width * 0.025)
        cv2.rectangle(
            image,
            (x - expansion, y - title_height),
            (x + width + expansion - 1, y - 1),
            (48, 48, 48),
            -1,
        )
        cv2.rectangle(
            image,
            (x - expansion, y + height),
            (x + width + expansion - 1, y + height + instruction_height - 1),
            (48, 48, 48),
            -1,
        )
        cv2.rectangle(
            image,
            (x, y),
            (x + width - 1, y + height - 1),
            (82, 154, 205),
            -1,
        )
        if includes_title_glyphs:
            cv2.rectangle(
                image,
                (x + width // 2 - 45, y - title_height + 12),
                (x + width // 2 + 45, y - 12),
                (220, 220, 220),
                -1,
            )
        return image


if __name__ == "__main__":
    unittest.main()

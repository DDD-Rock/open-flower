import unittest

try:
    import cv2
    import numpy as np

    from detection.party_invite_detector import PartyInviteDetector
except ImportError:
    cv2 = None
    np = None
    PartyInviteDetector = None


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class PartyInviteDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = PartyInviteDetector()

    def test_finds_vertically_paired_orange_buttons_in_responsive_region(self):
        image = np.zeros((500, 800, 3), dtype=np.uint8)
        orange = (20, 120, 240)
        cv2.rectangle(image, (650, 400), (660, 410), orange, -1)
        cv2.rectangle(image, (650, 445), (660, 455), orange, -1)

        point = self.detector.find_accept_button_in_image(image)

        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 655, delta=1)
        self.assertAlmostEqual(point[1], 405, delta=1)

    def test_rejects_single_orange_control(self):
        image = np.zeros((500, 800, 3), dtype=np.uint8)
        cv2.rectangle(image, (650, 400), (660, 410), (20, 120, 240), -1)

        self.assertIsNone(self.detector.find_accept_button_in_image(image))

    def test_template_fallback_finds_paired_controls(self):
        accept = cv2.imread(self.detector.ACCEPT_TEMPLATE)
        decline = cv2.imread(self.detector.DECLINE_TEMPLATE)
        region = np.full((240, 360, 3), 35, dtype=np.uint8)
        x, y = 250, 35
        height, width = accept.shape[:2]
        region[y : y + height, x : x + width] = accept
        decline_y = y + 68
        region[
            decline_y : decline_y + decline.shape[0],
            x : x + decline.shape[1],
        ] = decline

        point = self.detector._find_by_template(region)

        self.assertEqual(point, (x + width // 2, y + height // 2))

    def test_templates_are_packaged_in_source_tree(self):
        self.assertTrue(self.detector.ACCEPT_TEMPLATE.endswith("accept_btn.png"))
        self.assertTrue(self.detector.DECLINE_TEMPLATE.endswith("decline_btn.png"))
        self.assertIsNotNone(cv2.imread(self.detector.ACCEPT_TEMPLATE))
        self.assertIsNotNone(cv2.imread(self.detector.DECLINE_TEMPLATE))


if __name__ == "__main__":
    unittest.main()

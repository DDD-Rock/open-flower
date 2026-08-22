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

    def test_rejects_vertically_paired_orange_ui_without_invite_icons(self):
        image = np.zeros((500, 800, 3), dtype=np.uint8)
        orange = (20, 120, 240)
        cv2.rectangle(image, (650, 400), (660, 410), orange, -1)
        cv2.rectangle(image, (650, 445), (660, 455), orange, -1)

        point = self.detector.find_accept_button_in_image(image)

        self.assertIsNone(point)

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

    def test_full_image_finds_real_paired_invite_icons(self):
        image = np.full((500, 800, 3), 35, dtype=np.uint8)
        accept = cv2.imread(self.detector.ACCEPT_TEMPLATE)
        decline = cv2.imread(self.detector.DECLINE_TEMPLATE)
        x, y = 650, 350
        image[y : y + 54, x : x + 54] = accept
        image[y + 68 : y + 122, x : x + 54] = decline

        point = self.detector.find_accept_button_in_image(image)

        self.assertEqual(point, (x + 27, y + 27))

    def test_templates_are_packaged_in_source_tree(self):
        self.assertTrue(self.detector.ACCEPT_TEMPLATE.endswith("accept_btn.png"))
        self.assertTrue(self.detector.DECLINE_TEMPLATE.endswith("decline_btn.png"))
        self.assertIsNotNone(cv2.imread(self.detector.ACCEPT_TEMPLATE))
        self.assertIsNotNone(cv2.imread(self.detector.DECLINE_TEMPLATE))

    def test_confirmation_tracks_only_the_clicked_popup(self):
        self.assertTrue(self.detector.is_same_popup((100, 200), (112, 186)))
        self.assertFalse(self.detector.is_same_popup((100, 200), (140, 200)))
        self.assertFalse(self.detector.is_same_popup((100, 200), None))

    def test_reuses_cached_position_while_resolution_is_unchanged(self):
        image = np.full((500, 800, 3), 35, dtype=np.uint8)
        accept = cv2.imread(self.detector.ACCEPT_TEMPLATE)
        decline = cv2.imread(self.detector.DECLINE_TEMPLATE)
        image[350:404, 650:704] = accept
        image[418:472, 650:704] = decline

        self.assertEqual(self.detector.find_accept_button_in_image(image), (677, 377))
        without_popup = np.full_like(image, 35)
        self.assertIsNone(self.detector.find_accept_button_in_image(without_popup))

        image_with_distant_decoy = without_popup.copy()
        image_with_distant_decoy[350:404, 480:534] = accept
        image_with_distant_decoy[418:472, 480:534] = decline
        self.assertIsNone(
            self.detector.find_accept_button_in_image(image_with_distant_decoy)
        )


if __name__ == "__main__":
    unittest.main()

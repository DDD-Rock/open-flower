"""Detect the accept button in a MapleStory Worlds party invitation."""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import mss
    import win32gui
except ImportError:  # Allows pure image tests to run outside Windows.
    mss = None
    win32gui = None


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(__file__))


class PartyInviteDetector:
    """Find a paired accept/decline control in the lower-right game area."""

    TEMPLATE_DIR = os.path.join(_base_dir(), "templates", "party")
    ACCEPT_TEMPLATE = os.path.join(TEMPLATE_DIR, "accept_btn.png")
    DECLINE_TEMPLATE = os.path.join(TEMPLATE_DIR, "decline_btn.png")

    def __init__(self, hwnd: Optional[int] = None, confidence: float = 0.76):
        self.hwnd = hwnd
        self.confidence = confidence

    def set_window_handle(self, hwnd: int):
        self.hwnd = hwnd

    @staticmethod
    def is_same_popup(initial_point, current_point, tolerance: int = 18) -> bool:
        if current_point is None:
            return False
        return (
            abs(current_point[0] - initial_point[0]) <= tolerance
            and abs(current_point[1] - initial_point[1]) <= tolerance
        )

    def find_accept_button(
        self,
        include_template: bool = True,
        minimum_confidence: Optional[float] = None,
    ) -> Optional[Tuple[int, int]]:
        """Return the accept button center in absolute screen coordinates."""
        image = self.capture_game_screen()
        if image is None:
            return None

        game_point = self.find_accept_button_in_image(
            image,
            include_template,
            minimum_confidence,
        )
        if game_point is None or win32gui is None:
            return None

        client_x, client_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
        return client_x + game_point[0], client_y + game_point[1]

    def capture_game_screen(self) -> Optional[np.ndarray]:
        if not self.hwnd or win32gui is None or mss is None:
            return None

        try:
            rect = win32gui.GetClientRect(self.hwnd)
            client_x, client_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
            width, height = rect[2], rect[3]
            if width <= 0 or height <= 0:
                return None
            monitor = {
                "left": client_x,
                "top": client_y,
                "width": width,
                "height": height,
            }
            with mss.mss() as capture:
                screenshot = np.array(capture.grab(monitor))
            return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def find_accept_button_in_image(
        self,
        image: np.ndarray,
        include_template: bool = True,
        minimum_confidence: Optional[float] = None,
    ) -> Optional[Tuple[int, int]]:
        """Find the button center in client-image coordinates."""
        if image is None or image.ndim != 3 or image.size == 0:
            return None

        height, width = image.shape[:2]
        search_x = max(0, int(width * 0.43))
        search_y = max(0, int(height * 0.67))
        region = image[search_y:, search_x:]
        if region.size == 0:
            return None

        # 橙色在技能栏和常驻 UI 中非常常见，不能仅凭两个橙色色块就判定为
        # 邀请。必须同时匹配“接受”和“拒绝”两个不同图标及其相对位置。
        point = (
            self._find_by_template(region, minimum_confidence)
            if include_template
            else None
        )
        if point is None:
            return None
        return search_x + point[0], search_y + point[1]

    @staticmethod
    def _find_by_color(region: np.ndarray) -> Optional[Tuple[int, int]]:
        blue, green, red = cv2.split(region)
        mask = (
            (red >= 190)
            & (green >= 60)
            & (green <= 170)
            & (blue <= 85)
            & ((red.astype(np.int16) - green.astype(np.int16)) >= 55)
            & ((green.astype(np.int16) - blue.astype(np.int16)) >= 20)
        ).astype(np.uint8)

        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        blobs = []
        for index in range(1, count):
            x, y, width, height, area = stats[index]
            if (
                area >= 18
                and width >= 4
                and height >= 4
                and width <= 85
                and height <= 85
            ):
                blobs.append(
                    {
                        "center": centroids[index],
                        "width": int(width),
                        "height": int(height),
                        "area": int(area),
                    }
                )
        blobs.sort(key=lambda blob: blob["area"], reverse=True)
        blobs = blobs[:80]

        best = None
        for accept in blobs:
            for decline in blobs:
                if accept is decline:
                    continue
                accept_x, accept_y = accept["center"]
                decline_x, decline_y = decline["center"]
                dx = abs(decline_x - accept_x)
                dy = decline_y - accept_y
                button_size = max(
                    accept["width"],
                    accept["height"],
                    decline["width"],
                    decline["height"],
                )
                if not (
                    dy >= max(20, button_size * 1.5)
                    and dy <= max(115, button_size * 5.5)
                    and dx <= max(12, button_size * 0.9)
                    and decline_y <= region.shape[0] * 0.72
                ):
                    continue

                preferred_gap = max(38, button_size * 2.4)
                size_balance = abs(accept["area"] - decline["area"]) * 0.15
                score = (
                    accept["area"]
                    + decline["area"]
                    - dx * 4
                    - abs(dy - preferred_gap)
                    - size_balance
                )
                if best is None or score > best[0]:
                    best = (score, accept_x, accept_y)

        if best is None or best[0] <= 30:
            return None
        return int(round(best[1])), int(round(best[2]))

    def _find_by_template(
        self,
        region: np.ndarray,
        minimum_confidence: Optional[float] = None,
    ) -> Optional[Tuple[int, int]]:
        accept_template = cv2.imread(self.ACCEPT_TEMPLATE)
        decline_template = cv2.imread(self.DECLINE_TEMPLATE)
        if accept_template is None or decline_template is None:
            return None

        threshold = self.confidence if minimum_confidence is None else minimum_confidence
        scales = (
            0.45,
            0.55,
            0.65,
            0.75,
            0.85,
            0.95,
            1.0,
            1.1,
            1.2,
            1.3,
            1.45,
            1.6,
        )
        best = None
        for scale in scales:
            accept = self._resize_template(accept_template, scale, region)
            decline = self._resize_template(decline_template, scale, region)
            if accept is None or decline is None:
                continue

            result = cv2.matchTemplate(region, accept, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score < threshold:
                continue

            accept_h, accept_w = accept.shape[:2]
            decline_h, decline_w = decline.shape[:2]
            center_x = location[0] + accept_w // 2
            center_y = location[1] + accept_h // 2
            search_x = max(0, location[0] - accept_w)
            search_y = max(0, location[1] + accept_h // 2)
            search_right = min(region.shape[1], search_x + max(accept_w * 3, 40))
            search_bottom = min(region.shape[0], search_y + max(accept_h * 4, 60))
            decline_region = region[search_y:search_bottom, search_x:search_right]
            if (
                decline_region.shape[0] < decline_h
                or decline_region.shape[1] < decline_w
            ):
                continue

            decline_result = cv2.matchTemplate(
                decline_region, decline, cv2.TM_CCOEFF_NORMED
            )
            _, decline_score, _, decline_location = cv2.minMaxLoc(decline_result)
            if decline_score < threshold:
                continue

            decline_center_x = search_x + decline_location[0] + decline_w // 2
            decline_center_y = search_y + decline_location[1] + decline_h // 2
            dx = abs(decline_center_x - center_x)
            dy = decline_center_y - center_y
            max_size = max(accept_w, accept_h, decline_w, decline_h)
            if dx > max(6, max(accept_w, decline_w) * 0.40):
                continue
            if dy < max_size * 0.80 or dy > max_size * 1.80:
                continue

            pair_score = min(float(score), float(decline_score))
            if best is None or pair_score > best[0]:
                best = (pair_score, center_x, center_y)

        if best is None:
            return None
        return int(best[1]), int(best[2])

    @staticmethod
    def _resize_template(
        template: np.ndarray, scale: float, region: np.ndarray
    ) -> Optional[np.ndarray]:
        height, width = template.shape[:2]
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        if new_width > region.shape[1] or new_height > region.shape[0]:
            return None
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
        return cv2.resize(template, (new_width, new_height), interpolation=interpolation)

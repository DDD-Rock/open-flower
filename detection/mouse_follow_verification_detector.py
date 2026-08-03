"""鼠标跟随验证（寻找透明图形）弹窗识别及状态防抖。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class MouseFollowVerificationDetection:
    rect: tuple[int, int, int, int]
    body_rect: tuple[int, int, int, int]
    gold_coverage: float
    title_bar_dark_coverage: float
    instruction_bar_dark_coverage: float
    title_glyph_coverage: float
    bright_target_coverage: float
    confidence: float


class MouseFollowVerificationDetector:
    """在整张游戏画面中按弹窗自身结构寻找验证弹窗。"""

    MINIMUM_COMPONENT_CELLS = 900
    MINIMUM_BODY_WIDTH = 150
    MINIMUM_BODY_HEIGHT = 100
    MINIMUM_GOLD_COVERAGE = 0.55
    MINIMUM_DARK_BAR_COVERAGE = 0.48
    MINIMUM_TITLE_GLYPH_COVERAGE = 0.012
    MINIMUM_BODY_ASPECT_RATIO = 0.80
    MAXIMUM_BODY_ASPECT_RATIO = 3.00

    STRONG_GOLD_COVERAGE = 0.85
    STRONG_DARK_BAR_COVERAGE = 0.72
    STRONG_TITLE_GLYPH_COVERAGE = 0.08

    @classmethod
    def detect(cls, image: np.ndarray) -> Optional[MouseFollowVerificationDetection]:
        if image is None or image.ndim != 3 or image.shape[2] < 3:
            return None
        height, width = image.shape[:2]
        if width < 240 or height < 180:
            return None

        stride = max(2, min(6, min(width, height) // 300))
        sampled = image[::stride, ::stride, :3]
        blue = sampled[:, :, 0].astype(np.int16)
        green = sampled[:, :, 1].astype(np.int16)
        red = sampled[:, :, 2].astype(np.int16)
        gold_mask = (
            (red >= 105)
            & (green >= 65)
            & (red >= green + 10)
            & (green >= blue + 12)
            & (red >= blue + 42)
            & (blue <= 175)
        ).astype(np.uint8)

        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            gold_mask,
            connectivity=8,
        )
        candidates = sorted(
            (stats[index] for index in range(1, count)),
            key=lambda item: int(item[cv2.CC_STAT_AREA]),
            reverse=True,
        )

        best = None
        for component in candidates[:8]:
            cell_area = int(component[cv2.CC_STAT_AREA])
            if cell_area < cls.MINIMUM_COMPONENT_CELLS:
                continue
            grid_x = int(component[cv2.CC_STAT_LEFT])
            grid_y = int(component[cv2.CC_STAT_TOP])
            grid_width = int(component[cv2.CC_STAT_WIDTH])
            grid_height = int(component[cv2.CC_STAT_HEIGHT])
            gold_coverage = cell_area / max(1, grid_width * grid_height)
            if gold_coverage < cls.MINIMUM_GOLD_COVERAGE:
                continue

            x = grid_x * stride
            y = grid_y * stride
            body_width = min(width, (grid_x + grid_width) * stride) - x
            body_height = min(height, (grid_y + grid_height) * stride) - y
            if body_width < cls.MINIMUM_BODY_WIDTH or body_height < cls.MINIMUM_BODY_HEIGHT:
                continue
            aspect_ratio = body_width / body_height
            if not cls.MINIMUM_BODY_ASPECT_RATIO <= aspect_ratio <= cls.MAXIMUM_BODY_ASPECT_RATIO:
                continue

            bars = cls._surrounding_bars((x, y, body_width, body_height), width, height)
            if bars is None:
                continue
            title_rect, instruction_rect = bars
            title_dark = cls._coverage(image, title_rect, stride, cls._dark_neutral_mask)
            instruction_dark = cls._coverage(
                image,
                instruction_rect,
                stride,
                cls._dark_neutral_mask,
            )
            if (
                title_dark < cls.MINIMUM_DARK_BAR_COVERAGE
                or instruction_dark < cls.MINIMUM_DARK_BAR_COVERAGE
            ):
                continue

            title_x, title_y, title_width, title_height = title_rect
            glyph_rect = (
                round(title_x + title_width * 0.28),
                title_y,
                round(title_width * 0.44),
                title_height,
            )
            title_glyphs = cls._coverage(
                image,
                glyph_rect,
                max(1, stride // 2),
                cls._bright_neutral_mask,
            )
            if title_glyphs < cls.MINIMUM_TITLE_GLYPH_COVERAGE:
                continue

            body_rect = (x, y, body_width, body_height)
            bright_target = cls._coverage(
                image,
                body_rect,
                stride,
                cls._bright_neutral_mask,
            )
            confidence = cls.confidence(
                gold_coverage,
                title_dark,
                instruction_dark,
                title_glyphs,
                bright_target,
            )
            whole_x = min(title_rect[0], x, instruction_rect[0])
            whole_y = min(title_rect[1], y, instruction_rect[1])
            whole_right = max(
                title_rect[0] + title_rect[2],
                x + body_width,
                instruction_rect[0] + instruction_rect[2],
            )
            whole_bottom = max(
                title_rect[1] + title_rect[3],
                y + body_height,
                instruction_rect[1] + instruction_rect[3],
            )
            candidate = MouseFollowVerificationDetection(
                (whole_x, whole_y, whole_right - whole_x, whole_bottom - whole_y),
                body_rect,
                gold_coverage,
                title_dark,
                instruction_dark,
                title_glyphs,
                bright_target,
                confidence,
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        return best

    @classmethod
    def confidence(cls, gold, title_dark, instruction_dark, glyphs, bright_target):
        target_bonus = min(0.05, max(0.0, bright_target - 0.01) * 0.5)
        return min(
            1.0,
            0.35 * cls._normalize(gold, cls.MINIMUM_GOLD_COVERAGE, cls.STRONG_GOLD_COVERAGE)
            + 0.22 * cls._normalize(
                title_dark,
                cls.MINIMUM_DARK_BAR_COVERAGE,
                cls.STRONG_DARK_BAR_COVERAGE,
            )
            + 0.22 * cls._normalize(
                instruction_dark,
                cls.MINIMUM_DARK_BAR_COVERAGE,
                cls.STRONG_DARK_BAR_COVERAGE,
            )
            + 0.21 * cls._normalize(
                glyphs,
                cls.MINIMUM_TITLE_GLYPH_COVERAGE,
                cls.STRONG_TITLE_GLYPH_COVERAGE,
            )
            + target_bonus,
        )

    @staticmethod
    def _surrounding_bars(body_rect, image_width, image_height):
        x, y, width, height = body_rect
        expansion = width * 0.025
        title_height = round(height * 0.18)
        instruction_height = round(height * 0.22)
        bar_x = max(0, int(np.floor(x - expansion)))
        bar_right = min(image_width, int(np.ceil(x + width + expansion)))
        title_y = y - title_height
        instruction_bottom = y + height + instruction_height
        if title_y < 0 or instruction_bottom > image_height or bar_right <= bar_x:
            return None
        return (
            (bar_x, title_y, bar_right - bar_x, title_height),
            (bar_x, y + height, bar_right - bar_x, instruction_height),
        )

    @staticmethod
    def _coverage(image, rect, stride, predicate):
        x, y, width, height = rect
        x0 = max(0, int(np.floor(x)))
        y0 = max(0, int(np.floor(y)))
        x1 = min(image.shape[1], int(np.ceil(x + width)))
        y1 = min(image.shape[0], int(np.ceil(y + height)))
        if x0 >= x1 or y0 >= y1:
            return 0.0
        region = image[y0:y1: max(1, stride), x0:x1: max(1, stride), :3]
        return float(predicate(region).mean()) if region.size else 0.0

    @staticmethod
    def _dark_neutral_mask(region):
        maximum = region.max(axis=2)
        minimum = region.min(axis=2)
        return (maximum <= 92) & ((maximum.astype(np.int16) - minimum) <= 30)

    @staticmethod
    def _bright_neutral_mask(region):
        maximum = region.max(axis=2)
        minimum = region.min(axis=2)
        return (minimum >= 125) & ((maximum.astype(np.int16) - minimum) <= 45)

    @staticmethod
    def _normalize(value, lower, upper):
        return min(max((value - lower) / (upper - lower), 0.0), 1.0)


class MouseFollowVerificationStabilizer:
    IMMEDIATE_CONFIDENCE = 0.72

    def __init__(self, required_detections: int = 2, required_misses: int = 2):
        self.required_detections = max(1, required_detections)
        self.required_misses = max(1, required_misses)
        self.reset()

    def update(self, detection: Optional[MouseFollowVerificationDetection]) -> bool:
        if detection is not None:
            self.consecutive_misses = 0
            self.consecutive_detections += 1
            self.latest_detection = detection
            if not self.is_present and (
                detection.confidence >= self.IMMEDIATE_CONFIDENCE
                or self.consecutive_detections >= self.required_detections
            ):
                self.is_present = True
                return True
            return False
        self.consecutive_detections = 0
        self.consecutive_misses += 1
        if self.is_present and self.consecutive_misses >= self.required_misses:
            self.is_present = False
            self.latest_detection = None
            return True
        return False

    def reset(self):
        self.is_present = False
        self.consecutive_detections = 0
        self.consecutive_misses = 0
        self.latest_detection = None

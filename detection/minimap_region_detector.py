"""Pure OpenCV helpers for locating the in-game minimap.

The minimap panel is anchored to the upper-left of the game client.  Its map
artwork varies heavily between maps, while the light rectangular frame is
stable.  Detect that frame first and return only the map canvas inside it.

This module deliberately has no Windows imports so the geometry can be covered
by unit tests on every development platform.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class _BrightRun:
    y: int
    start_x: int
    end_x: int

    @property
    def width(self) -> int:
        return self.end_x - self.start_x + 1


def _bright_near_mask(image: np.ndarray) -> np.ndarray:
    """Return the tolerant light-frame mask used by the successful Mac path."""
    channels = image.astype(np.int16)
    minimum = channels.min(axis=2)
    maximum = channels.max(axis=2)
    brightness = channels.sum(axis=2) // 3
    bright = (
        (brightness >= 170)
        & (minimum >= 145)
        & ((maximum - minimum) <= 90)
    ).astype(np.uint8)
    return cv2.dilate(bright, np.ones((3, 3), dtype=np.uint8), iterations=1)


def _horizontal_runs(mask: np.ndarray) -> List[_BrightRun]:
    runs: List[_BrightRun] = []
    height, width = mask.shape
    for y in range(height):
        start = None
        last_bright = -1
        gap = 0
        for x in range(width):
            if mask[y, x]:
                if start is None:
                    start = x
                last_bright = x
                gap = 0
            elif start is not None:
                gap += 1
                if gap > 2:
                    if last_bright - start + 1 >= 80:
                        runs.append(_BrightRun(y, start, last_bright))
                    start = None
                    last_bright = -1
                    gap = 0
        if start is not None and last_bright - start + 1 >= 80:
            runs.append(_BrightRun(y, start, last_bright))
    return runs


def _vertical_support(mask: np.ndarray, x: int, top: int, bottom: int) -> int:
    if x < 0 or x >= mask.shape[1] or bottom < top:
        return 0
    return int(np.count_nonzero(mask[top : bottom + 1, x]))


def _refined_sides(
    mask: np.ndarray,
    top: int,
    bottom: int,
    approximate_left: int,
    approximate_right: int,
) -> Optional[Tuple[int, int, int, int]]:
    approximate_width = approximate_right - approximate_left + 1
    if bottom <= top or approximate_width < 100:
        return None

    radius = max(12, round(approximate_width * 0.10))
    left_range = range(
        max(0, approximate_left - radius),
        min(approximate_right, approximate_left + radius) + 1,
    )
    right_range = range(
        max(approximate_left, approximate_right - radius),
        min(mask.shape[1] - 1, approximate_right + radius) + 1,
    )
    left_samples = [(x, _vertical_support(mask, x, top, bottom)) for x in left_range]
    right_samples = [(x, _vertical_support(mask, x, top, bottom)) for x in right_range]
    if not left_samples or not right_samples:
        return None

    left_cutoff = round(max(value for _, value in left_samples) * 0.92)
    right_cutoff = round(max(value for _, value in right_samples) * 0.92)
    left = next((sample for sample in left_samples if sample[1] >= left_cutoff), None)
    right = next(
        (sample for sample in reversed(right_samples) if sample[1] >= right_cutoff),
        None,
    )
    if left is None or right is None or right[0] - left[0] + 1 < 100:
        return None
    return left[0], right[0], left[1], right[1]


def _bright_bands(
    mask: np.ndarray,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> List[Tuple[int, int]]:
    width = right - left + 1
    bands: List[Tuple[int, int]] = []
    start = None
    last = -1
    for y in range(top, bottom + 1):
        ratio = np.count_nonzero(mask[y, left : right + 1]) / max(width, 1)
        if ratio >= 0.88:
            if start is None:
                start = y
            last = y
        elif start is not None:
            bands.append((start, last))
            start = None
            last = -1
    if start is not None:
        bands.append((start, last))
    return bands


def _content_rect(
    mask: np.ndarray,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> Optional[Rect]:
    panel_width = right - left + 1
    panel_height = bottom - top + 1
    if panel_width < 100 or panel_height < 110:
        return None

    horizontal_inset = max(3, round(panel_width * 0.018))
    bands = _bright_bands(mask, left, right, top, bottom)
    minimum_divider_y = top + round(panel_width * 0.20)
    maximum_divider_y = min(bottom - 20, top + round(panel_width * 0.62))
    divider = next(
        (
            band
            for band in bands
            if band[1] - band[0] + 1 >= 4
            and band[0] >= minimum_divider_y
            and band[1] <= maximum_divider_y
        ),
        None,
    )
    bottom_border = next(
        (
            band
            for band in reversed(bands)
            if band[1] - band[0] + 1 >= 4
            and bottom - band[1] <= 3
            and bottom - band[0] <= max(10, round(panel_width * 0.14))
        ),
        None,
    )

    content_top = divider[1] + 1 if divider else top + round(panel_width * 0.38)
    content_bottom = (
        bottom_border[0]
        if bottom_border
        else bottom - max(5, round(panel_width * 0.059)) + 1
    )
    content_width = panel_width - horizontal_inset * 2
    content_height = content_bottom - content_top
    if content_width < 70 or content_height < 45:
        return None
    return left + horizontal_inset, content_top, content_width, content_height


def detect_minimap_content_region(
    image: np.ndarray,
    search_width: int = 480,
    search_height: int = 420,
) -> Optional[Rect]:
    """Locate the upper-left white minimap frame and return its map canvas."""
    if image is None or image.ndim != 3 or image.shape[0] < 110:
        return None

    image_height, image_width = image.shape[:2]
    dynamic_search_size = min(640, max(search_width, image_width // 4))
    width = min(dynamic_search_size, image_width)
    height = min(max(search_height, dynamic_search_size), image_height)
    region = image[:height, :width]
    bright_mask = _bright_near_mask(region)
    runs = [
        run
        for run in _horizontal_runs(bright_mask)
        if 100 <= run.width <= 560
        and run.start_x <= 24
        and run.end_x < width - 3
    ]

    maximum_frame_top = min(64, max(24, height // 12))
    best_rect = None
    best_score = float("-inf")
    for top_index, top_run in enumerate(runs):
        if top_run.y > maximum_frame_top:
            continue
        for bottom_run in runs[top_index + 1 :]:
            frame_height = bottom_run.y - top_run.y + 1
            if frame_height > 600:
                break
            if frame_height < 110:
                continue

            approximate_left = max(top_run.start_x, bottom_run.start_x)
            approximate_right = min(top_run.end_x, bottom_run.end_x)
            approximate_width = approximate_right - approximate_left + 1
            if not 100 <= approximate_width <= 560 or approximate_left > 18:
                continue
            sides = _refined_sides(
                bright_mask,
                top_run.y,
                bottom_run.y,
                approximate_left,
                approximate_right,
            )
            if sides is None:
                continue
            left, right, left_support, right_support = sides
            frame_width = right - left + 1
            aspect = frame_height / frame_width
            required_support = round(frame_height * 0.78)
            if not 0.62 <= aspect <= 2.40:
                continue
            if left_support < required_support or right_support < required_support:
                continue

            content = _content_rect(
                bright_mask,
                left,
                top_run.y,
                right,
                bottom_run.y,
            )
            if content is None:
                continue
            side_ratio = (left_support + right_support) / (frame_height * 2)
            score = (
                side_ratio * 10_000
                + frame_width * frame_height * 0.02
                - (top_run.y + left) * 120
            )
            if score > best_score:
                best_score = score
                best_rect = content
    return best_rect


def crop_minimap_content(image: np.ndarray) -> Optional[np.ndarray]:
    """Return a copy of the detected pure minimap canvas."""
    rect = detect_minimap_content_region(image)
    if rect is None:
        return None
    x, y, width, height = rect
    return image[y : y + height, x : x + width].copy()

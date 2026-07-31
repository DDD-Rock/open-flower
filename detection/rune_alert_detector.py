"""符文诅咒横幅识别及状态防抖。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class RuneAlertDetection:
    rect: tuple[int, int, int, int]
    line_coverage: float
    interior_tint: float
    confidence: float


class RuneAlertDetector:
    MINIMUM_LINE_COVERAGE = 0.32
    MINIMUM_LINE_WIDTH_RATIO = 0.30
    MINIMUM_SPAN_RATIO = 0.06
    MAXIMUM_SPAN_RATIO = 0.22
    MINIMUM_HORIZONTAL_OVERLAP = 0.80
    MINIMUM_INTERIOR_TINT = 0.25
    COLUMN_STRIDE = 2

    @classmethod
    def detect(cls, image: np.ndarray) -> Optional[RuneAlertDetection]:
        if image is None or image.ndim != 3 or min(image.shape[:2]) < 64:
            return None
        height, width = image.shape[:2]
        sampled = image[:, :: cls.COLUMN_STRIDE]
        blue, green, red = [channel.astype(np.int16) for channel in cv2.split(sampled)]
        border = (
            (blue >= 90)
            & (blue >= green + 45)
            & (red >= green + 20)
            & (blue >= red + 5)
            & (red >= 40)
        )
        coverage = border.mean(axis=1)
        hot_rows = np.flatnonzero(coverage >= cls.MINIMUM_LINE_COVERAGE)
        groups = cls._merge_rows(hot_rows)
        lines = []
        gap_tolerance = max(2, sampled.shape[1] // 128)
        for start, end in groups:
            hits = border[start:end].any(axis=0)
            run = cls._longest_run(hits, gap_tolerance)
            if run and run[1] - run[0] >= sampled.shape[1] * cls.MINIMUM_LINE_WIDTH_RATIO:
                lines.append((start, end - 1, run[0], run[1] - 1, float(coverage[start:end].max())))

        best = None
        for index, top in enumerate(lines):
            for bottom in lines[index + 1 :]:
                span = bottom[1] - top[0]
                if not height * cls.MINIMUM_SPAN_RATIO <= span <= height * cls.MAXIMUM_SPAN_RATIO:
                    continue
                left, right = max(top[2], bottom[2]), min(top[3], bottom[3])
                overlap = right - left + 1
                narrower = min(top[3] - top[2] + 1, bottom[3] - bottom[2] + 1)
                if narrower <= 0 or overlap / narrower < cls.MINIMUM_HORIZONTAL_OVERLAP:
                    continue
                interior = sampled[top[1] + 1 : bottom[0], left : right + 1]
                if interior.shape[0] < 4:
                    continue
                b, g, r = [channel.astype(np.int16) for channel in cv2.split(interior)]
                tint = float(((b >= g + 25) & (r >= g + 8) & (b >= 40)).mean())
                if tint < cls.MINIMUM_INTERIOR_TINT:
                    continue
                line_coverage = min(top[4], bottom[4])
                confidence = 0.5 * cls._normalize(line_coverage, 0.32, 0.55) + 0.5 * cls._normalize(tint, 0.25, 0.45)
                candidate = RuneAlertDetection(
                    (left * cls.COLUMN_STRIDE, top[0], overlap * cls.COLUMN_STRIDE, span + 1),
                    line_coverage,
                    tint,
                    confidence,
                )
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
        return best

    @staticmethod
    def _normalize(value, lower, upper):
        return min(max((value - lower) / (upper - lower), 0.0), 1.0)

    @staticmethod
    def _merge_rows(rows):
        groups = []
        for row in rows:
            row = int(row)
            if groups and row - (groups[-1][1] - 1) <= 2:
                groups[-1] = (groups[-1][0], row + 1)
            else:
                groups.append((row, row + 1))
        return groups

    @staticmethod
    def _longest_run(hits, gap_tolerance):
        positions = np.flatnonzero(hits)
        if not positions.size:
            return None
        best = start = previous = int(positions[0])
        best_range = (start, start + 1)
        for value in positions[1:]:
            value = int(value)
            if value - previous > gap_tolerance:
                if previous - start > best_range[1] - best_range[0] - 1:
                    best_range = (start, previous + 1)
                start = value
            previous = value
        if previous - start > best_range[1] - best_range[0] - 1:
            best_range = (start, previous + 1)
        return best_range


class RuneAlertStabilizer:
    def __init__(self, required_detections: int = 2, required_misses: int = 2):
        self.required_detections = max(1, required_detections)
        self.required_misses = max(1, required_misses)
        self.reset()

    def update(self, detection: Optional[RuneAlertDetection]) -> bool:
        if detection is not None:
            self.consecutive_misses = 0
            self.consecutive_detections += 1
            self.latest_detection = detection
            if not self.is_present and self.consecutive_detections >= self.required_detections:
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

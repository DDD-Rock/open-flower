"""监控模式的安全区和稳定状态模型。"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from models.map_topology import NormalizedMapPoint


@dataclass
class MonitorSafeZone:
    center: NormalizedMapPoint
    width: float
    height: float

    MINIMUM_SIDE_RATIO = 0.02

    def __post_init__(self):
        self.width = self._side(self.width)
        self.height = self._side(self.height)

    @classmethod
    def _side(cls, value: float) -> float:
        return min(max(float(value), cls.MINIMUM_SIDE_RATIO), 1.0) if math.isfinite(value) else cls.MINIMUM_SIDE_RATIO

    @property
    def normalized_rect(self) -> tuple[float, float, float, float]:
        left = max(0.0, self.center.x - self.width / 2)
        top = max(0.0, self.center.y - self.height / 2)
        right = min(1.0, self.center.x + self.width / 2)
        bottom = min(1.0, self.center.y + self.height / 2)
        return left, top, max(0.0, right - left), max(0.0, bottom - top)

    def contains(self, point: tuple[float, float], size: tuple[int, int]) -> bool:
        width, height = size
        if width <= 0 or height <= 0:
            return True
        normalized = NormalizedMapPoint.from_pixel(point, size)
        x, y, rect_width, rect_height = self.normalized_rect
        return x <= normalized.x <= x + rect_width and y <= normalized.y <= y + rect_height

    def to_dict(self):
        return {"center": self.center.to_dict(), "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, value):
        return cls(
            NormalizedMapPoint.from_dict((value or {}).get("center") or {}),
            (value or {}).get("width", cls.MINIMUM_SIDE_RATIO),
            (value or {}).get("height", cls.MINIMUM_SIDE_RATIO),
        )


class SafeZoneStabilizer:
    REQUIRED_OUTSIDE_SECONDS = 1.5
    REQUIRED_INSIDE_SECONDS = 1.0
    LOST_MARKER_GRACE_SECONDS = 10.0

    def __init__(self):
        self.reset()

    def update(self, observed_outside: Optional[bool], now: Optional[float] = None) -> str:
        now = time.monotonic() if now is None else now
        if observed_outside is None:
            self._pending_outside = None
            self._pending_since = None
            if not self.is_outside:
                self._lost_since = None
                return "none"
            if self._lost_since is None:
                self._lost_since = now
                return "none"
            if now - self._lost_since < self.LOST_MARKER_GRACE_SECONDS:
                return "none"
            self.is_outside = False
            self._lost_since = None
            return "lost_track"

        self._lost_since = None
        if observed_outside == self.is_outside:
            self._pending_outside = None
            self._pending_since = None
            return "none"
        required = (
            self.REQUIRED_OUTSIDE_SECONDS
            if observed_outside
            else self.REQUIRED_INSIDE_SECONDS
        )
        if self._pending_outside != observed_outside or self._pending_since is None:
            self._pending_outside = observed_outside
            self._pending_since = now
            return "none"
        if now - self._pending_since < required:
            return "none"
        self.is_outside = observed_outside
        self._pending_outside = None
        self._pending_since = None
        return "breached" if observed_outside else "returned"

    def reset(self):
        self.is_outside = False
        self._pending_outside = None
        self._pending_since = None
        self._lost_since = None

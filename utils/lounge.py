"""休息室人数变化追踪与喊话选择，保持为可独立测试的纯逻辑。"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class LoungeMarkerCounts:
    yellow: int
    orange: int

    def has_increase(self, previous: "LoungeMarkerCounts") -> bool:
        return self.yellow > previous.yellow or self.orange > previous.orange


@dataclass(frozen=True)
class LoungePopulationChange:
    previous: LoungeMarkerCounts
    current: LoungeMarkerCounts

    @property
    def increased(self) -> bool:
        return self.current.has_increase(self.previous)


class LoungePopulationTracker:
    def __init__(self, confirmation_frames: int = 2):
        self.confirmation_frames = max(1, confirmation_frames)
        self.baseline = None
        self._candidate = None
        self._candidate_frames = 0

    def observe(self, counts: LoungeMarkerCounts):
        if counts == self.baseline:
            self._candidate = None
            self._candidate_frames = 0
            return None
        if counts == self._candidate:
            self._candidate_frames += 1
        else:
            self._candidate = counts
            self._candidate_frames = 1
        if self._candidate_frames < self.confirmation_frames:
            return None
        previous = self.baseline
        self.baseline = counts
        self._candidate = None
        self._candidate_frames = 0
        return LoungePopulationChange(previous, counts) if previous is not None else None


class LoungeAnnouncementPicker:
    REGULAR = (
        "BUFF放好了", "BUFF好了", "buff放完了", "buff好了", "状态放好了",
        "状态补好了", "技能放完了", "已经放好了", "都放好了", "这轮好了",
    )
    SHORT = ("补完了", "好了", "可以了", "搞定", "搞定了")

    def __init__(self, rng=None):
        self.rng = rng or random
        self.last_base = None

    def next(self):
        preferred = self.REGULAR if self.rng.randrange(100) < 85 else self.SHORT
        available = [item for item in preferred if item != self.last_base]
        base = self.rng.choice(available or list(self.REGULAR + self.SHORT))
        self.last_base = base
        roll = self.rng.randrange(100)
        punctuation = "" if roll < 70 else "。" if roll < 90 else "~"
        return base + punctuation

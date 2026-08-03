"""跟补模式的纯导航规则。

这里不依赖窗口截图或输入库，方便 Windows/macOS 两端保持同一套边界。
"""

import random
from dataclasses import dataclass
from typing import Optional


CENTER_ADJUST_INTERVAL_RANGE = (10.0, 13.0)
NEW_COLLISION_DISTANCE = 1.0


def teleport_direction_to_base(current_x: float, base_x: float) -> Optional[str]:
    """返回朝基准点瞬移需要按的方向；正好重合时返回 None。"""
    if current_x < base_x:
        return "right"
    if current_x > base_x:
        return "left"
    return None


def is_outside_anchor_band(current_x: float, base_x: float, tolerance: float) -> bool:
    """是否走出了用户配置的 base_x +/- tolerance 允许区域。"""
    return abs(current_x - base_x) > max(0.0, float(tolerance))


def next_center_adjust_interval() -> float:
    """下一次瞬移修正的随机间隔。"""
    return random.uniform(*CENTER_ADJUST_INTERVAL_RANGE)


@dataclass
class TeleportExcursionGuard:
    """防止瞬移跨点后立即反向，同时允许识别后续的新碰撞。"""

    last_teleport_direction: Optional[str] = None
    awaiting_stable_position: bool = False
    guarded_reverse_direction: Optional[str] = None
    guarded_distance: Optional[float] = None

    def record_teleport(self, direction: str) -> None:
        self.last_teleport_direction = direction
        self.awaiting_stable_position = True
        self.guarded_reverse_direction = None
        self.guarded_distance = None

    def should_correct(
        self,
        current_x: float,
        base_x: float,
        tolerance: float,
    ) -> bool:
        if not is_outside_anchor_band(current_x, base_x, tolerance):
            self._clear_guard()
            return False

        direction = teleport_direction_to_base(current_x, base_x)
        distance = abs(current_x - base_x)

        if self.awaiting_stable_position:
            self.awaiting_stable_position = False
            # 瞬移后仍在原来一侧：黄点已经稳定，可以继续朝基准点补一次。
            if direction == self.last_teleport_direction:
                self.guarded_reverse_direction = None
                self.guarded_distance = None
                return True

            # 瞬移跨过基准点：保护这次反向结果，避免马上瞬移回去。
            self.guarded_reverse_direction = direction
            self.guarded_distance = distance
            return False

        if direction == self.guarded_reverse_direction:
            baseline = self.guarded_distance if self.guarded_distance is not None else distance
            if distance >= baseline + NEW_COLLISION_DISTANCE:
                # 黄点在被保护的一侧继续向外移动，视为一次新的撞击。
                self.guarded_reverse_direction = None
                self.guarded_distance = None
                return True
            self.guarded_distance = min(baseline, distance)
            return False

        self.guarded_reverse_direction = None
        self.guarded_distance = None
        return True

    def _clear_guard(self) -> None:
        self.awaiting_stable_position = False
        self.guarded_reverse_direction = None
        self.guarded_distance = None

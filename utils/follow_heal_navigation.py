"""跟补模式的纯导航规则。

这里不依赖窗口截图或输入库，方便 Windows/macOS 两端保持同一套边界。
"""

import random
from dataclasses import dataclass
from typing import Optional


CENTER_ADJUST_INTERVAL_RANGE = (4.0, 7.0)
HEAL_HOLD_RANGE = (8.0, 12.0)
HEAL_GAP_RANGE = (0.25, 0.60)
NEW_COLLISION_DISTANCE = 1.0
PROTECTIVE_BOUNDARY_RATIO = 0.75
NEAR_ANCHOR_EXCURSION_RATIO = 0.5
WALKING_KEEPALIVE_INTERVAL_RANGE = (8.0, 12.0)
WALKING_KEEPALIVE_DURATION_RANGE = (0.20, 0.30)
WALKING_KEEPALIVE_RECOVERY_RANGE = (0.08, 0.22)


def teleport_direction_to_base(current_x: float, base_x: float) -> Optional[str]:
    """返回朝基准点瞬移需要按的方向；正好重合时返回 None。"""
    if current_x < base_x:
        return "right"
    if current_x > base_x:
        return "left"
    return None


def walking_direction_to_base(current_x: float, base_x: float) -> Optional[str]:
    """走路方案独立判断回位方向。"""
    if current_x < base_x:
        return "right"
    if current_x > base_x:
        return "left"
    return None


def is_outside_walking_boundary(
    current_x: float,
    base_x: float,
    tolerance: float,
) -> bool:
    """走路方案独立判断是否越出用户界限。"""
    return abs(current_x - base_x) > max(0.0, float(tolerance))


def walking_keepalive_direction(current_x: float, base_x: float) -> str:
    return walking_direction_to_base(current_x, base_x) or "right"


def next_walking_keepalive_interval() -> float:
    return random.uniform(*WALKING_KEEPALIVE_INTERVAL_RANGE)


def is_outside_anchor_band(current_x: float, base_x: float, tolerance: float) -> bool:
    """是否走出了用户配置的 base_x +/- tolerance 允许区域。"""
    return abs(current_x - base_x) > max(0.0, float(tolerance))


def protective_anchor_tolerance(boundary_tolerance: float) -> float:
    """在硬边界内提前触发回位，给连续撞击预留缓冲距离。"""
    return max(0.5, float(boundary_tolerance) * PROTECTIVE_BOUNDARY_RATIO)


def is_near_anchor(current_x: float, base_x: float, tolerance: float) -> bool:
    """是否处于允许范围的一半以内，触发一次拟人往返瞬移。"""
    return abs(current_x - base_x) <= max(0.0, float(tolerance)) * NEAR_ANCHOR_EXCURSION_RATIO


def outward_teleport_direction(current_x: float, base_x: float) -> str:
    """返回远离基准点的一侧；正好重合时随机选择一侧。"""
    if current_x < base_x:
        return "left"
    if current_x > base_x:
        return "right"
    return random.choice(("left", "right"))


def opposite_direction(direction: str) -> str:
    return "right" if direction == "left" else "left"


def requires_immediate_left_recovery(
    current_x: float,
    base_x: float,
    boundary_tolerance: float,
) -> bool:
    """左侧达到保护线即有掉层风险，必须绕过其它间隔和反向保护。"""
    return current_x <= base_x - max(0.0, float(boundary_tolerance))


def next_center_adjust_interval() -> float:
    """下一次瞬移修正的随机间隔。"""
    return random.uniform(*CENTER_ADJUST_INTERVAL_RANGE)


def updated_center_adjust_deadline(
    current_deadline: float,
    now: float,
    scheduled_triggered: bool,
) -> float:
    """只有定时事件本身才能推进定时器；越界回位不影响原定时间。"""
    if not scheduled_triggered:
        return current_deadline
    return now + next_center_adjust_interval()


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
        priority_left_recovery_tolerance: Optional[float] = None,
    ) -> bool:
        # 左侧几乎没有缓冲空间，向右回位不能被当作瞬移后的反向抖动拦截。
        if (
            priority_left_recovery_tolerance is not None
            and requires_immediate_left_recovery(
                current_x,
                base_x,
                priority_left_recovery_tolerance,
            )
        ):
            self._clear_guard()
            return True

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

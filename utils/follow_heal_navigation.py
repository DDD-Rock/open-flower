"""跟补模式的纯导航规则。

这里不依赖窗口截图或输入库，方便 Windows/macOS 两端保持同一套边界。
"""

import random
from typing import Optional, Tuple


ARRIVAL_TOLERANCE = 3.0
MOVEMENT_OBSERVED_TOLERANCE = 1.0
ANCHOR_BAND_TOLERANCE = 6.0
CENTER_ADJUST_INTERVAL_RANGE = (12.0, 15.0)
DEFAULT_CENTER_ADJUST_HOLD_MS = (200, 300)


def direction_to_base(current_x: float, base_x: float) -> Optional[str]:
    """返回回到基准 X 需要按的方向；已足够接近时返回 None。"""
    delta = current_x - base_x
    if abs(delta) <= ARRIVAL_TOLERANCE:
        return None
    return "left" if delta > 0 else "right"


def is_outside_anchor_band(current_x: float, base_x: float) -> bool:
    """是否走出了 base_x +/- 6 的允许区域。"""
    return abs(current_x - base_x) > ANCHOR_BAND_TOLERANCE


def direction_for_center_adjustment(current_x: float, base_x: float) -> str:
    """周期性小走：偏左/右则向中心走，正好在中心附近则向右小走。"""
    return direction_to_base(current_x, base_x) or "right"


def next_center_adjust_interval() -> float:
    """下一次站位修正的随机间隔。"""
    return random.uniform(*CENTER_ADJUST_INTERVAL_RANGE)


def normalize_center_adjust_hold_ms(min_ms: int, max_ms: int) -> Tuple[int, int]:
    """返回安全的周期性站位修正方向键按住时长范围。"""
    lower = max(50, min(int(min_ms), int(max_ms)))
    upper = min(1000, max(int(min_ms), int(max_ms)))
    return lower, upper

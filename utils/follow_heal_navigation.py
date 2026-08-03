"""跟补模式的纯导航规则。

这里不依赖窗口截图或输入库，方便 Windows/macOS 两端保持同一套边界。
"""

import random
from typing import Optional


CENTER_ADJUST_INTERVAL_RANGE = (10.0, 13.0)


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

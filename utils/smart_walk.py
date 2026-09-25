"""Pure helpers for the live-flower smart-walk feature."""

import random
from typing import Callable, Tuple


DEFAULT_SMART_WALK_INTERVAL = (15, 30)


def normalize_interval_range(
    minimum_minutes: int,
    maximum_minutes: int,
) -> Tuple[int, int]:
    """Clamp the configured range and keep its endpoints ordered."""
    minimum = max(1, min(1440, int(minimum_minutes)))
    maximum = max(1, min(1440, int(maximum_minutes)))
    if maximum < minimum:
        maximum = minimum
    return minimum, maximum


def next_smart_walk_deadline(
    now: float,
    minimum_minutes: int,
    maximum_minutes: int,
    choose: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return the next monotonic deadline using a randomized minute range."""
    minimum, maximum = normalize_interval_range(
        minimum_minutes,
        maximum_minutes,
    )
    return now + choose(float(minimum), float(maximum)) * 60.0


def smart_walk_direction(
    player_x: float,
    center_x: float,
) -> str:
    """Choose one short-walk direction from the starting side of center."""
    return "right" if float(player_x) < float(center_x) else "left"


def smart_walk_can_continue(
    direction: str,
    player_x: float,
    center_x: float,
    half_width: float,
) -> bool:
    """Allow crossing the center, stopping only at the selected boundary."""
    player = float(player_x)
    center = float(center_x)
    width = max(0.0, float(half_width))
    left = center - width
    right = center + width
    if direction == "right":
        return player < right
    if direction == "left":
        return player > left
    return False

"""Shared countdown calculations for both flower modes."""

import math
from datetime import datetime


def next_release_time(pressed_at: float, interval: float, early_by: float = 0.0) -> float:
    """Anchor the next release to the final successful Buff key press."""
    return pressed_at + max(0.0, interval - early_by)


def remaining_seconds(next_release: float, now: float) -> int:
    """Return a display countdown without dropping a second immediately."""
    return int(math.ceil(max(0.0, next_release - now)))


def format_release_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

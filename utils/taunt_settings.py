"""挑衅模式共用的毫秒范围及配置容错。"""

DEFAULT_TAUNT_INTERVAL_MS = (300, 500)
DEFAULT_TAUNT_HOLD_MS = (140, 180)
TAUNT_TIMING_VERSION = 2
MAX_TAUNT_TIMING_MS = 600000


def normalize_taunt_range(minimum, maximum, defaults):
    values = []
    for value, default in zip((minimum, maximum), defaults):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            value = default
        values.append(max(1, min(MAX_TAUNT_TIMING_MS, value)))
    return tuple(sorted(values))


def load_taunt_timing_ranges(settings):
    """升级旧默认节奏，保留用户已设置的自定义范围。"""
    try:
        version = int(settings.get("taunt_timing_version", 1))
    except (TypeError, ValueError):
        version = 1
    ranges = {}
    for prefix, defaults, legacy in (
        ("interval", DEFAULT_TAUNT_INTERVAL_MS, (800, 1200)),
        ("hold", DEFAULT_TAUNT_HOLD_MS, (60, 120)),
    ):
        values = normalize_taunt_range(
            settings.get(f"taunt_{prefix}_min_ms", defaults[0]),
            settings.get(f"taunt_{prefix}_max_ms", defaults[1]), defaults)
        ranges[prefix] = defaults if version < TAUNT_TIMING_VERSION and values == legacy else values
    return ranges

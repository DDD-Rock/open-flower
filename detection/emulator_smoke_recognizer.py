"""OCR predicates for the emulator social panel and its context menu."""

from __future__ import annotations

from detection.exp_recognizer import EXPRapidOCRRecognizer


def read_text(frame):
    """Use the OCR engine already shipped with the application."""
    payload = EXPRapidOCRRecognizer()._run_engine(frame)
    if not isinstance(payload, dict) or payload.get("code") != 100:
        return []
    return [
        block for block in (payload.get("data") or [])
        if isinstance(block, dict) and float(block.get("score") or 0) >= 0.75
        and isinstance(block.get("box"), list)
    ]


def center(block):
    points = block["box"]
    return (round(sum(point[0] for point in points) / len(points)),
            round(sum(point[1] for point in points) / len(points)))


def _clean(value):
    return "".join(str(value or "").split()).casefold()


def _name_matches(observed, expected):
    observed, expected = _clean(observed), _clean(expected)
    if observed == expected:
        return True
    # Downscaled stream OCR can drop a small run of glyphs; never accept
    # substitutions, and keep the deletion budget deliberately small.
    if not observed or len(observed) >= len(expected):
        return False
    missing = len(expected) - len(observed)
    if missing > 2:
        return False
    cursor = 0
    for char in observed:
        cursor = expected.find(char, cursor)
        if cursor < 0:
            return False
        cursor += 1
    return True


def is_social_panel(blocks):
    texts = {_clean(block.get("text")) for block in blocks}
    # The panel title is often missed while the friend rows are still being
    # refreshed.  The visible 好友 tab alone is sufficient evidence here;
    # 社交 remains accepted for OCR variants where the tab text is clearer.
    return "社交" in texts or "好友" in texts


def online_friend(blocks, name):
    """Return a unique online match; reject duplicate/offline and uncertain rows."""
    matches = []
    for block in blocks:
        if not _name_matches(block.get("text"), name):
            continue
        x, y = center(block)
        if any(
            0 <= center(status)[1] - y <= 65
            and abs(center(status)[0] - x) <= 230
            and _clean(status.get("text")).startswith("正在")
            for status in blocks
        ):
            matches.append((x, y))
    return matches[0] if len(matches) == 1 else None


def together_action(blocks):
    matches = [
        center(block) for block in blocks
        if _clean(block.get("text")).startswith("一起")
    ]
    return matches[0] if len(matches) == 1 else None

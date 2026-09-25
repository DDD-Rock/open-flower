"""Frame analysis for the experimental MuMu video-stream mode."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Tuple

import cv2
import numpy as np

from detection.minimap_monitor import MinimapMonitor
from detection.minimap_region_detector import detect_minimap_content_region


Rect = Tuple[int, int, int, int]


@dataclass
class EmulatorFrameAnalysis:
    """Recognition result for one decoded emulator frame."""

    game_state: str
    minimap_rect: Optional[Rect] = None
    minimap_image: Optional[np.ndarray] = None
    player_position: Optional[Tuple[int, int]] = None
    player_summary: str = ""
    title_rect: Optional[Rect] = None
    has_game_evidence: bool = False


def _neutral_bright_mask(image: np.ndarray) -> np.ndarray:
    channels = image.astype(np.int16)
    minimum = channels.min(axis=2)
    maximum = channels.max(axis=2)
    brightness = channels.sum(axis=2) // 3
    mask = (
        (brightness >= 168)
        & (minimum >= 140)
        & ((maximum - minimum) <= 90)
    ).astype(np.uint8) * 255
    return cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)


def _edge_support(mask: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    """Measure how much of a proposed rectangular border is actually bright."""
    if x2 <= x1 or y2 <= y1:
        return 0.0
    horizontal = max(x2 - x1 + 1, 1)
    vertical = max(y2 - y1 + 1, 1)
    top = np.count_nonzero(mask[max(0, y1 - 2) : y1 + 3, x1 : x2 + 1])
    bottom = np.count_nonzero(mask[y2 - 2 : y2 + 3, x1 : x2 + 1])
    left = np.count_nonzero(mask[y1 : y2 + 1, max(0, x1 - 2) : x1 + 3])
    right = np.count_nonzero(mask[y1 : y2 + 1, x2 - 2 : x2 + 3])
    return (top + bottom) / (horizontal * 10) + (left + right) / (vertical * 10)


def _horizontal_bands(
    mask: np.ndarray, left: int, top: int, right: int, bottom: int
) -> list[tuple[int, int]]:
    bands = []
    start = None
    last = -1
    width = max(right - left + 1, 1)
    for y in range(top, bottom + 1):
        bright_ratio = np.count_nonzero(mask[y, left : right + 1]) / width
        if bright_ratio >= 0.78:
            if start is None:
                start = y
            last = y
        elif start is not None:
            bands.append((start, last))
            start = None
    if start is not None:
        bands.append((start, last))
    return bands


def _detect_flexible_minimap_region(image: np.ndarray) -> Optional[Rect]:
    """Fallback for emulator maps whose minimap frame is unusually wide or tall."""
    image_height, image_width = image.shape[:2]
    search_width = min(image_width, max(420, round(image_width * 0.55)))
    search_height = min(image_height, max(320, round(image_height * 0.92)))
    search = image[:search_height, :search_width]
    mask = _neutral_bright_mask(search)
    closed = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), np.uint8),
        iterations=1,
    )
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    minimum_width = max(80, round(image_width * 0.055))
    maximum_width = round(image_width * 0.54)
    minimum_height = max(75, round(image_height * 0.075))
    maximum_height = round(image_height * 0.90)
    maximum_left = max(26, round(image_width * 0.018))
    maximum_top = max(70, round(image_height * 0.075))
    candidates = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if not minimum_width <= width <= maximum_width:
            continue
        if not minimum_height <= height <= maximum_height:
            continue
        if x > maximum_left or y > maximum_top:
            continue
        aspect = height / max(width, 1)
        if not 0.22 <= aspect <= 5.0:
            continue
        support = _edge_support(mask, x, y, x + width - 1, y + height - 1)
        if support < 0.95:
            continue
        candidates.append((support * 10000 + width * height * 0.01, x, y, width, height))

    for _, left, top, panel_width, panel_height in sorted(candidates, reverse=True):
        right = left + panel_width - 1
        bottom = top + panel_height - 1
        bands = _horizontal_bands(mask, left, top, right, bottom)
        minimum_title_height = max(18, round(image_height * 0.025))
        minimum_canvas_height = max(40, round(image_height * 0.05))
        divider = next(
            (
                band
                for band in reversed(bands)
                if band[0] >= top + minimum_title_height
                and bottom - band[1] >= minimum_canvas_height
            ),
            None,
        )
        if divider is None:
            continue
        bottom_border = next(
            (band for band in reversed(bands) if bottom - band[1] <= 4),
            None,
        )
        inset = max(3, round(panel_width * 0.012))
        content_top = divider[1] + 1
        content_bottom = bottom_border[0] if bottom_border else bottom - inset + 1
        content_width = panel_width - inset * 2
        content_height = content_bottom - content_top
        if content_width >= 70 and content_height >= minimum_canvas_height:
            return left + inset, content_top, content_width, content_height
    return None


def _is_plausible_minimap_canvas(image: np.ndarray, rect: Rect) -> bool:
    """Reject bright game scenery accidentally enclosed by unrelated UI borders."""
    x, y, width, height = rect
    crop = image[y : y + height, x : x + width]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bright_ratio = float(np.mean(gray >= 220))
    edge_ratio = float(np.mean(cv2.Canny(gray, 50, 120) > 0))
    # Real minimaps contain platforms, icons, or terrain texture. Hidden-map
    # scenes can leave a bright sky rectangle between the title strip and the
    # chat panel which satisfies the geometric frame detector but has almost
    # no map detail.
    if bright_ratio >= 0.72 and edge_ratio < 0.06:
        return False
    return True


def detect_emulator_minimap_region(image: np.ndarray) -> Optional[Rect]:
    """Locate a minimap while preserving the proven PC detector as first choice."""
    region = detect_minimap_content_region(image)
    if region is not None and _is_plausible_minimap_canvas(image, region):
        return region
    region = _detect_flexible_minimap_region(image)
    if region is not None and _is_plausible_minimap_canvas(image, region):
        return region
    return None


def detect_emulator_map_title_region(image: np.ndarray) -> Optional[Rect]:
    """Detect the upper-left white map-name strip used by hidden-minimap maps."""
    if image is None or image.ndim != 3:
        return None
    image_height, image_width = image.shape[:2]
    search_width = min(image_width, max(360, round(image_width * 0.48)))
    search_height = min(image_height, max(180, round(image_height * 0.32)))
    mask = _neutral_bright_mask(image[:search_height, :search_width])
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((5, 11), np.uint8),
        iterations=1,
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    maximum_left = max(28, round(image_width * 0.02))
    maximum_top = max(80, round(image_height * 0.09))
    candidates = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if x > maximum_left or y > maximum_top:
            continue
        if width < max(90, round(image_width * 0.07)):
            continue
        if not max(18, round(image_height * 0.018)) <= height <= round(image_height * 0.18):
            continue
        if width / max(height, 1) < 2.0:
            continue
        support = _edge_support(mask, x, y, x + width - 1, y + height - 1)
        if support >= 0.75:
            candidates.append((support * 1000 + width - y * 2, x, y, width, height))
    if candidates:
        _, x, y, width, height = max(candidates)
        return x, y, width, height

    # In a hidden-map scene the title strip is gray rather than white. Its
    # thin top/bottom borders remain stable, so pair long horizontal edges
    # anchored at the upper-left instead of relying on fill color.
    edge_width = min(image_width, max(360, round(image_width * 0.30)))
    edge_height = min(image_height, max(120, round(image_height * 0.15)))
    gray = cv2.cvtColor(image[:edge_height, :edge_width], cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 100)
    minimum_line_width = max(90, round(image_width * 0.07))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(45, minimum_line_width // 3),
        minLineLength=minimum_line_width,
        maxLineGap=12,
    )
    if lines is None:
        return None
    horizontal = []
    for raw_line in lines[:, 0]:
        x1, y1, x2, y2 = (int(value) for value in raw_line)
        if x2 < x1:
            x1, x2 = x2, x1
            y1, y2 = y2, y1
        if abs(y2 - y1) <= 2 and x1 <= max(16, round(image_width * 0.008)):
            horizontal.append((x1, round((y1 + y2) / 2), x2))
    maximum_top = max(12, round(image_height * 0.012))
    top_lines = [line for line in horizontal if line[1] <= maximum_top]
    if not top_lines:
        return None
    top = max(top_lines, key=lambda line: line[2] - line[0])
    top_width = top[2] - top[0] + 1
    bottom_lines = [
        line
        for line in horizontal
        if top[1] + max(20, round(image_height * 0.018)) <= line[1]
        <= top[1] + max(90, round(image_height * 0.075))
        and line[2] - line[0] + 1 >= top_width * 0.50
    ]
    if not bottom_lines:
        return None
    bottom = min(bottom_lines, key=lambda line: line[1])
    right = min(top[2], bottom[2])
    return top[0], top[1], right - top[0] + 1, bottom[1] - top[1] + 1


def _find_emulator_player_position(
    minimap: np.ndarray,
) -> tuple[Optional[Tuple[int, int]], str]:
    """Find the player while rejecting dull-yellow map decorations."""
    if minimap is None or minimap.ndim != 3 or minimap.size == 0:
        return None, "小地图图像无效"

    # The player's marker has a stable pure-yellow core. Keep this path small:
    # it avoids HSV conversion and the tolerant fallback on almost every frame.
    core_mask = cv2.inRange(
        minimap,
        np.array([0, 200, 200], dtype=np.uint8),
        np.array([45, 255, 255], dtype=np.uint8),
    )
    count, _, stats, centroids = cv2.connectedComponentsWithStats(core_mask, 8)
    cores = []
    for index in range(1, count):
        _, _, width, height, area = stats[index]
        if 1 <= area <= 180 and width <= 20 and height <= 20:
            x, y = centroids[index]
            cores.append((float(x), float(y), int(area)))

    cluster_radius = max(5.0, minimap.shape[1] * 0.025)
    clusters = []
    for x, y, area in cores:
        target = next(
            (
                cluster
                for cluster in clusters
                if (x - cluster[0]) ** 2 + (y - cluster[1]) ** 2
                <= cluster_radius**2
            ),
            None,
        )
        if target is None:
            clusters.append([x, y, area])
            continue
        total = target[2] + area
        target[0] = (target[0] * target[2] + x * area) / total
        target[1] = (target[1] * target[2] + y * area) / total
        target[2] = total

    if len(clusters) == 1:
        x, y, area = clusters[0]
        point = (int(round(x)), int(round(y)))
        return point, f"玩家黄点核心 x={x:.1f}, y={y:.1f}，核心像素={area}"

    # Only pay for the complete detector when the cheap core path cannot
    # identify exactly one marker (for example during anti-aliased frames).
    position, summary = MinimapMonitor.find_player_position_in_image(minimap)
    if position is not None:
        px, py = position
        verified = next(
            (
                cluster
                for cluster in clusters
                if (px - cluster[0]) ** 2 + (py - cluster[1]) ** 2
                <= (cluster_radius * 1.5) ** 2
            ),
            None,
        )
        if verified is not None:
            return position, summary + "；已由纯黄色核心复核"
        return None, f"黄色候选缺少纯色核心，已拒绝；{summary}"
    return None, summary


def analyze_emulator_frame(frame: np.ndarray) -> EmulatorFrameAnalysis:
    """Analyze one current frame without carrying temporal state."""
    if frame is None or frame.ndim != 3 or frame.size == 0:
        return EmulatorFrameAnalysis(game_state="not_in_game")

    rect = detect_emulator_minimap_region(frame)
    if rect is not None:
        x, y, width, height = rect
        minimap = frame[y : y + height, x : x + width].copy()
        player, summary = _find_emulator_player_position(minimap)
        return EmulatorFrameAnalysis(
            game_state="in_game",
            minimap_rect=rect,
            minimap_image=minimap,
            player_position=player,
            player_summary=summary,
            has_game_evidence=True,
        )

    title_rect = detect_emulator_map_title_region(frame)
    if title_rect is not None:
        return EmulatorFrameAnalysis(
            game_state="in_game",
            player_summary="当前地图未显示小地图画布",
            title_rect=title_rect,
            has_game_evidence=True,
        )
    return EmulatorFrameAnalysis(
        game_state="not_in_game",
        player_summary="未检测到小地图或地图名称条",
    )


def analyze_known_emulator_minimap(
    frame: np.ndarray, rect: Rect
) -> EmulatorFrameAnalysis:
    """Fast path between full frame searches while the minimap geometry is stable."""
    if frame is None or frame.ndim != 3 or frame.size == 0:
        return EmulatorFrameAnalysis(game_state="not_in_game")
    x, y, width, height = rect
    frame_height, frame_width = frame.shape[:2]
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > frame_width
        or y + height > frame_height
    ):
        return EmulatorFrameAnalysis(game_state="not_in_game")
    minimap = frame[y : y + height, x : x + width].copy()
    player, summary = _find_emulator_player_position(minimap)
    return EmulatorFrameAnalysis(
        game_state="in_game",
        minimap_rect=rect,
        minimap_image=minimap,
        player_position=player,
        player_summary=summary,
        has_game_evidence=True,
    )


def apply_game_state_grace(
    analysis: EmulatorFrameAnalysis,
    last_evidence_at: Optional[float],
    now: float,
) -> tuple[EmulatorFrameAnalysis, Optional[float]]:
    """Apply the agreed 5/30-second loss tolerance to visual game evidence."""
    if analysis.has_game_evidence:
        return analysis, now
    if last_evidence_at is None:
        return analysis, None
    missing_for = max(0.0, now - last_evidence_at)
    if missing_for <= 5.0:
        return replace(analysis, game_state="in_game"), last_evidence_at
    if missing_for <= 30.0:
        return replace(analysis, game_state="loading"), last_evidence_at
    return replace(analysis, game_state="not_in_game"), last_evidence_at

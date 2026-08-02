"""跨平台地图标注模型与小地图视觉匹配。

字段名保持和 macOS ``MapTopology`` 的 Codable JSON 一致，使两端导出的
地图文件可以直接互相导入。
"""

from __future__ import annotations

import base64
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import cv2
    import numpy as np
except ImportError:  # 数据模型和文件导入不应强依赖图像运行库。
    cv2 = None
    np = None


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    value = float(value)
    return min(max(value, lower), upper) if math.isfinite(value) else lower


def _uuid(value: Optional[str] = None) -> str:
    try:
        return str(uuid.UUID(str(value))) if value else str(uuid.uuid4())
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid4())


@dataclass(frozen=True)
class NormalizedMapPoint:
    x: float
    y: float

    def __post_init__(self):
        object.__setattr__(self, "x", _clamp(self.x))
        object.__setattr__(self, "y", _clamp(self.y))

    @classmethod
    def from_pixel(cls, point: tuple[float, float], size: tuple[int, int]):
        width, height = size
        return cls(
            point[0] / width if width > 0 else 0,
            point[1] / height if height > 0 else 0,
        )

    def to_pixel(self, size: tuple[int, int]) -> tuple[float, float]:
        return self.x * size[0], self.y * size[1]

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        return cls(value.get("x", 0), value.get("y", 0))


@dataclass
class MapPlatform:
    points: list[NormalizedMapPoint]
    id: str = field(default_factory=_uuid)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "points": [point.to_dict() for point in self.points]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        return cls(
            id=_uuid(value.get("id")),
            points=[NormalizedMapPoint.from_dict(item) for item in value.get("points", [])],
        )


@dataclass
class MapRope:
    x: float
    top_y: float
    bottom_y: float
    id: str = field(default_factory=_uuid)

    def __post_init__(self):
        top, bottom = sorted((_clamp(self.top_y), _clamp(self.bottom_y)))
        self.x = _clamp(self.x)
        self.top_y = top
        self.bottom_y = bottom

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "x": self.x,
            "topY": self.top_y,
            "bottomY": self.bottom_y,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        return cls(
            id=_uuid(value.get("id")),
            x=value.get("x", 0),
            top_y=value.get("topY", 0),
            bottom_y=value.get("bottomY", 0),
        )


@dataclass
class MapPortal:
    point: NormalizedMapPoint
    type: str = "normal"
    destination_map_name: Optional[str] = None
    destination_portal_id: Optional[str] = None
    id: str = field(default_factory=_uuid)

    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "point": self.point.to_dict(), "type": self.type}
        if self.destination_map_name is not None:
            result["destinationMapName"] = self.destination_map_name
        if self.destination_portal_id is not None:
            result["destinationPortalID"] = self.destination_portal_id
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        return cls(
            id=_uuid(value.get("id")),
            point=NormalizedMapPoint.from_dict(value.get("point") or {}),
            type=str(value.get("type") or "normal"),
            destination_map_name=value.get("destinationMapName"),
            destination_portal_id=value.get("destinationPortalID"),
        )


@dataclass
class MapTraversalConnection:
    kind: str
    from_platform_id: str
    to_platform_id: str
    start_point: NormalizedMapPoint
    landing_point: NormalizedMapPoint
    direction: str = "neutral"
    key_hold_milliseconds: int = 300
    landing_tolerance: float = 0.06
    is_enabled: bool = True
    is_verified: bool = False
    success_count: int = 0
    failure_count: int = 0
    id: str = field(default_factory=_uuid)

    def __post_init__(self):
        self.key_hold_milliseconds = min(max(int(self.key_hold_milliseconds), 50), 2000)
        self.landing_tolerance = _clamp(self.landing_tolerance, 0.01, 0.2)
        self.success_count = max(0, int(self.success_count))
        self.failure_count = max(0, int(self.failure_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "fromPlatformID": self.from_platform_id,
            "toPlatformID": self.to_platform_id,
            "startPoint": self.start_point.to_dict(),
            "landingPoint": self.landing_point.to_dict(),
            "direction": self.direction,
            "keyHoldMilliseconds": self.key_hold_milliseconds,
            "landingTolerance": self.landing_tolerance,
            "isEnabled": self.is_enabled,
            "isVerified": self.is_verified,
            "successCount": self.success_count,
            "failureCount": self.failure_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        return cls(
            id=_uuid(value.get("id")),
            kind=str(value.get("kind") or "drop"),
            from_platform_id=_uuid(value.get("fromPlatformID")),
            to_platform_id=_uuid(value.get("toPlatformID")),
            start_point=NormalizedMapPoint.from_dict(value.get("startPoint") or {}),
            landing_point=NormalizedMapPoint.from_dict(value.get("landingPoint") or {}),
            direction=str(value.get("direction") or "neutral"),
            key_hold_milliseconds=value.get("keyHoldMilliseconds", 300),
            landing_tolerance=value.get("landingTolerance", 0.06),
            is_enabled=bool(value.get("isEnabled", True)),
            is_verified=bool(value.get("isVerified", False)),
            success_count=value.get("successCount", 0),
            failure_count=value.get("failureCount", 0),
        )


@dataclass
class MapTopology:
    map_name: str
    reference_width: int
    reference_height: int
    version: int = 4
    visual_signature: Optional[list[int]] = None
    reference_bgr: Optional[bytes] = None
    platforms: list[MapPlatform] = field(default_factory=list)
    ropes: list[MapRope] = field(default_factory=list)
    portals: list[MapPortal] = field(default_factory=list)
    traversal_connections: list[MapTraversalConnection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "version": 4,
            "mapName": self.map_name,
            "referenceWidth": int(self.reference_width),
            "referenceHeight": int(self.reference_height),
            "platforms": [item.to_dict() for item in self.platforms],
            "ropes": [item.to_dict() for item in self.ropes],
            "portals": [item.to_dict() for item in self.portals],
            "traversalConnections": [
                item.to_dict() for item in self.traversal_connections
            ],
        }
        if self.visual_signature is not None:
            result["visualSignature"] = [int(value) & 0xFF for value in self.visual_signature]
        if self.reference_bgr is not None:
            result["referenceBGR"] = base64.b64encode(self.reference_bgr).decode("ascii")
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        reference = value.get("referenceBGR")
        try:
            reference_bgr = base64.b64decode(reference) if reference else None
        except (ValueError, TypeError):
            reference_bgr = None
        return cls(
            version=4,
            map_name=str(value.get("mapName") or ""),
            reference_width=int(value.get("referenceWidth") or 0),
            reference_height=int(value.get("referenceHeight") or 0),
            visual_signature=(
                [int(item) & 0xFF for item in value.get("visualSignature", [])]
                if value.get("visualSignature") is not None
                else None
            ),
            reference_bgr=reference_bgr,
            platforms=[MapPlatform.from_dict(item) for item in value.get("platforms", [])],
            ropes=[MapRope.from_dict(item) for item in value.get("ropes", [])],
            portals=[MapPortal.from_dict(item) for item in value.get("portals", [])],
            traversal_connections=[
                MapTraversalConnection.from_dict(item)
                for item in value.get("traversalConnections", [])
            ],
        )


class PlatformTraceBuilder:
    """把玩家往返移动的黄点样本合并成稳定的平台折线。"""

    @classmethod
    def build_polyline(
        cls,
        samples: Iterable[tuple[float, float]],
        canvas_size: tuple[int, int],
        bucket_width: float = 1.0,
        simplify_tolerance: float = 1.2,
    ) -> list[NormalizedMapPoint]:
        width, height = canvas_size
        valid = [
            (float(x), float(y))
            for x, y in samples
            if math.isfinite(x)
            and math.isfinite(y)
            and 0 <= x < width
            and 0 <= y < height
        ]
        if width <= 0 or height <= 0 or len(valid) < 5:
            return []
        bucket_width = max(bucket_width, 0.5)
        buckets: dict[int, list[tuple[float, float]]] = {}
        for point in valid:
            buckets.setdefault(round(point[0] / bucket_width), []).append(point)
        merged = [
            (
                cls._median(sorted(point[0] for point in buckets[key])),
                cls._median(sorted(point[1] for point in buckets[key])),
            )
            for key in sorted(buckets)
        ]
        if len(merged) < 3:
            return []
        runs: list[list[tuple[float, float]]] = []
        # 和 macOS 保持一致：允许正常移动或偶发漏检造成的短缺口，但保留上限，
        # 避免把相邻的不同平台错误连接起来。
        maximum_horizontal_gap = max(10.0, min(18.0, width * 0.10))
        maximum_vertical_gap = max(8.0, min(14.0, height * 0.12))
        current = [merged[0]]
        for point in merged[1:]:
            previous = current[-1]
            if (
                point[0] - previous[0] <= maximum_horizontal_gap
                and abs(point[1] - previous[1]) <= maximum_vertical_gap
            ):
                current.append(point)
            else:
                runs.append(current)
                current = [point]
        runs.append(current)
        best = max(
            runs,
            key=lambda run: run[-1][0] - run[0][0] + len(run) * 0.25,
            default=[],
        )
        if len(best) < 3:
            return []
        smoothed = []
        for index, point in enumerate(best):
            ys = sorted(
                item[1]
                for item in best[max(0, index - 1) : min(len(best), index + 2)]
            )
            smoothed.append((point[0], cls._median(ys)))
        simplified = cls._simplify(smoothed, simplify_tolerance)
        return [
            NormalizedMapPoint.from_pixel(point, canvas_size)
            for point in simplified
        ] if len(simplified) >= 2 else []

    @classmethod
    def _simplify(cls, points, tolerance):
        if len(points) <= 2:
            return points
        first, last = points[0], points[-1]
        maximum, split = 0.0, 0
        for index in range(1, len(points) - 1):
            distance = cls._perpendicular_distance(points[index], first, last)
            if distance > maximum:
                maximum, split = distance, index
        if maximum <= tolerance:
            return [first, last]
        left = cls._simplify(points[: split + 1], tolerance)
        right = cls._simplify(points[split:], tolerance)
        return left[:-1] + right

    @staticmethod
    def _perpendicular_distance(point, start, end):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 0.0001:
            return math.hypot(point[0] - start[0], point[1] - start[1])
        ratio = min(
            max(((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared, 0),
            1,
        )
        return math.hypot(
            point[0] - (start[0] + ratio * dx),
            point[1] - (start[1] + ratio * dy),
        )

    @staticmethod
    def _median(values):
        middle = len(values) // 2
        return (
            (values[middle - 1] + values[middle]) / 2
            if len(values) % 2 == 0
            else values[middle]
        )


class RopeTraceBuilder:
    @staticmethod
    def build_rope(
        samples: Iterable[tuple[float, float]],
        canvas_size: tuple[int, int],
    ) -> Optional[MapRope]:
        width, height = canvas_size
        valid = sorted(
            (
                (float(x), float(y))
                for x, y in samples
                if math.isfinite(x)
                and math.isfinite(y)
                and 0 <= x < width
                and 0 <= y < height
            ),
            key=lambda point: point[1],
        )
        if width <= 0 or height <= 0 or len(valid) < 5:
            return None
        xs = sorted(point[0] for point in valid)
        ys = [point[1] for point in valid]
        x = xs[len(xs) // 2]
        top = ys[len(ys) // 20]
        bottom = ys[len(ys) - 1 - len(ys) // 20]
        if bottom - top < max(5, height * 0.025):
            return None
        return MapRope(x / width, top / height, bottom / height)


class MapTopologyValidator:
    @classmethod
    def messages(cls, topology: MapTopology) -> list[str]:
        messages = []
        if not topology.platforms:
            messages.append("还没有标注平台")
        if not topology.ropes:
            messages.append("还没有标注绳索")
        for index, platform in enumerate(topology.platforms):
            if len(platform.points) < 2:
                messages.append(f"平台 P{index + 1} 至少需要两个端点")
            elif not any(
                math.hypot(end.x - start.x, end.y - start.y) >= 0.015
                for start, end in zip(platform.points, platform.points[1:])
            ):
                messages.append(f"平台 P{index + 1} 长度太短")
        for index, rope in enumerate(topology.ropes):
            if rope.bottom_y - rope.top_y < 0.025:
                messages.append(f"绳索 R{index + 1} 长度太短")
            if not any(cls._platform_intersects_rope(item, rope) for item in topology.platforms):
                messages.append(f"绳索 R{index + 1} 没有连接任何平台")
        for index, portal in enumerate(topology.portals):
            near_platform = any(
                cls._point_segment_distance(portal.point, start, end) <= 0.07
                for platform in topology.platforms
                for start, end in zip(platform.points, platform.points[1:])
            )
            near_rope = any(
                abs(portal.point.x - rope.x) <= 0.05
                and rope.top_y - 0.05 <= portal.point.y <= rope.bottom_y + 0.05
                for rope in topology.ropes
            )
            if not near_platform and not near_rope:
                messages.append(
                    f"传送点 T{index + 1} 不在平台或绳索可到达范围内"
                )
        platform_ids = {item.id for item in topology.platforms}
        for index, connection in enumerate(topology.traversal_connections):
            prefix = "J" if connection.kind == "jump" else "D"
            if (
                connection.from_platform_id not in platform_ids
                or connection.to_platform_id not in platform_ids
            ):
                messages.append(f"连接 {prefix}{index + 1} 引用的平台已不存在")
            if connection.from_platform_id == connection.to_platform_id:
                messages.append(
                    f"连接 {prefix}{index + 1} 的起点和落点不能是同一平台"
                )
            if (
                connection.kind == "drop"
                and connection.landing_point.y
                <= connection.start_point.y + 0.02
            ):
                messages.append(f"下落连接 D{index + 1} 的落点必须在起点下方")
        return messages

    @staticmethod
    def _point_segment_distance(point, start, end):
        dx, dy = end.x - start.x, end.y - start.y
        length_squared = dx * dx + dy * dy
        if length_squared <= 0.000001:
            return math.hypot(point.x - start.x, point.y - start.y)
        ratio = min(
            max(
                ((point.x - start.x) * dx + (point.y - start.y) * dy)
                / length_squared,
                0,
            ),
            1,
        )
        return math.hypot(
            point.x - (start.x + ratio * dx),
            point.y - (start.y + ratio * dy),
        )

    @staticmethod
    def _platform_intersects_rope(platform, rope):
        for start, end in zip(platform.points, platform.points[1:]):
            if not min(start.x, end.x) - 0.05 <= rope.x <= max(start.x, end.x) + 0.05:
                continue
            ratio = (
                min(max((rope.x - start.x) / (end.x - start.x), 0), 1)
                if abs(end.x - start.x) >= 0.0001
                else 0.5
            )
            y = start.y + (end.y - start.y) * ratio
            if rope.top_y - 0.05 <= y <= rope.bottom_y + 0.05:
                return True
        return False


class MinimapVisualMatcher:
    COLUMNS = 24
    ROWS = 16
    MINIMUM_MATCH_PERCENTAGE = 60.0

    @classmethod
    def signature(cls, image: np.ndarray) -> list[int]:
        if cv2 is None or np is None:
            raise RuntimeError("小地图视觉匹配需要安装 OpenCV 和 NumPy")
        if image is None or image.ndim != 3 or image.size == 0:
            return []
        height, width = image.shape[:2]
        result = []
        for row in range(cls.ROWS):
            for column in range(cls.COLUMNS):
                x0 = column * width // cls.COLUMNS
                x1 = max(x0 + 1, (column + 1) * width // cls.COLUMNS)
                y0 = row * height // cls.ROWS
                y1 = max(y0 + 1, (row + 1) * height // cls.ROWS)
                cell = image[y0:min(y1, height), x0:min(x1, width)]
                spread = cell.max(axis=2) - cell.min(axis=2)
                gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                stable = gray[spread <= 90]
                result.append(int(stable.max()) if stable.size else 0)
        return result

    @classmethod
    def distance(cls, lhs: Iterable[int], rhs: Iterable[int]) -> float:
        lhs_values, rhs_values = list(lhs), list(rhs)
        if len(lhs_values) != cls.COLUMNS * cls.ROWS or len(rhs_values) != len(lhs_values):
            return math.inf
        differences = sorted(abs(a - b) for a, b in zip(lhs_values, rhs_values))
        del differences[len(differences) * 94 // 100 :]
        return sum(differences) / len(differences)

    @classmethod
    def _structural_mismatch(cls, lhs: list[int], rhs: list[int], radius: int) -> float:
        threshold = 35

        def directed(source, target):
            unmatched = total = 0
            for row in range(cls.ROWS):
                for column in range(cls.COLUMNS):
                    if source[row * cls.COLUMNS + column] < threshold:
                        continue
                    total += 1
                    found = any(
                        target[y * cls.COLUMNS + x] >= threshold
                        for y in range(max(0, row - radius), min(cls.ROWS, row + radius + 1))
                        for x in range(max(0, column - radius), min(cls.COLUMNS, column + radius + 1))
                    )
                    unmatched += int(not found)
            return unmatched, total

        forward = directed(lhs, rhs)
        backward = directed(rhs, lhs)
        total = forward[1] + backward[1]
        return (forward[0] + backward[0]) / total if total else 0.0

    @classmethod
    def _tolerant_distance(cls, lhs: list[int], rhs: list[int]) -> float:
        def directed(source, target):
            total = 0
            for row in range(cls.ROWS):
                for column in range(cls.COLUMNS):
                    value = source[row * cls.COLUMNS + column]
                    total += min(
                        abs(value - target[y * cls.COLUMNS + x])
                        for y in range(max(0, row - 1), min(cls.ROWS, row + 2))
                        for x in range(max(0, column - 1), min(cls.COLUMNS, column + 2))
                    )
            return total / len(source)

        return (directed(lhs, rhs) + directed(rhs, lhs)) / 2

    @classmethod
    def comparison(cls, lhs: Iterable[int], rhs: Iterable[int]) -> dict[str, Any]:
        lhs_values, rhs_values = list(lhs), list(rhs)
        if len(lhs_values) != cls.COLUMNS * cls.ROWS or len(rhs_values) != len(lhs_values):
            return {"similarityPercentage": 0.0, "isMatch": False}

        candidates = []
        for distance, structure, tolerant in (
            (cls.distance(lhs_values, rhs_values), cls._structural_mismatch(lhs_values, rhs_values, 0), False),
            (cls._tolerant_distance(lhs_values, rhs_values), cls._structural_mismatch(lhs_values, rhs_values, 1), True),
        ):
            penalty = min(max(distance / 32, 0), 1) * 0.45 + min(max(structure, 0), 1) * 0.55
            candidates.append((penalty, distance, structure, tolerant))
        penalty, distance, structure, tolerant = min(candidates)
        similarity = round(min(max((1 - penalty) * 100, 0), 100), 1)
        return {
            "similarityPercentage": similarity,
            "isMatch": similarity >= cls.MINIMUM_MATCH_PERCENTAGE,
            "appearanceDistance": distance,
            "structuralMismatch": structure,
            "usesScaleTolerance": tolerant,
        }


class MapTransferService:
    FORMAT_VERSION = 1

    @classmethod
    def export_data(cls, maps: list[MapTopology]) -> bytes:
        validated = cls._validate(maps)
        # JSONEncoder's default Date representation is seconds since 2001-01-01.
        document = {
            "formatVersion": cls.FORMAT_VERSION,
            "exportedAt": time.time() - 978307200,
            "maps": [item.to_dict() for item in validated],
        }
        return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

    @classmethod
    def import_data(cls, data: bytes | str) -> list[MapTopology]:
        try:
            root = json.loads(data)
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            raise ValueError("无法识别该地图文件") from error
        if isinstance(root, dict) and "formatVersion" in root:
            if int(root["formatVersion"]) > cls.FORMAT_VERSION:
                raise ValueError(f"不支持的地图文件格式版本 {root['formatVersion']}")
            values = root.get("maps")
        elif isinstance(root, dict) and "schemaVersion" in root:
            if int(root["schemaVersion"]) > 1:
                raise ValueError(f"不支持的地图库版本 {root['schemaVersion']}")
            values = root.get("maps")
        elif isinstance(root, list):
            values = root
        else:
            raise ValueError("无法识别该地图文件")
        if not isinstance(values, list):
            raise ValueError("地图文件中没有可导入的地图")
        return cls._validate([MapTopology.from_dict(item) for item in values])

    @classmethod
    def load(cls, path: str | Path) -> list[MapTopology]:
        return cls.import_data(Path(path).read_bytes())

    @classmethod
    def save(cls, path: str | Path, maps: list[MapTopology]):
        Path(path).write_bytes(cls.export_data(maps))

    @staticmethod
    def merge(imported: list[MapTopology], existing: list[MapTopology]):
        merged = list(existing)
        indexes = {item.map_name.strip().casefold(): index for index, item in enumerate(merged)}
        added = replaced = 0
        for item in imported:
            key = item.map_name.strip().casefold()
            if key in indexes:
                item.map_name = merged[indexes[key]].map_name
                merged[indexes[key]] = item
                replaced += 1
            else:
                indexes[key] = len(merged)
                merged.append(item)
                added += 1
        return merged, added, replaced

    @staticmethod
    def _validate(maps: list[MapTopology]) -> list[MapTopology]:
        if not maps:
            raise ValueError("地图文件中没有可导入的地图")
        names = set()
        for index, item in enumerate(maps):
            item.map_name = item.map_name.strip()
            if not item.map_name:
                raise ValueError(f"地图文件中的第 {index + 1} 张地图没有名称")
            if item.reference_width <= 0 or item.reference_height <= 0:
                raise ValueError(f"地图“{item.map_name}”的参考尺寸无效")
            key = item.map_name.casefold()
            if key in names:
                raise ValueError(f"地图文件中存在重复名称“{item.map_name}”")
            names.add(key)
        return maps

"""由地图标注生成路径图，并进行带动作代价的最短路径规划。"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from models.map_topology import MapTopology, NormalizedMapPoint


@dataclass(frozen=True)
class NavigationNode:
    id: str
    kind: str
    point: NormalizedMapPoint
    reference_id: str
    map_name: str = ""


@dataclass(frozen=True)
class NavigationEdge:
    id: str
    source_id: str
    destination_id: str
    kind: str
    cost: float
    direction: str = "neutral"
    key_hold_milliseconds: int = 250
    landing_tolerance: float = 0.07


@dataclass
class MapNavigationGraph:
    nodes: list[NavigationNode] = field(default_factory=list)
    edges: list[NavigationEdge] = field(default_factory=list)

    def outgoing(self, node_id: str):
        return [edge for edge in self.edges if edge.source_id == node_id]

    def node(self, node_id: str):
        return next((item for item in self.nodes if item.id == node_id), None)

    def nearest_node(
        self,
        point: NormalizedMapPoint,
        maximum_distance=0.12,
        map_name=None,
    ):
        nodes = [
            item
            for item in self.nodes
            if map_name is None or item.map_name == map_name
        ]
        candidate = min(
            nodes,
            key=lambda item: math.hypot(item.point.x - point.x, item.point.y - point.y),
            default=None,
        )
        if candidate is None:
            return None
        distance = math.hypot(candidate.point.x - point.x, candidate.point.y - point.y)
        return candidate if distance <= maximum_distance else None


class MapNavigationGraphBuilder:
    WALK_COST = 1.0
    CLIMB_COST = 1.8
    DROP_COST = 2.2
    PORTAL_COST = 2.5

    @classmethod
    def build(cls, topology: MapTopology | list[MapTopology]) -> MapNavigationGraph:
        maps = topology if isinstance(topology, list) else [topology]
        graph = MapNavigationGraph()
        portal_nodes = {}
        for item in maps:
            cls._append_map(graph, item, portal_nodes)
        for item in maps:
            for portal in item.portals:
                source = portal_nodes.get(portal.id)
                destination = portal_nodes.get(portal.destination_portal_id or "")
                if (
                    source is not None
                    and destination is not None
                    and portal.destination_map_name == destination.map_name
                ):
                    graph.edges.append(
                        NavigationEdge(
                            f"portal-edge:{portal.id}",
                            source.id,
                            destination.id,
                            "portal",
                            cls.PORTAL_COST,
                        )
                    )
        return graph

    @classmethod
    def _append_map(cls, graph, topology, portal_nodes):
        platform_nodes = {}
        for platform in topology.platforms:
            nodes = []
            expanded = cls._expanded_platform_points(platform.points)
            for index, point in enumerate(expanded):
                node = NavigationNode(
                    f"{topology.map_name}:platform:{platform.id}:{index}",
                    "platform",
                    point,
                    platform.id,
                    topology.map_name,
                )
                graph.nodes.append(node)
                nodes.append(node)
            platform_nodes[platform.id] = nodes
            for first, second in zip(nodes, nodes[1:]):
                distance = math.hypot(
                    first.point.x - second.point.x,
                    first.point.y - second.point.y,
                )
                cls._bidirectional(
                    graph,
                    first,
                    second,
                    "walk",
                    max(0.05, distance / 0.1) * cls.WALK_COST,
                )

        for rope in topology.ropes:
            steps = max(1, math.ceil((rope.bottom_y - rope.top_y) / 0.045))
            rope_nodes = [
                NavigationNode(
                    f"{topology.map_name}:rope:{rope.id}:{index}",
                    "rope",
                    NormalizedMapPoint(
                        rope.x,
                        rope.top_y
                        + (rope.bottom_y - rope.top_y) * index / steps,
                    ),
                    rope.id,
                    topology.map_name,
                )
                for index in range(steps + 1)
            ]
            graph.nodes.extend(rope_nodes)
            for first, second in zip(rope_nodes, rope_nodes[1:]):
                cls._bidirectional(
                    graph,
                    first,
                    second,
                    "climb",
                    max(0.05, second.point.y - first.point.y)
                    * 10
                    * cls.CLIMB_COST,
                )
            for rope_node in (rope_nodes[0], rope_nodes[-1]):
                platform_node = cls._nearest_platform_node(
                    [node for nodes in platform_nodes.values() for node in nodes],
                    rope_node.point,
                    horizontal=0.08,
                    vertical=0.08,
                )
                if platform_node is not None:
                    cls._bidirectional(
                        graph,
                        platform_node,
                        rope_node,
                        "approach_rope",
                        1.5,
                    )

        for portal in topology.portals:
            node = NavigationNode(
                f"{topology.map_name}:portal:{portal.id}",
                "portal",
                portal.point,
                portal.id,
                topology.map_name,
            )
            graph.nodes.append(node)
            portal_nodes[portal.id] = node
            platform_node = cls._nearest_platform_node(
                [item for nodes in platform_nodes.values() for item in nodes],
                portal.point,
                horizontal=0.1,
                vertical=0.08,
            )
            if platform_node is not None:
                cls._bidirectional(graph, platform_node, node, "approach", 1.0)

        cls._add_drop_edges(graph, topology, platform_nodes)
        cls._add_saved_connections(graph, topology, platform_nodes)

    @staticmethod
    def _expanded_platform_points(points):
        expanded = []
        for start, end in zip(points, points[1:]):
            distance = math.hypot(end.x - start.x, end.y - start.y)
            steps = max(1, math.ceil(distance / 0.04))
            for index in range(steps):
                ratio = index / steps
                candidate = NormalizedMapPoint(
                    start.x + (end.x - start.x) * ratio,
                    start.y + (end.y - start.y) * ratio,
                )
                if not expanded or candidate != expanded[-1]:
                    expanded.append(candidate)
        if points and (not expanded or expanded[-1] != points[-1]):
            expanded.append(points[-1])
        return expanded

    @staticmethod
    def _nearest_platform_node(nodes, point, horizontal, vertical):
        candidates = [
            node
            for node in nodes
            if node.kind == "platform"
            and abs(node.point.x - point.x) <= horizontal
            and abs(node.point.y - point.y) <= vertical
        ]
        return min(
            candidates,
            key=lambda node: math.hypot(node.point.x - point.x, node.point.y - point.y),
            default=None,
        )

    @classmethod
    def _add_drop_edges(cls, graph, topology, platform_nodes):
        for source in topology.platforms:
            source_nodes = platform_nodes.get(source.id, [])
            for source_node in source_nodes:
                candidates = []
                for target in topology.platforms:
                    if target.id == source.id:
                        continue
                    target_node = min(
                        platform_nodes.get(target.id, []),
                        key=lambda node: abs(node.point.x - source_node.point.x),
                        default=None,
                    )
                    if (
                        target_node is not None
                        and target_node.point.y > source_node.point.y + 0.03
                        and abs(target_node.point.x - source_node.point.x) <= 0.08
                    ):
                        candidates.append(target_node)
                landing = min(candidates, key=lambda node: node.point.y, default=None)
                crosses_rope = any(
                    abs(rope.x - source_node.point.x) <= 0.035
                    and landing is not None
                    and rope.bottom_y >= source_node.point.y + 0.015
                    and rope.top_y <= landing.point.y - 0.015
                    for rope in topology.ropes
                )
                if landing is not None and not crosses_rope:
                    graph.edges.append(
                        NavigationEdge(
                            f"drop:{source_node.id}:{landing.id}",
                            source_node.id,
                            landing.id,
                            "drop",
                            cls.DROP_COST,
                            "neutral",
                            120,
                            0.07,
                        )
                    )
            for source_node, direction, target_x in (
                (source_nodes[0], "left", source_nodes[0].point.x - 0.012),
                (source_nodes[-1], "right", source_nodes[-1].point.x + 0.012),
            ) if source_nodes else ():
                candidates = [
                    node
                    for target in topology.platforms
                    if target.id != source.id
                    for node in platform_nodes.get(target.id, [])
                    if node.point.y > source_node.point.y + 0.03
                    and abs(node.point.x - target_x) <= 0.035
                ]
                landing = min(candidates, key=lambda node: node.point.y, default=None)
                if landing is not None:
                    graph.edges.append(
                        NavigationEdge(
                            f"walkoff:{source_node.id}:{landing.id}:{direction}",
                            source_node.id,
                            landing.id,
                            "drop",
                            cls.DROP_COST,
                            direction,
                            250,
                            0.07,
                        )
                    )

    @classmethod
    def _add_saved_connections(cls, graph, topology, platform_nodes):
        for connection in topology.traversal_connections:
            if not connection.is_enabled:
                continue
            source = min(
                platform_nodes.get(connection.from_platform_id, []),
                key=lambda node: abs(node.point.x - connection.start_point.x),
                default=None,
            )
            destination = min(
                platform_nodes.get(connection.to_platform_id, []),
                key=lambda node: abs(node.point.x - connection.landing_point.x),
                default=None,
            )
            if source and destination:
                graph.edges.append(
                    NavigationEdge(
                        f"saved:{connection.id}",
                        source.id,
                        destination.id,
                        connection.kind,
                        2.8 if connection.kind == "jump" else cls.DROP_COST,
                        connection.direction,
                        connection.key_hold_milliseconds,
                        connection.landing_tolerance,
                    )
                )

    @classmethod
    def _add_intra_map_portals(cls, graph, topology):
        portal_nodes = {
            node.reference_id: node for node in graph.nodes if node.kind == "portal"
        }
        for portal in topology.portals:
            destination = portal_nodes.get(portal.destination_portal_id or "")
            source = portal_nodes.get(portal.id)
            if source and destination:
                graph.edges.append(
                    NavigationEdge(
                        f"portal-edge:{portal.id}",
                        source.id,
                        destination.id,
                        "portal",
                        cls.PORTAL_COST,
                    )
                )

    @staticmethod
    def _bidirectional(graph, first, second, kind, cost):
        graph.edges.extend(
            (
                NavigationEdge(
                    f"{kind}:{first.id}:{second.id}",
                    first.id,
                    second.id,
                    kind,
                    cost,
                    "right" if second.point.x >= first.point.x else "left",
                ),
                NavigationEdge(
                    f"{kind}:{second.id}:{first.id}",
                    second.id,
                    first.id,
                    kind,
                    cost,
                    "right" if first.point.x >= second.point.x else "left",
                ),
            )
        )


class MapPathPlanner:
    @staticmethod
    def locate_current_node(
        point: NormalizedMapPoint,
        topology: MapTopology,
        graph: MapNavigationGraph,
    ):
        """优先判定平台/绳索归属，再选择该标注上的最近图节点。"""
        candidates = []
        for platform in topology.platforms:
            distances = [
                MapPathPlanner._point_segment_distance(point, start, end)
                for start, end in zip(platform.points, platform.points[1:])
            ]
            distance = min(distances, default=math.inf)
            if distance <= 0.065:
                candidates.append((platform.id, distance, "platform"))
        for rope in topology.ropes:
            x_distance = abs(point.x - rope.x)
            if (
                x_distance <= 0.045
                and rope.top_y - 0.04 <= point.y <= rope.bottom_y + 0.04
            ):
                candidates.append((rope.id, x_distance, "rope"))
        if not candidates:
            return graph.nearest_node(point, 0.12, topology.map_name)
        reference_id, _, _ = min(candidates, key=lambda item: item[1])
        return min(
            (
                node
                for node in graph.nodes
                if node.map_name == topology.map_name
                and node.reference_id == reference_id
            ),
            key=lambda node: math.hypot(
                node.point.x - point.x,
                node.point.y - point.y,
            ),
            default=None,
        )

    @staticmethod
    def shortest_path_to_target(
        graph: MapNavigationGraph,
        source_id: str,
        target_reference_id: str,
        target_map_name: str,
    ) -> Optional[list[NavigationEdge]]:
        targets = {
            node.id
            for node in graph.nodes
            if node.map_name == target_map_name
            and node.reference_id == target_reference_id
        }
        best = None
        for target_id in targets:
            path = MapPathPlanner.shortest_path(graph, source_id, target_id)
            if path is None:
                continue
            cost = sum(edge.cost for edge in path)
            if best is None or cost < best[0]:
                best = (cost, path)
        return best[1] if best else None

    @staticmethod
    def shortest_path(
        graph: MapNavigationGraph,
        source_id: str,
        destination_id: str,
    ) -> Optional[list[NavigationEdge]]:
        if source_id == destination_id:
            return []
        distances = {source_id: 0.0}
        previous = {}
        queue = [(0.0, source_id)]
        while queue:
            distance, node_id = heapq.heappop(queue)
            if distance != distances.get(node_id):
                continue
            if node_id == destination_id:
                break
            for edge in graph.outgoing(node_id):
                candidate = distance + max(0.001, edge.cost)
                if candidate < distances.get(edge.destination_id, math.inf):
                    distances[edge.destination_id] = candidate
                    previous[edge.destination_id] = edge
                    heapq.heappush(queue, (candidate, edge.destination_id))
        if destination_id not in previous:
            return None
        result = []
        current = destination_id
        while current != source_id:
            edge = previous[current]
            result.append(edge)
            current = edge.source_id
        result.reverse()
        return result

    @staticmethod
    def disconnected_nodes(graph: MapNavigationGraph) -> list[NavigationNode]:
        if not graph.nodes:
            return []
        seen = {graph.nodes[0].id}
        pending = [graph.nodes[0].id]
        while pending:
            current = pending.pop()
            neighbors = {
                edge.destination_id
                for edge in graph.edges
                if edge.source_id == current
            } | {
                edge.source_id
                for edge in graph.edges
                if edge.destination_id == current
            }
            for neighbor in neighbors - seen:
                seen.add(neighbor)
                pending.append(neighbor)
        return [node for node in graph.nodes if node.id not in seen]

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

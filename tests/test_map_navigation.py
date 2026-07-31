import unittest

from models.map_navigation import MapNavigationGraphBuilder, MapPathPlanner
from models.map_topology import MapPlatform, MapRope, MapTopology, NormalizedMapPoint


class MapNavigationTests(unittest.TestCase):
    def test_builds_walk_climb_and_drop_edges(self):
        top = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.3), NormalizedMapPoint(0.8, 0.3)]
        )
        bottom = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.7), NormalizedMapPoint(0.8, 0.7)]
        )
        topology = MapTopology(
            "路径图",
            200,
            100,
            platforms=[top, bottom],
            ropes=[MapRope(0.15, 0.28, 0.72)],
        )

        graph = MapNavigationGraphBuilder.build(topology)
        kinds = {edge.kind for edge in graph.edges}

        self.assertIn("walk", kinds)
        self.assertIn("climb", kinds)
        self.assertIn("drop", kinds)

    def test_shortest_path_combines_actions(self):
        top = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.3), NormalizedMapPoint(0.8, 0.3)]
        )
        bottom = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.7), NormalizedMapPoint(0.8, 0.7)]
        )
        graph = MapNavigationGraphBuilder.build(
            MapTopology("路径图", 200, 100, platforms=[top, bottom])
        )
        source = next(
            node.id for node in graph.nodes if node.reference_id == top.id
        )
        destination = next(
            node.id for node in graph.nodes if node.reference_id == bottom.id
        )

        path = MapPathPlanner.shortest_path(graph, source, destination)

        self.assertIsNotNone(path)
        self.assertEqual(path[-1].kind, "drop")

    def test_cross_map_portal_connects_two_graphs(self):
        from models.map_topology import MapPortal

        first_platform = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.5), NormalizedMapPoint(0.8, 0.5)]
        )
        second_platform = MapPlatform(
            points=[NormalizedMapPoint(0.1, 0.5), NormalizedMapPoint(0.8, 0.5)]
        )
        first_portal = MapPortal(NormalizedMapPoint(0.7, 0.5))
        second_portal = MapPortal(NormalizedMapPoint(0.2, 0.5))
        first_portal.destination_map_name = "地图二"
        first_portal.destination_portal_id = second_portal.id
        maps = [
            MapTopology(
                "地图一",
                200,
                100,
                platforms=[first_platform],
                portals=[first_portal],
            ),
            MapTopology(
                "地图二",
                200,
                100,
                platforms=[second_platform],
                portals=[second_portal],
            ),
        ]
        graph = MapNavigationGraphBuilder.build(maps)
        source = next(
            node.id for node in graph.nodes if node.reference_id == first_platform.id
        )
        path = MapPathPlanner.shortest_path_to_target(
            graph,
            source,
            second_platform.id,
            "地图二",
        )
        self.assertIsNotNone(path)
        self.assertIn("portal", [edge.kind for edge in path])


if __name__ == "__main__":
    unittest.main()

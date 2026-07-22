import unittest

from fire_spread.osm import network_from_osm


class OsmConversionTests(unittest.TestCase):
    def test_way_geometry_becomes_meter_graph_and_preserves_oneway(self):
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 10,
                    "tags": {"highway": "residential", "surface": "asphalt", "oneway": "yes"},
                    "geometry": [
                        {"lat": 39.0, "lon": 32.0},
                        {"lat": 39.0, "lon": 32.001},
                        {"lat": 39.001, "lon": 32.001},
                    ],
                }
            ]
        }

        graph = network_from_osm(payload, origin_lat=39.0, origin_lon=32.0)

        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(len(graph.edges), 2)
        self.assertGreater(graph.edges["osm:10:0"].length_m, 80)
        self.assertEqual(graph.edges["osm:10:0"].surface, "asphalt")
        self.assertEqual(graph.edges["osm:10:0"].width_m, 5.0)
        first_start = graph.edges["osm:10:0"].start
        first_end = graph.edges["osm:10:0"].end
        self.assertEqual(graph.neighbors(first_start)[0][0], first_end)
        self.assertNotIn(first_start, {neighbor for neighbor, _ in graph.neighbors(first_end)})
        self.assertGreater(graph.nodes[first_end].x, graph.nodes[first_start].x)

    def test_intersection_shared_by_ways_is_one_graph_node(self):
        shared = {"lat": 39.0, "lon": 32.001}
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": {"highway": "service"},
                    "geometry": [{"lat": 39.0, "lon": 32.0}, shared],
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"highway": "service"},
                    "geometry": [shared, {"lat": 39.001, "lon": 32.001}],
                },
            ]
        }

        graph = network_from_osm(payload, origin_lat=39.0, origin_lon=32.0)

        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(len(graph.edges), 2)
        shared_id = "osm:39.0000000:32.0010000"
        self.assertEqual(len(graph.neighbors(shared_id)), 2)

    def test_optional_osm_elevation_is_preserved_on_normalized_nodes(self):
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 3,
                    "tags": {"highway": "service"},
                    "geometry": [
                        {"lat": 39.0, "lon": 32.0, "ele": "925 m"},
                        {"lat": 39.0, "lon": 32.001, "ele": "926"},
                    ],
                }
            ]
        }

        graph = network_from_osm(payload, origin_lat=39.0, origin_lon=32.0)

        self.assertEqual(graph.nodes["osm:39.0000000:32.0000000"].elevation_m, 925.0)
        self.assertEqual(graph.nodes["osm:39.0000000:32.0010000"].elevation_m, 926.0)


if __name__ == "__main__":
    unittest.main()

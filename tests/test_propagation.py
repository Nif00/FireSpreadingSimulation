import unittest

from fire_spread.io import network_from_dict
from fire_spread.propagation import FireParameters, edge_speed_m_per_min, simulate


def network(*, bidirectional: bool = True):
    return network_from_dict(
        {
            "nodes": [
                {"id": "A", "x": 0, "y": 0},
                {"id": "B", "x": 30, "y": 0},
                {"id": "C", "x": 60, "y": 0},
            ],
            "edges": [
                {
                    "id": "A-B",
                    "start": "A",
                    "end": "B",
                    "length_m": 30,
                    "width_m": 6,
                    "surface": "paved",
                    "bidirectional": bidirectional,
                },
                {
                    "id": "B-C",
                    "start": "B",
                    "end": "C",
                    "length_m": 30,
                    "width_m": 3,
                    "surface": "vegetated",
                    "bidirectional": True,
                },
            ],
        }
    )


class NetworkContractTests(unittest.TestCase):
    def test_missing_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing nodes"):
            network_from_dict(
                {
                    "nodes": [{"id": "A", "x": 0, "y": 0}],
                    "edges": [
                        {"id": "A-Z", "start": "A", "end": "Z", "length_m": 10}
                    ],
                }
            )

    def test_directional_edge_only_allows_forward_spread(self):
        graph = network(bidirectional=False)

        forward = simulate(graph, ["A"], horizon_minutes=2)
        reverse = simulate(graph, ["B"], horizon_minutes=2)

        self.assertIn("B", forward.arrival_times)
        self.assertNotIn("A", reverse.arrival_times)
        self.assertIn("B-C", forward.edge_scores)


class PropagationContractTests(unittest.TestCase):
    def test_horizon_keeps_partial_front_without_claiming_arrival(self):
        result = simulate(network(), ["A"], horizon_minutes=0.5)

        self.assertEqual(result.arrival_times, {"A": 0.0})
        self.assertEqual(len(result.edge_arrivals), 1)
        arrival = result.edge_arrivals[0]
        self.assertFalse(arrival.complete)
        self.assertEqual(arrival.end_minute, 0.5)

    def test_reachable_node_arrival_is_earliest_path(self):
        result = simulate(network(), ["A"], horizon_minutes=10)

        self.assertAlmostEqual(result.arrival_times["B"], 1.0, places=6)
        self.assertLess(result.arrival_times["C"], 3.0)
        self.assertEqual(result.ignition_nodes, ("A",))

    def test_uphill_direction_is_faster_than_downhill_for_positive_slope(self):
        graph = network_from_dict(
            {
                "nodes": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 1, "y": 0}],
                "edges": [
                    {
                        "id": "A-B",
                        "start": "A",
                        "end": "B",
                        "length_m": 10,
                        "slope": 0.5,
                    }
                ],
            }
        )
        params = FireParameters()

        uphill = edge_speed_m_per_min(graph, graph.edges["A-B"], "A", "B", params)
        downhill = edge_speed_m_per_min(graph, graph.edges["A-B"], "B", "A", params)

        self.assertGreater(uphill, downhill)

    def test_scores_are_normalized_and_serializable(self):
        result = simulate(network(), ["A"], horizon_minutes=10)
        payload = result.to_dict()

        self.assertEqual(set(payload["edge_scores"]), {"A-B", "B-C"})
        self.assertTrue(all(0.0 <= score <= 1.0 for score in result.edge_scores.values()))
        self.assertEqual(payload["ignition_nodes"], ["A"])
        self.assertIsInstance(payload["edge_arrivals"], list)
        self.assertEqual(payload["parameters"]["base_rate_m_per_min"], 30.0)

    def test_unknown_ignition_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown ignition"):
            simulate(network(), ["missing"])


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from fire_spread.io import load_network
from fire_spread.web import ScenarioService


class PolatliDatasetTests(unittest.TestCase):
    dataset_path = Path("data/processed/polatli_network.json")
    buildings_path = Path("data/processed/polatli_buildings.json")

    def test_preserved_dataset_is_large_real_network(self):
        self.assertTrue(self.dataset_path.exists())
        payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        graph = load_network(self.dataset_path)

        self.assertEqual(payload["source"]["provider"], "OpenStreetMap contributors")
        self.assertGreaterEqual(len(graph.nodes), 10_000)
        self.assertGreaterEqual(len(graph.edges), 10_000)
        self.assertEqual(payload["source"]["osm_element_count"], 1837)

    def test_real_network_runs_from_default_center_ignition(self):
        service = ScenarioService(self.dataset_path, self.buildings_path)
        result = service.run({"horizon_minutes": 2})

        self.assertIn(service.default_ignition, result["arrival_times"])
        self.assertGreater(len(result["edge_arrivals"]), 0)
        self.assertEqual(len(result["edge_scores"]), len(service.network.edges))
        self.assertEqual(result["parameters"]["base_rate_m_per_min"], 30.0)
        self.assertEqual(result["dataset"]["source"]["provider"], "OpenStreetMap contributors")
        self.assertGreaterEqual(result["dataset"]["buildings"], 10_000)


if __name__ == "__main__":
    unittest.main()

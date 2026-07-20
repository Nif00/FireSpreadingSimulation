import json
import tempfile
import unittest
from pathlib import Path

from fire_spread.buildings import normalize_buildings


class BuildingNormalizationTests(unittest.TestCase):
    def test_footprints_and_height_provenance_are_preserved(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="39.0" lon="32.0" />
  <node id="2" lat="39.0" lon="32.001" />
  <node id="3" lat="39.001" lon="32.001" />
  <node id="4" lat="39.001" lon="32.0" />
  <way id="10">
    <nd ref="1" /><nd ref="2" /><nd ref="3" /><nd ref="4" /><nd ref="1" />
    <tag k="building" v="yes" />
    <tag k="height" v="12 m" />
  </way>
  <way id="11">
    <nd ref="1" /><nd ref="2" /><nd ref="3" />
    <tag k="building:part" v="yes" />
    <tag k="building:levels" v="2" />
  </way>
</osm>
"""
        with tempfile.TemporaryDirectory() as directory:
            tile = Path(directory) / "tile.osm"
            tile.write_text(xml, encoding="utf-8")
            payload = normalize_buildings(
                [tile],
                origin_lat=39.0,
                origin_lon=32.0,
                source={"provider": "test"},
            )

        self.assertEqual(len(payload["buildings"]), 2)
        by_id = {building["id"]: building for building in payload["buildings"]}
        self.assertEqual(by_id["osm:building:10"]["height_m"], 12.0)
        self.assertEqual(by_id["osm:building:10"]["height_source"], "height_tag")
        self.assertEqual(by_id["osm:building:11"]["height_m"], 6.0)
        self.assertEqual(by_id["osm:building:11"]["height_source"], "levels_estimate")
        self.assertGreater(by_id["osm:building:10"]["area_m2"], 1.0)
        self.assertEqual(payload["source"]["height_source_counts"]["height_tag"], 1)
        self.assertEqual(payload["source"]["height_source_counts"]["levels_estimate"], 1)


class RealBuildingLayerTests(unittest.TestCase):
    building_path = Path("data/processed/polatli_buildings.json")

    def test_real_layer_has_footprints_and_explicit_height_provenance(self):
        self.assertTrue(self.building_path.exists())
        payload = json.loads(self.building_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload["buildings"]), 10_000)
        self.assertEqual(payload["source"]["provider"], "OpenStreetMap contributors")
        self.assertGreater(payload["source"]["height_source_counts"]["footprint_only"], 0)
        self.assertGreater(payload["source"]["height_source_counts"]["height_tag"], 0)


if __name__ == "__main__":
    unittest.main()

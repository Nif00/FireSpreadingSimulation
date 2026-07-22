import unittest

from fire_spread.urban_wind import UrbanWindField


class UrbanWindFieldTests(unittest.TestCase):
    def field(self, buildings):
        return UrbanWindField.from_buildings(
            buildings,
            (0.0, 300.0, 0.0, 300.0),
            wind_speed_mps=10.0,
            wind_direction_deg=0.0,
            cell_size_m=50.0,
        )

    def test_open_cell_preserves_background_wind(self):
        field = self.field([])
        sample = field.sample(25.0, 25.0)

        self.assertAlmostEqual(sample.speed_mps, 10.0)
        self.assertAlmostEqual(sample.direction_deg, 0.0)
        self.assertEqual(sample.obstruction, 0.0)

    def test_building_massing_blocks_wind(self):
        field = self.field(
            [{"id": "building-1", "polygon": [[100, 100], [150, 100], [150, 150], [100, 150]], "height_m": 24}]
        )
        sample = field.sample(125.0, 125.0)

        self.assertGreater(sample.obstruction, 0.9)
        self.assertLess(sample.speed_mps, 10.0)
        self.assertEqual(field.obstacle_cells, 1)

    def test_unknown_height_uses_massing_fallback(self):
        field = self.field(
            [{"id": "building-1", "polygon": [[100, 100], [150, 100], [150, 150], [100, 150]]}]
        )
        sample = field.sample(125.0, 125.0)

        self.assertEqual(sample.building_height_m, 3.0)
        self.assertGreater(sample.obstruction, 0.0)


if __name__ == "__main__":
    unittest.main()

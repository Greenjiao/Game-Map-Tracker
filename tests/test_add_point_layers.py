import unittest
from pathlib import Path

from tools.add_point_layers import (
    LayerCatalog,
    annotation_points,
    apply_layer_fields,
    route_points,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AddPointLayersTests(unittest.TestCase):
    def test_catalog_maps_layer_name_to_background(self) -> None:
        catalog = LayerCatalog.load(PROJECT_ROOT / "maps" / "layer_maps.json")

        self.assertEqual(catalog.default_layer, "卡洛西亚大陆")
        self.assertEqual(catalog.layers["卡洛西亚大陆"]["background_id"], 10003)
        self.assertEqual(catalog.layers["月兔暗港"]["background_id"], 12)

    def test_migration_preserves_existing_and_excludes_nodes(self) -> None:
        catalog = LayerCatalog.load(PROJECT_ROOT / "maps" / "layer_maps.json")
        annotation = {
            "pointsByType": {
                "ore": [
                    {"x": 1, "y": 2},
                    {"x": 3, "y": 4, "layer": "月兔暗港"},
                ]
            }
        }
        route = {
            "points": [{"x": 5, "y": 6}],
            "nodes": [{"x": 7, "y": 8}],
        }

        annotation_stats = apply_layer_fields(annotation_points(annotation), catalog=catalog)
        route_stats = apply_layer_fields(route_points(route), catalog=catalog)

        self.assertEqual(annotation["pointsByType"]["ore"][0]["layer"], "卡洛西亚大陆")
        self.assertEqual(annotation["pointsByType"]["ore"][1]["layer"], "月兔暗港")
        self.assertEqual(route["points"][0]["layer"], "卡洛西亚大陆")
        self.assertEqual(list(route["points"][0]), ["x", "layer", "y"])
        self.assertNotIn("layer", route["nodes"][0])
        self.assertEqual(annotation_stats.points_changed, 1)
        self.assertEqual(annotation_stats.existing_preserved, 1)
        self.assertEqual(route_stats.points_changed, 1)

    def test_unknown_existing_layer_is_rejected(self) -> None:
        catalog = LayerCatalog.load(PROJECT_ROOT / "maps" / "layer_maps.json")

        with self.assertRaisesRegex(ValueError, "Unknown point layer"):
            apply_layer_fields([{"layer": "not-in-catalog"}], catalog=catalog)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from tools.fetch_17173_points import latlng_to_xy
from tools.route_format_converter import (
    RouteAnnotationOptions,
    annotate_route_folder,
    annotate_route_payload,
    convert_old_big_map_route_payload,
    convert_old_big_map_routes_in_place,
    convert_route_folder,
    default_route_teleport_type_ids,
    normalize_route_payload,
    old_big_map_xy_to_17173_xy,
)
from ui_island.services.annotation_matcher import AnnotationMatchIndex
from ui_island.services import resource_metadata

_MAP_HASH = "a" * 32


def _old_xy_from_latlng(latitude: float, longitude: float) -> tuple[float, float]:
    return 5824.0800 * longitude + 7217.5810, -5822.8413 * latitude + 6602.7721


def _write_route(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_x, old_y = _old_xy_from_latlng(0.3, -0.2)
    path.write_text(
        json.dumps({"name": "路线", "points": [{"x": old_x, "y": old_y}]}, ensure_ascii=False),
        encoding="utf-8",
    )


class RouteFormatConverterTests(unittest.TestCase):
    def test_normalize_route_payload_removes_map_metadata_and_preserves_unknown_fields(self) -> None:
        payload = normalize_route_payload(
            {
                "id": "not-valid",
                "name": "路线",
                "notes": "说明",
                "loop": True,
                "map_hash": _MAP_HASH,
                "map_hashs": [_MAP_HASH],
                "map_info": {"map_id": "10003", "map_name": "卡洛西亚大陆"},
                "coordinate_space_id": "legacy_big_map_unmapped",
                "annotation_hash": "b" * 32,
                "custom": {"kept": True},
                "points": [{"x": 1, "y": 2}],
            }
        )

        keys = list(payload)
        self.assertTrue(resource_metadata.HASH_RE.fullmatch(payload["id"]))
        self.assertNotIn("format_version", payload)
        self.assertNotIn("enable_versions", payload)
        self.assertEqual(payload["annotation_hash"], "b" * 32)
        self.assertEqual(payload["custom"], {"kept": True})
        self.assertNotIn("color", payload)
        self.assertNotIn("coordinate_space_id", payload)
        self.assertNotIn("map_hash", payload)
        self.assertNotIn("map_hashs", payload)
        self.assertNotIn("map_info", payload)
        self.assertLess(keys.index("notes"), keys.index("loop"))

    def test_convert_route_folder_writes_new_files_without_inventing_map_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "in"
            output_dir = root / "out"
            category = input_dir / "分类"
            category.mkdir(parents=True)
            old_x, old_y = _old_xy_from_latlng(0.3, -0.2)
            expected_x, expected_y = latlng_to_xy(0.3, -0.2)
            (category / "route.json").write_text(
                json.dumps({"name": "路线", "points": [{"x": old_x, "y": old_y}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (input_dir / "progress.json").write_text("{}", encoding="utf-8")
            (input_dir / "metadata.json").write_text(json.dumps({"name": "not route"}), encoding="utf-8")

            report = convert_route_folder(input_dir, output_dir)

            self.assertEqual(report.converted, 1)
            self.assertEqual(report.ignored, 2)
            self.assertEqual(report.points_converted, 1)
            target = next((output_dir / "分类").glob("route_*.json"))
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertNotIn("map_info", payload)
            self.assertNotIn("map_hashs", payload)
            self.assertNotIn("coordinate_space_id", payload)
            self.assertNotIn("color", payload)
            self.assertEqual(payload["name"], "路线")
            self.assertTrue(resource_metadata.HASH_RE.fullmatch(payload["id"]))
            self.assertEqual(payload["format_version"], resource_metadata.APP_FORMAT_VERSION)
            self.assertEqual(payload["enable_versions"], [resource_metadata.APP_FORMAT_VERSION])
            self.assertEqual(payload["points"][0]["x"], expected_x)
            self.assertEqual(payload["points"][0]["y"], expected_y)

    def test_convert_route_folder_rejects_same_input_and_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_route(root / "route.json")

            with self.assertRaisesRegex(ValueError, "输出目录不能和输入目录相同"):
                convert_route_folder(root, root)

    def test_convert_route_folder_rejects_recursive_output_inside_input_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "in"
            output_dir = input_dir / "converted"
            _write_route(input_dir / "route.json")

            with self.assertRaisesRegex(ValueError, "输出目录不能位于输入目录内部"):
                convert_route_folder(input_dir, output_dir, recursive=True)

    def test_convert_route_folder_allows_sibling_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "in"
            output_dir = root / "converted"
            _write_route(input_dir / "route.json")

            report = convert_route_folder(input_dir, output_dir, recursive=True)

            self.assertEqual(report.converted, 1)
            self.assertTrue((output_dir / "route_新格式.json").is_file())

    def test_normalize_route_payload_keeps_existing_format_metadata(self) -> None:
        source_info = {"map_id": "source", "map_name": "源地图"}

        payload = normalize_route_payload(
            {
                "id": "f" * 32,
                "format_version": "old-format",
                "enable_versions": ["old-format"],
                "map_hashs": [_MAP_HASH],
                "map_info": source_info,
                "coordinate_space_id": "legacy_big_map_unmapped",
                "points": [],
            }
        )

        self.assertEqual(payload["id"], "f" * 32)
        self.assertEqual(payload["format_version"], "old-format")
        self.assertEqual(payload["enable_versions"], ["old-format", resource_metadata.APP_FORMAT_VERSION])
        self.assertNotIn("coordinate_space_id", payload)
        self.assertNotIn("map_info", payload)
        self.assertNotIn("map_hashs", payload)

    def test_normalize_route_payload_keeps_valid_numeric_id(self) -> None:
        payload = normalize_route_payload({"id": "2026041913", "name": "路线", "points": []})

        self.assertEqual(payload["id"], "2026041913")
        self.assertNotIn("format_version", payload)

    def test_old_big_map_xy_to_17173_xy_uses_reversed_fit_formula(self) -> None:
        old_x, old_y = _old_xy_from_latlng(1.2, -0.75)

        self.assertEqual(old_big_map_xy_to_17173_xy(old_x, old_y), latlng_to_xy(1.2, -0.75))

    def test_convert_old_big_map_route_payload_converts_points_and_removes_metadata(self) -> None:
        old_x, old_y = _old_xy_from_latlng(0.7, -0.4)
        expected_x, expected_y = latlng_to_xy(0.7, -0.4)

        payload, point_count = convert_old_big_map_route_payload(
            {
                "name": "旧路线",
                "map_hash": _MAP_HASH,
                "map_hashs": [_MAP_HASH],
                "map_info": {"map_id": "10003", "map_name": "卡洛西亚大陆"},
                "format_version": "legacy-route-format",
                "coordinate_space_id": "legacy_big_map_unmapped",
                "points": [
                    {"x": old_x, "y": old_y, "label": "A"},
                    {"label": "missing xy"},
                ],
            }
        )

        self.assertEqual(point_count, 1)
        self.assertTrue(resource_metadata.HASH_RE.fullmatch(payload["id"]))
        self.assertEqual(payload["format_version"], "legacy-route-format")
        self.assertEqual(payload["enable_versions"], [resource_metadata.APP_FORMAT_VERSION])
        self.assertEqual(payload["points"][0]["x"], expected_x)
        self.assertEqual(payload["points"][0]["y"], expected_y)
        self.assertEqual(payload["points"][0]["label"], "A")
        self.assertEqual(payload["points"][1], {"label": "missing xy"})
        self.assertNotIn("map_hash", payload)
        self.assertNotIn("map_hashs", payload)
        self.assertNotIn("map_info", payload)
        self.assertNotIn("coordinate_space_id", payload)

    def test_convert_old_big_map_route_payload_appends_current_enable_version(self) -> None:
        payload, _ = convert_old_big_map_route_payload(
            {
                "name": "旧路线",
                "format_version": "legacy-route-format",
                "enable_versions": ["legacy-route-format", resource_metadata.APP_FORMAT_VERSION, ""],
                "points": [],
            }
        )

        self.assertEqual(
            payload["enable_versions"],
            ["legacy-route-format", resource_metadata.APP_FORMAT_VERSION],
        )

    def test_convert_old_big_map_routes_in_place_overwrites_source_and_skips_non_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_dir = root / "routes"
            route_dir.mkdir()
            old_x, old_y = _old_xy_from_latlng(0.5, -0.2)
            expected_x, expected_y = latlng_to_xy(0.5, -0.2)
            source = route_dir / "route.json"
            source.write_text(
                json.dumps(
                    {
                        "name": "旧路线",
                        "coordinate_space_id": "legacy_big_map_unmapped",
                        "points": [{"x": old_x, "y": old_y}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (route_dir / "progress.json").write_text("{}", encoding="utf-8")
            (route_dir / "metadata.json").write_text(json.dumps({"name": "not route"}), encoding="utf-8")

            report = convert_old_big_map_routes_in_place(route_dir)

            self.assertEqual(report.converted, 1)
            self.assertEqual(report.ignored, 2)
            self.assertEqual(report.points_converted, 1)
            self.assertFalse(any(route_dir.glob("*_新格式.json")))

            payload = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["x"], expected_x)
            self.assertEqual(payload["points"][0]["y"], expected_y)
            self.assertTrue(resource_metadata.HASH_RE.fullmatch(payload["id"]))
            self.assertEqual(payload["format_version"], resource_metadata.APP_FORMAT_VERSION)
            self.assertEqual(payload["enable_versions"], [resource_metadata.APP_FORMAT_VERSION])
            self.assertNotIn("coordinate_space_id", payload)

    def test_annotate_route_payload_matches_annotations_and_preserves_manual_fields(self) -> None:
        annotation_payload = {
            "types": [
                {"typeId": "flower", "type": "花"},
                {"typeId": "teleport", "type": "魔力之源（传送点）"},
                {"typeId": "ore", "type": "矿"},
            ],
            "pointsByType": {
                "flower": [{"x": 10, "y": 10, "label": "花点"}],
                "teleport": [{"x": 40, "y": 40, "label": "传送点"}],
                "ore": [{"x": 13, "y": 10, "label": "矿点"}],
            },
        }
        matcher = AnnotationMatchIndex(annotation_payload)
        route = {
            "name": "路线",
            "points": [
                {"x": 11, "y": 10},
                {"x": 40, "y": 40},
                {"x": 100, "y": 100},
                {"x": 10, "y": 10, "node_type": "virtual"},
                {"x": 10, "y": 10, "typeId": "manual", "type": "手动", "node_type": "collect"},
                {"x": 11, "y": 10, "node_type": "teleport"},
            ],
        }
        options = RouteAnnotationOptions(
            annotation_file="unused",
            match_type_ids=("flower", "teleport", "ore"),
            teleport_type_ids=("teleport",),
            max_radius=12,
            ambiguous_distance_delta=5,
        )

        converted, stats, messages = annotate_route_payload(route, matcher, options)

        points = converted["points"]
        self.assertEqual(points[0]["typeId"], "flower")
        self.assertEqual(points[0]["type"], "花")
        self.assertEqual(points[0]["node_type"], "collect")
        self.assertEqual(points[1]["typeId"], "teleport")
        self.assertEqual(points[1]["node_type"], "teleport")
        self.assertEqual(points[2], {"x": 100, "y": 100, "node_type": "collect"})
        self.assertEqual(points[3], {"x": 10, "y": 10, "node_type": "virtual"})
        self.assertEqual(points[4]["typeId"], "manual")
        self.assertEqual(points[5]["node_type"], "teleport")
        self.assertEqual(points[5]["typeId"], "flower")
        self.assertEqual(stats.matched, 3)
        self.assertEqual(stats.unmatched, 1)
        self.assertEqual(stats.existing_skipped, 1)
        self.assertEqual(stats.virtual_skipped, 1)
        self.assertEqual(stats.teleports, 2)
        self.assertEqual(stats.suspicious, 2)
        self.assertTrue(any("[可疑]" in message for message in messages))

    def test_annotate_route_folder_writes_new_files_with_original_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "in"
            output_dir = root / "out"
            input_dir.mkdir()
            annotation_file = root / "points.json"
            annotation_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "花"}],
                        "pointsByType": {"flower": [{"x": 10, "y": 10}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (input_dir / "route.json").write_text(
                json.dumps({"name": "路线", "points": [{"x": 10, "y": 10}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            report = annotate_route_folder(
                input_dir,
                output_dir,
                RouteAnnotationOptions(
                    annotation_file=str(annotation_file),
                    match_type_ids=("flower",),
                    max_radius=12,
                ),
            )

            self.assertEqual(report.converted, 1)
            self.assertEqual(report.annotation_matched, 1)
            payload = json.loads((output_dir / "route.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["typeId"], "flower")
            self.assertFalse((output_dir / "route_新格式.json").exists())

    def test_annotate_route_folder_in_place_skips_when_nothing_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "in"
            input_dir.mkdir()
            annotation_file = root / "points.json"
            annotation_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "花"}],
                        "pointsByType": {"flower": [{"x": 10, "y": 10}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = input_dir / "route.json"
            source.write_text(
                json.dumps({"name": "路线", "points": [{"x": 10, "y": 10, "typeId": "old"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            report = annotate_route_folder(
                input_dir,
                None,
                RouteAnnotationOptions(
                    annotation_file=str(annotation_file),
                    match_type_ids=("flower",),
                    max_radius=12,
                ),
                in_place=True,
            )

            self.assertEqual(report.converted, 0)
            self.assertEqual(report.skipped, 1)
            payload = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["typeId"], "old")

    def test_default_route_teleport_type_ids_uses_teleport_folder_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            annotation_file = root / "points.json"
            annotation_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {"typeId": "tp", "type": "魔力之源（传送点）"},
                            {"typeId": "flower", "type": "花"},
                        ],
                        "pointsByType": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            teleport_dir = root / "teleport"
            teleport_dir.mkdir()
            (teleport_dir / "魔力之源（传送点）.json").write_text("{}", encoding="utf-8")

            self.assertEqual(default_route_teleport_type_ids(annotation_file, teleport_dir), ["tp"])


if __name__ == "__main__":
    unittest.main()

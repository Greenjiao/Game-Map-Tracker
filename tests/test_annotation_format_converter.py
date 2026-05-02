import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools.annotation_format_converter import (
    convert_annotation_file,
    convert_old_big_map_annotation_payload,
)
from tools.annotation_converters.legacy_coordinate_convert import (
    _old_big_map_xy_to_17173_xy as annotation_old_big_map_xy_to_17173_xy,
)
from tools.annotation_converters.outside_convert.rocopath_convert import convert_rocopath_resource_points_payload
from tools.annotation_converters.outside_convert.rocopath_convert import (
    _rocopath_xy_to_gmt_xy as rocopath_xy_to_gmt_xy,
)
from tools.annotation_converters.base import UnsupportedAnnotationFormatError
from tools.annotation_converters.annotation_merge import convert_annotation_merge_file
from tools.annotation_converters.registry import (
    _OUTSIDE_CONVERTERS,
    convert_outside_annotation_file,
    register_outside_converter,
)
from tools.fetch_17173_points import latlng_to_xy
from tools.route_format_converter import old_big_map_xy_to_17173_xy as route_old_big_map_xy_to_17173_xy
from ui_island.services import resource_metadata


def _old_xy_from_latlng(latitude: float, longitude: float) -> tuple[float, float]:
    return 5824.0800 * longitude + 7217.5810, -5822.8413 * latitude + 6602.7721


class AnnotationFormatConverterTests(unittest.TestCase):
    def test_legacy_coordinate_converters_have_identical_behavior(self) -> None:
        exact_samples = [
            ((0.0, 0.0), (8191, 8191)),
            ((0.7, -0.4), (5862, 4114)),
            ((1.2, -0.75), (3823, 1201)),
            ((1.4, -1.4), (36, 36)),
        ]

        for (latitude, longitude), expected in exact_samples:
            old_x, old_y = _old_xy_from_latlng(latitude, longitude)
            route_xy = route_old_big_map_xy_to_17173_xy(old_x, old_y)
            annotation_xy = annotation_old_big_map_xy_to_17173_xy(old_x, old_y)
            rocopath_xy = rocopath_xy_to_gmt_xy(old_x, old_y)

            self.assertEqual(route_xy, expected)
            self.assertEqual(annotation_xy, expected)
            self.assertEqual(rocopath_xy, expected)

        old_x, old_y = _old_xy_from_latlng(10.0, 10.0)
        route_xy = route_old_big_map_xy_to_17173_xy(old_x, old_y)
        annotation_xy = annotation_old_big_map_xy_to_17173_xy(old_x, old_y)
        rocopath_xy = rocopath_xy_to_gmt_xy(old_x, old_y)

        self.assertEqual(route_xy, annotation_xy)
        self.assertEqual(annotation_xy, rocopath_xy)
        self.assertTrue(all(0 <= value <= 8191 for value in route_xy))

    def test_legacy_annotation_conversion_does_not_call_route_converter(self) -> None:
        old_x, old_y = _old_xy_from_latlng(0.7, -0.4)

        with patch("tools.route_format_converter.old_big_map_xy_to_17173_xy", side_effect=AssertionError):
            payload, report = convert_old_big_map_annotation_payload(
                {
                    "pointsByType": {
                        "sample": [
                            {"x": old_x, "y": old_y, "label": "old point", "typeId": "sample"},
                        ]
                    }
                }
            )

        self.assertEqual(report.converted_points, 1)
        self.assertEqual(payload["pointsByType"]["sample"][0]["x"], 5862)
        self.assertEqual(payload["pointsByType"]["sample"][0]["y"], 4114)

    def test_builtin_annotation_data_has_rocopath_type_adjustments(self) -> None:
        payload = json.loads(Path("annotations/points_17173.json").read_text(encoding="utf-8-sig"))
        icons = json.loads(Path("tools/points_icon/icons.json").read_text(encoding="utf-8-sig"))
        type_items = {str(item["typeId"]): item for item in payload["types"]}
        icon_items = {str(item["typeId"]): item for item in icons}

        self.assertEqual(type_items["17310030002"]["type"], "\u679c\u6811")
        self.assertEqual(type_items["17310030062"]["type"], "\u871c\u9ec4\u83cc")
        self.assertEqual(type_items["17310030065"]["type"], "\u4f1e\u4f1e\u83cc")
        self.assertEqual(type_items["17310030055"]["type"], "\u51e4\u773c\u83b2")
        for type_id in ("17310030002", "17310030062", "17310030065"):
            points = payload["pointsByType"][type_id]
            self.assertTrue(points)
            self.assertTrue(all(point["type"] == type_items[type_id]["type"] for point in points))

        sea_coral_points = payload["pointsByType"]["17310030083"]
        self.assertEqual(type_items["17310030083"]["type"], "\u6d77\u73ca\u745a")
        self.assertEqual(type_items["17310030083"]["count"], 16)
        self.assertEqual(len(sea_coral_points), 16)
        self.assertTrue(all(point["typeId"] == "17310030083" for point in sea_coral_points))
        self.assertEqual(icon_items["17310030083"]["groupId"], "1731003007")
        self.assertEqual(icon_items["17310030083"]["iconPath"], "17310030083.png")

    def test_convert_old_big_map_annotation_payload_converts_points_and_metadata(self) -> None:
        old_x, old_y = _old_xy_from_latlng(0.7, -0.4)
        expected_x, expected_y = latlng_to_xy(0.7, -0.4)

        payload, report = convert_old_big_map_annotation_payload(
            {
                "mapId": 4010,
                "types": [{"typeId": "flower", "type": "向阳花", "count": 99}],
                "pointsByType": {
                    "flower": [
                        {"x": old_x, "y": old_y, "label": "旧点", "type": "向阳花", "typeId": "flower"},
                        {"label": "缺坐标", "typeId": "flower"},
                    ]
                },
            }
        )

        self.assertEqual(report.converted_points, 1)
        self.assertEqual(report.skipped_points, 1)
        point = payload["pointsByType"]["flower"][0]
        self.assertEqual(point["x"], expected_x)
        self.assertEqual(point["y"], expected_y)
        self.assertEqual(point["label"], "旧点")
        self.assertEqual(payload["types"][0]["count"], 1)
        self.assertIn("id", payload)
        self.assertIn("format_version", payload)
        self.assertNotIn("enable_versions", payload)

    def test_convert_annotation_file_writes_converted_file_without_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_x, old_y = _old_xy_from_latlng(0.2, -0.3)
            old_file = root / "old.json"
            old_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "chest", "type": "宝箱"}],
                        "pointsByType": {"chest": [{"x": old_x, "y": old_y, "typeId": "chest"}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_dir = root / "annotations"

            report = convert_annotation_file(old_file, output_dir, merge=False)

            self.assertEqual(report.converted_points, 1)
            output_path = Path(report.output_path)
            self.assertTrue(output_path.is_file())
            self.assertEqual(output_path.parent, output_dir)
            self.assertRegex(output_path.name, r"^old_\d{8}01\.json$")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["pointsByType"]["chest"]), 1)
            self.assertEqual(payload["types"][0]["count"], 1)

    def test_convert_annotation_file_without_merge_increments_dated_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_x, old_y = _old_xy_from_latlng(0.2, -0.3)
            old_file = root / "old.json"
            old_file.write_text(
                json.dumps({"pointsByType": {"chest": [{"x": old_x, "y": old_y, "typeId": "chest"}]}}),
                encoding="utf-8",
            )
            output_dir = root / "annotations"
            output_dir.mkdir()
            first_report = convert_annotation_file(old_file, output_dir, merge=False)
            second_report = convert_annotation_file(old_file, output_dir, merge=False)

            self.assertRegex(Path(first_report.output_path).name, r"^old_\d{8}01\.json$")
            self.assertRegex(Path(second_report.output_path).name, r"^old_\d{8}02\.json$")

    def test_convert_annotation_file_merge_only_carries_manual_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            non_manual_old_x, non_manual_old_y = _old_xy_from_latlng(0.1, -0.1)
            ore_old_x, ore_old_y = _old_xy_from_latlng(0.4, -0.2)
            old_file = root / "old.json"
            old_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {"typeId": "flower", "type": "向阳花", "count": 1},
                            {"typeId": "ore", "type": "矿石", "count": 1},
                        ],
                        "pointsByType": {
                            "flower": [
                                {
                                    "x": non_manual_old_x,
                                    "y": non_manual_old_y,
                                    "label": "旧官方点",
                                    "typeId": "flower",
                                    "id": "same-id",
                                }
                            ],
                            "ore": [
                                {
                                    "x": ore_old_x,
                                    "y": ore_old_y,
                                    "label": "旧手动矿石",
                                    "typeId": "ore",
                                    "id": "manual-1",
                                    "manual": True,
                                    "sourceId": 7,
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            new_file = root / "new.json"
            new_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "向阳花", "count": 1}],
                        "pointsByType": {
                            "flower": [
                                {
                                    "x": 10,
                                    "y": 11,
                                    "label": "新推送点",
                                    "typeId": "flower",
                                    "id": "same-id",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = convert_annotation_file(old_file, root / "annotations", merge=True, merge_with=new_file)

            self.assertEqual(report.converted_points, 1)
            self.assertEqual(report.skipped_points, 1)
            self.assertEqual(report.deduplicated_points, 0)
            payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
            self.assertEqual([point["label"] for point in payload["pointsByType"]["flower"]], ["新推送点"])
            ore_point = payload["pointsByType"]["ore"][0]
            self.assertEqual(ore_point["label"], "旧手动矿石")
            self.assertEqual(ore_point["sourceId"], 7)
            self.assertTrue(ore_point["manual"])
            counts = {item["typeId"]: item["count"] for item in payload["types"]}
            self.assertEqual(counts["flower"], 1)
            self.assertEqual(counts["ore"], 1)

    def test_convert_annotation_file_merge_keeps_manual_point_even_when_id_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_x, old_y = _old_xy_from_latlng(0.4, -0.2)
            old_file = root / "old.json"
            old_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "ore", "type": "矿石", "count": 1}],
                        "pointsByType": {
                            "ore": [
                                {
                                    "x": old_x,
                                    "y": old_y,
                                    "label": "旧手动矿石",
                                    "typeId": "ore",
                                    "id": "manual-1",
                                    "manual": True,
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            new_file = root / "new.json"
            new_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "ore", "type": "矿石", "count": 1}],
                        "pointsByType": {
                            "ore": [
                                {
                                    "x": 1,
                                    "y": 2,
                                    "label": "已有手动矿石",
                                    "typeId": "ore",
                                    "id": "manual-1",
                                    "manual": True,
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = convert_annotation_file(old_file, root / "annotations", merge=True, merge_with=new_file)

            self.assertEqual(report.converted_points, 1)
            self.assertEqual(report.deduplicated_points, 0)
            payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
            self.assertEqual(
                [point["label"] for point in payload["pointsByType"]["ore"]],
                ["已有手动矿石", "旧手动矿石"],
            )

    def test_annotation_merge_file_merges_all_points_and_deduplicates_by_id_and_near_coordinate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_file = root / "target.json"
            source_file = root / "source.json"
            version = resource_metadata.APP_FORMAT_VERSION
            target_file.write_text(
                json.dumps(
                    {
                        "format_version": version,
                        "types": [{"typeId": "ore", "type": "矿石", "count": 2}],
                        "pointsByType": {
                            "ore": [
                                {"x": 10, "y": 10, "label": "已有 id", "typeId": "ore", "id": "same-id"},
                                {"x": 20, "y": 20, "label": "已有坐标", "typeId": "ore"},
                            ],
                            "flower": [{"x": 20, "y": 20, "label": "不同类型", "typeId": "flower"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source_file.write_text(
                json.dumps(
                    {
                        "format_version": version,
                        "types": [
                            {"typeId": "ore", "type": "矿石", "count": 4},
                            {"typeId": "tree", "type": "树木", "count": 1},
                        ],
                        "pointsByType": {
                            "ore": [
                                {"x": 100, "y": 100, "label": "重复 id", "typeId": "ore", "id": "same-id"},
                                {"x": 22, "y": 21, "label": "近坐标", "typeId": "ore"},
                                {"x": 24, "y": 24, "label": "新矿石", "typeId": "ore", "id": "new-id"},
                            ],
                            "tree": [{"x": 50, "y": 50, "label": "新树", "typeId": "tree"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = convert_annotation_merge_file(source_file, root / "annotations", merge_with=target_file)

            self.assertEqual(report.converted_points, 2)
            self.assertEqual(report.deduplicated_points, 2)
            payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
            self.assertRegex(Path(report.output_path).name, r"^annotations_merged_\d{8}01\.json$")
            self.assertEqual([point["label"] for point in payload["pointsByType"]["ore"]], ["已有 id", "已有坐标", "新矿石"])
            self.assertEqual([point["label"] for point in payload["pointsByType"]["flower"]], ["不同类型"])
            self.assertEqual([point["label"] for point in payload["pointsByType"]["tree"]], ["新树"])
            counts = {item["typeId"]: item["count"] for item in payload["types"]}
            self.assertEqual(counts["ore"], 3)
            self.assertEqual(counts["flower"], 1)
            self.assertEqual(counts["tree"], 1)

    def test_annotation_merge_file_rejects_missing_or_different_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_file = root / "target.json"
            source_file = root / "source.json"
            target_file.write_text(json.dumps({"format_version": "tool-1", "pointsByType": {}}), encoding="utf-8")
            source_file.write_text(json.dumps({"format_version": "tool-2", "pointsByType": {}}), encoding="utf-8")

            with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "格式版本不同，无法合并"):
                convert_annotation_merge_file(source_file, root / "annotations", merge_with=target_file)

            source_file.write_text(json.dumps({"pointsByType": {}}), encoding="utf-8")
            with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "缺少 format_version"):
                convert_annotation_merge_file(source_file, root / "annotations", merge_with=target_file)

    def test_outside_converter_rejects_missing_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"pointsByType": {}}), encoding="utf-8")

            with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "缺少 format_version"):
                convert_outside_annotation_file(source, Path(tmp, "annotations"))

    def test_outside_converter_rejects_unsupported_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": "unsupported"}), encoding="utf-8")

            with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "\u6682\u4e0d\u517c\u5bb9\uff1aunsupported"):
                convert_outside_annotation_file(source, Path(tmp, "annotations"))

    def test_outside_converter_does_not_normalize_numeric_rocopath_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": 2, "items": []}), encoding="utf-8")

            with (
                patch("config.APP_ENABLE_VERSIONS", ["rocoparh_0.1"], create=True),
                self.assertRaisesRegex(UnsupportedAnnotationFormatError, "\u6682\u4e0d\u517c\u5bb9\uff1a2"),
            ):
                convert_outside_annotation_file(source, Path(tmp, "annotations"))

    def test_rocopath_converter_outputs_gmt_annotation_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(
                json.dumps(
                    {
                        "format_version": "rocoparh_0.1",
                        "name": "\u793a\u4f8b\u8d44\u6e90\u70b9",
                        "map_path": "display_map.png",
                        "notes": "\u5907\u6ce8",
                        "items": [
                            {
                                "id": "10001",
                                "x": 1321,
                                "y": 3741,
                                "label": "\u9ec4\u77f3\u69b4\u77f3 1",
                                "resource_type_id": "5511",
                                "resource_group_id": "144",
                                "resource_title": "\u9ec4\u77f3\u69b4\u77f3",
                                "icon_file": "FjGSxqYcrPovtCLNog50pRYnF2iG.png",
                            },
                            {
                                "id": "2704509",
                                "x": 5848,
                                "y": 3480,
                                "label": "\u6d77\u73ca\u745a 1",
                                "resource_type_id": "5609",
                                "resource_group_id": "152",
                                "resource_title": "\u6d77\u73ca\u745a",
                                "icon_file": "Fqp_hjI3621vgqua3C28od2Q2zpF.png",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch("config.APP_ENABLE_VERSIONS", ["rocoparh_0.1"], create=True),
                patch("tools.route_format_converter.old_big_map_xy_to_17173_xy", side_effect=AssertionError),
            ):
                report = convert_outside_annotation_file(source, Path(tmp, "annotations"))

            payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], resource_metadata.APP_FORMAT_VERSION)
            self.assertEqual(payload["origin_format_version"], "rocoparh_0.1")
            self.assertEqual(payload["target_format_version"], resource_metadata.APP_FORMAT_VERSION)
            datetime.fromisoformat(payload["generatedAt"])
            self.assertNotIn("enable_versions", payload)
            self.assertEqual(payload["name"], "\u793a\u4f8b\u8d44\u6e90\u70b9")
            self.assertEqual(payload["notes"], "\u5907\u6ce8")
            self.assertNotIn("map_path", payload)
            self.assertEqual([item["typeId"] for item in payload["types"]], ["17310030043", "17310030083"])
            self.assertEqual(payload["types"][0]["type"], "\u9ec4\u77f3\u69b4\u77f3")
            self.assertEqual(payload["types"][1]["type"], "\u6d77\u73ca\u745a")
            point = payload["pointsByType"]["17310030043"][0]
            self.assertEqual(point["sourceId"], 10001)
            self.assertEqual(point["x"], 2294)
            self.assertEqual(point["y"], 5329)
            self.assertEqual(point["label"], "\u9ec4\u77f3\u69b4\u77f3")
            self.assertEqual(set(point), {"x", "y", "label", "type", "typeId", "sourceId"})

            sea_coral = payload["pointsByType"]["17310030083"][0]
            self.assertEqual(sea_coral["x"], 6822)
            self.assertEqual(sea_coral["y"], 5068)
            self.assertEqual(sea_coral["label"], "\u6d77\u73ca\u745a")

    def test_rocopath_converter_rejects_unmapped_resource_type(self) -> None:
        with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "9999"):
            convert_rocopath_resource_points_payload(
                {
                    "items": [
                        {
                            "id": "1",
                            "x": 1,
                            "y": 2,
                            "label": "unknown",
                            "resource_type_id": "9999",
                            "resource_title": "\u672a\u77e5",
                        }
                    ]
                }
            )

    def test_outside_converter_rejects_supported_format_without_registered_converter(self) -> None:
        old_converters = dict(_OUTSIDE_CONVERTERS)
        import tools.annotation_converters.registry as registry
        old_discovered = registry._OUTSIDE_CONVERTERS_DISCOVERED
        try:
            _OUTSIDE_CONVERTERS.clear()
            registry._OUTSIDE_CONVERTERS_DISCOVERED = True

            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp, "source.json")
                source.write_text(
                    json.dumps({"format_version": resource_metadata.APP_FORMAT_VERSION}),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "未找到此格式版本的外部转换方法"):
                    convert_outside_annotation_file(source, Path(tmp, "annotations"))
        finally:
            _OUTSIDE_CONVERTERS.clear()
            _OUTSIDE_CONVERTERS.update(old_converters)
            registry._OUTSIDE_CONVERTERS_DISCOVERED = old_discovered

    def test_outside_converter_uses_registered_converter_for_supported_format(self) -> None:
        old_converters = dict(_OUTSIDE_CONVERTERS)
        import tools.annotation_converters.registry as registry
        old_discovered = registry._OUTSIDE_CONVERTERS_DISCOVERED
        try:
            _OUTSIDE_CONVERTERS.clear()
            registry._OUTSIDE_CONVERTERS_DISCOVERED = True
            register_outside_converter(
                resource_metadata.APP_FORMAT_VERSION,
                lambda payload: {
                    "mapId": payload.get("mapId", 4010),
                    "types": [{"typeId": "ore", "type": "矿石", "count": 1}],
                    "pointsByType": {"ore": [{"x": 1, "y": 2, "typeId": "ore"}]},
                },
            )

            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp, "source.json")
                source.write_text(
                    json.dumps({"format_version": resource_metadata.APP_FORMAT_VERSION, "mapId": 4010}),
                    encoding="utf-8",
                )

                report = convert_outside_annotation_file(source, Path(tmp, "annotations"))

                payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
                self.assertEqual(payload["format_version"], resource_metadata.APP_FORMAT_VERSION)
                self.assertEqual(payload["origin_format_version"], resource_metadata.APP_FORMAT_VERSION)
                self.assertEqual(payload["target_format_version"], resource_metadata.APP_FORMAT_VERSION)
                self.assertNotIn("enable_versions", payload)
                self.assertEqual(payload["pointsByType"]["ore"][0]["x"], 1)
        finally:
            _OUTSIDE_CONVERTERS.clear()
            _OUTSIDE_CONVERTERS.update(old_converters)
            registry._OUTSIDE_CONVERTERS_DISCOVERED = old_discovered


if __name__ == "__main__":
    unittest.main()

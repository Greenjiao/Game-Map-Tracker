import json
import tempfile
import unittest
from pathlib import Path

from tools.annotation_format_converter import (
    convert_annotation_file,
    convert_old_big_map_annotation_payload,
)
from tools.annotation_converters.base import UnsupportedAnnotationFormatError
from tools.annotation_converters.registry import (
    _OUTSIDE_CONVERTERS,
    convert_outside_annotation_file,
    register_outside_converter,
)
from tools.fetch_17173_points import latlng_to_xy
from ui_island.services import resource_metadata


def _old_xy_from_latlng(latitude: float, longitude: float) -> tuple[float, float]:
    return 5824.0800 * longitude + 7217.5810, -5822.8413 * latitude + 6602.7721


class AnnotationFormatConverterTests(unittest.TestCase):
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
        self.assertIn("enable_versions", payload)

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

            with self.assertRaisesRegex(UnsupportedAnnotationFormatError, "暂未兼容转换"):
                convert_outside_annotation_file(source, Path(tmp, "annotations"))

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
                self.assertIn(resource_metadata.APP_FORMAT_VERSION, payload["enable_versions"])
                self.assertEqual(payload["pointsByType"]["ore"][0]["x"], 1)
        finally:
            _OUTSIDE_CONVERTERS.clear()
            _OUTSIDE_CONVERTERS.update(old_converters)
            registry._OUTSIDE_CONVERTERS_DISCOVERED = old_discovered


if __name__ == "__main__":
    unittest.main()

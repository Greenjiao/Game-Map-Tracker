import argparse
import json
import math
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import update_roco_teleport_points as updater


def config(rows: dict) -> dict:
    return {"RocoDataRows": rows}


@dataclass(frozen=True)
class FakeTransform:
    side_length: float = 100.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    logical_size: int = 6144

    def convert(self, world_x: float, world_y: float) -> tuple[int, int]:
        scale = self.logical_size / self.side_length
        return (
            math.floor((world_x - self.offset_x) * scale + 0.5),
            math.floor((world_y - self.offset_y) * scale + 0.5),
        )


class FakeRocoModule:
    @staticmethod
    def get_scene_transform(_rows: dict, _scene_res_id: int):
        return FakeTransform(), 4010

    @staticmethod
    def parse_xyz(value):
        if not isinstance(value, list) or len(value) < 2:
            return None
        try:
            result = (float(value[0]), float(value[1]), float(value[2] if len(value) > 2 else 0))
        except (TypeError, ValueError):
            return None
        return result if all(math.isfinite(item) for item in result) else None

    @staticmethod
    def config_rejection_reasons(refresh, *, npc, location, rule, extra_text=None):
        reasons = []
        if refresh.get("disable") is True:
            reasons.append("disabled")
        if rule and rule.get("trigger_type") == 14:
            reasons.append("task_trigger_rule")
        note = " ".join(str(value or "") for value in (refresh.get("editor_name"), (npc or {}).get("editor_name"), (location or {}).get("editor_name"), extra_text))
        if "测试" in note:
            reasons.append("test_note")
        if "准备废弃" in note:
            reasons.append("deprecated_note")
        return reasons


def sample_annotation() -> dict:
    definitions = (
        ("5", "魔力之源", [(100, 101, "魔力之源")]),
        ("6", "炼金釜", [(200, 201, "炼金釜")]),
        ("7", "副本", [(300, 301, "测试副本")]),
        ("8", "稀兽花种", [(400, 401, "稀兽花种")]),
        ("9", "大型眠枭庇护所", [(500, 501, "大型眠枭庇护所·北区")]),
        ("10", "小型眠枭庇护所", [(600, 601, "小型眠枭庇护所·南区")]),
    )
    return {
        "types": [
            {"typeId": type_id, "type": name, "count": len(points)}
            for type_id, name, points in definitions
        ],
        "pointsByType": {
            type_id: [
                {"x": x, "y": y, "label": label, "typeId": type_id}
                for x, y, label in points
            ]
            for type_id, _name, points in definitions
        },
    }


def sample_game_configs() -> dict:
    return {
        "MEGAMAP_CONF": config(
            {
                "20": {"id": 20, "class": 3, "genre": "甲（首领战）"},
                "10": {"id": 10, "class": 3, "genre": "乙（首领战）"},
                "30": {"id": 30, "class": 2, "genre": "非首领（首领战）"},
            }
        ),
        "MEGAMAP_GATHERING_CONF": config(
            {
                "1": {"id": 1, "genre": "甲（首领战）", "index_method": 5, "param_id": 101},
                "2": {"id": 2, "genre": "乙（首领战）", "index_method": 5, "param_id": 102},
                "3": {"id": 3, "genre": "甲（首领战）", "index_method": 5, "param_id": 103},
                "4": {"id": 4, "genre": "甲（首领战）", "index_method": 5, "param_id": 104},
                "5": {"id": 5, "genre": "甲（首领战）", "index_method": 5, "param_id": 105},
                "6": {"id": 6, "genre": "甲（首领战）", "index_method": 5, "param_id": 106},
            }
        ),
        "NPC_REFRESH_CONTENT_CONF": config(
            {
                "101": {"id": 101, "npc_id": 1, "refresh_type": 1, "refresh_param": 201},
                "102": {"id": 102, "npc_id": 2, "refresh_type": 1, "refresh_param": 202},
                "103": {"id": 103, "npc_id": 3, "refresh_type": 1, "refresh_param": 203, "disable": True},
                "104": {"id": 104, "npc_id": 4, "refresh_type": 1, "refresh_param": 204},
                "105": {"id": 105, "npc_id": 5, "refresh_type": 1, "refresh_param": 205, "refresh_rule": 305},
                "106": {"id": 106, "npc_id": 6, "refresh_type": 1, "refresh_param": 206},
            }
        ),
        "NPC_REFRESH_RULE_CONF": config({"305": {"id": 305, "trigger_type": 14}}),
        "NPC_CONF": config({str(index): {"id": index} for index in range(1, 7)}),
        "AREA_CONF": config(
            {
                "201": {"id": 201, "scene_res_id": 10003, "pos": [{"position_xyz": [25, 50, 0]}]},
                "202": {"id": 202, "scene_res_id": 10003, "pos": [{"position_xyz": [10, 20, 0]}]},
                "203": {"id": 203, "scene_res_id": 10003, "pos": [{"position_xyz": [30, 30, 0]}]},
                "204": {"id": 204, "scene_res_id": 999, "pos": [{"position_xyz": [40, 40, 0]}]},
                "205": {"id": 205, "scene_res_id": 10003, "pos": [{"position_xyz": [50, 50, 0]}]},
                "206": {"id": 206, "scene_res_id": 10003, "pos": [{"position_xyz": ["bad", 10, 0]}]},
            }
        ),
        "WORLD_MAP_BLOCK_CONF": config({"1": {"id": 1}}),
    }


class UpdateRocoTeleportPointsTests(unittest.TestCase):
    def test_annotation_conversion_preserves_labels_and_merges_sanctuaries(self) -> None:
        payloads = updater.build_annotation_payloads(sample_annotation(), logical_map_size=8192)

        sanctuary = payloads["眠枭庇护所.json"]
        self.assertEqual(sanctuary["annotationTypes"], ["大型眠枭庇护所", "小型眠枭庇护所"])
        self.assertEqual([point["label"] for point in sanctuary["points"]], ["大型眠枭庇护所·北区", "小型眠枭庇护所·南区"])
        self.assertTrue(all(point["radius"] == 30 for point in sanctuary["points"]))
        self.assertIn("尚未人工校对", payloads["副本.json"]["notes"])

    def test_boss_chain_filters_invalid_rows_and_uses_8192_coordinates(self) -> None:
        points, excluded = updater.build_boss_points(
            sample_game_configs(),
            roco_module=FakeRocoModule,
            scene_res_id=10003,
            logical_map_size=8192,
        )

        self.assertEqual([point["label"] for point in points], ["首领·乙", "首领·甲"])
        self.assertEqual((points[0]["x"], points[0]["y"]), (819, 1638))
        self.assertEqual((points[1]["x"], points[1]["y"]), (2048, 4096))
        self.assertEqual(excluded["disabled"], 1)
        self.assertEqual(excluded["other_scene"], 1)
        self.assertEqual(excluded["task_trigger_rule"], 1)
        self.assertEqual(excluded["invalid_position"], 1)

    def test_dry_run_writes_nothing_and_normal_writes_identical_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            annotation_path = root / "annotation.json"
            annotation_path.write_text(json.dumps(sample_annotation(), ensure_ascii=False), encoding="utf-8")
            output_dir = root / "source"
            mirror_dir = root / "mirror"
            base_args = dict(
                annotation=annotation_path,
                game_root=root,
                roco_map_get_root=root,
                logical_map_size=8192,
                scene_res_id=10003,
                output_dir=output_dir,
                mirror_dir=[mirror_dir],
            )
            with patch.object(updater, "import_roco_exporter", return_value=FakeRocoModule), patch.object(
                updater, "load_game_configs", return_value=sample_game_configs()
            ):
                summary = updater.run(argparse.Namespace(**base_args, dry_run=True))
                self.assertTrue(summary["dry_run"])
                self.assertFalse(output_dir.exists())
                self.assertFalse(mirror_dir.exists())

                updater.run(argparse.Namespace(**base_args, dry_run=False))

            filenames = {spec["filename"] for spec in updater.ANNOTATION_EXPORTS} | {"BOSS（精灵首领）.json"}
            self.assertEqual({path.name for path in output_dir.glob("*.json")}, filenames)
            for filename in filenames:
                self.assertEqual((output_dir / filename).read_bytes(), (mirror_dir / filename).read_bytes())

    def test_duplicate_xy_across_sanctuary_types_is_rejected(self) -> None:
        annotation = sample_annotation()
        annotation["pointsByType"]["10"][0]["x"] = 500
        annotation["pointsByType"]["10"][0]["y"] = 501

        with self.assertRaisesRegex(ValueError, "Duplicate XY"):
            updater.build_annotation_payloads(annotation, logical_map_size=8192)


if __name__ == "__main__":
    unittest.main()

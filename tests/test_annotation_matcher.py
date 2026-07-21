import json
import tempfile
import unittest
from pathlib import Path

from ui_island.services.annotation_matcher import (
    AnnotationMatchIndex,
    default_teleport_type_ids_from_folder,
    suspicious_candidates,
)


class AnnotationMatcherTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "types": [
                {"typeId": "flower", "type": "花"},
                {"typeId": "ore", "type": "矿"},
                {"typeId": "teleport", "type": "魔力之源（传送点）"},
            ],
            "pointsByType": {
                "flower": [
                    {"x": 10, "y": 10, "label": "近花"},
                    {"x": 100, "y": 100, "label": "远花"},
                ],
                "ore": [{"x": 13, "y": 10, "label": "近矿"}],
                "teleport": [{"x": 50, "y": 50, "label": "传送"}],
            },
        }

    def test_find_candidates_returns_nearest_within_radius(self) -> None:
        matcher = AnnotationMatchIndex(self._payload())

        candidates = matcher.find_candidates(11, 10, ["flower", "ore"], max_radius=12)

        self.assertEqual([candidate.type_id for candidate in candidates], ["flower", "ore"])
        self.assertAlmostEqual(candidates[0].distance, 1.0)
        self.assertEqual(candidates[0].label, "近花")

    def test_find_candidates_filters_types_and_radius(self) -> None:
        matcher = AnnotationMatchIndex(self._payload())

        self.assertEqual(matcher.find_candidates(11, 10, ["teleport"], max_radius=12), [])
        self.assertEqual(matcher.find_candidates(11, 10, ["flower"], max_radius=0), [])

    def test_suspicious_candidates_uses_distance_delta_from_best(self) -> None:
        matcher = AnnotationMatchIndex(self._payload())
        candidates = matcher.find_candidates(11, 10, ["flower", "ore"], max_radius=12)

        suspicious = suspicious_candidates(candidates, distance_delta=5)

        self.assertEqual([candidate.type_id for candidate in suspicious], ["ore"])

    def test_default_teleport_type_ids_map_folder_names_to_annotation_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            annotation_file = root / "points.json"
            annotation_file.write_text(json.dumps(self._payload(), ensure_ascii=False), encoding="utf-8")
            teleport_dir = root / "teleport"
            teleport_dir.mkdir()
            (teleport_dir / "魔力之源（传送点）.json").write_text(
                json.dumps({"name": "ignored because filename is enough"}, ensure_ascii=False),
                encoding="utf-8",
            )

            type_ids = default_teleport_type_ids_from_folder(annotation_file, teleport_dir)

        self.assertEqual(type_ids, ["teleport"])

    def test_default_teleport_type_ids_accept_annotation_type_aliases(self) -> None:
        payload = {
            "types": [
                {"typeId": "5", "type": "魔力之源"},
                {"typeId": "6", "type": "炼金釜"},
                {"typeId": "9", "type": "大型眠枭庇护所"},
                {"typeId": "10", "type": "小型眠枭庇护所"},
                {"typeId": "legacy", "type": "旧文件名"},
            ],
            "pointsByType": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            annotation_file = root / "points.json"
            annotation_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            teleport_dir = root / "teleport"
            teleport_dir.mkdir()
            (teleport_dir / "炼金台.json").write_text(
                json.dumps(
                    {
                        "name": "炼金台",
                        "annotationTypes": ["炼金釜", 123, "", None],
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (teleport_dir / "眠枭庇护所.json").write_text(
                json.dumps(
                    {
                        "name": "眠枭庇护所",
                        "annotationTypes": ["大型眠枭庇护所", "小型眠枭庇护所"],
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (teleport_dir / "魔力之源（传送点）.json").write_text(
                json.dumps({"annotationTypes": ["魔力之源"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (teleport_dir / "旧文件名.json").write_text("{}", encoding="utf-8")

            type_ids = default_teleport_type_ids_from_folder(annotation_file, teleport_dir)

        self.assertEqual(type_ids, ["5", "6", "9", "10", "legacy"])

    def test_invalid_annotation_types_field_is_safely_ignored(self) -> None:
        payload = {
            "types": [{"typeId": "5", "type": "魔力之源"}],
            "pointsByType": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            annotation_file = root / "points.json"
            annotation_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            teleport_dir = root / "teleport"
            teleport_dir.mkdir()
            (teleport_dir / "unrelated.json").write_text(
                json.dumps({"annotationTypes": "魔力之源"}, ensure_ascii=False),
                encoding="utf-8",
            )

            type_ids = default_teleport_type_ids_from_folder(annotation_file, teleport_dir)

        self.assertEqual(type_ids, [])


if __name__ == "__main__":
    unittest.main()

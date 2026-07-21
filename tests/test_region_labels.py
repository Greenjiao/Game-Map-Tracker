import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import config
from config_defaults import DEFAULT_CONFIG
from ui_island.services import route_manager as rm
from ui_island.services.route_manager import RouteManager, _RegionLabel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S3_ANNOTATION_FILE = next((PROJECT_ROOT / "annotations").glob("*S3_8192.json"))


def _bare_manager(labels: list[_RegionLabel]) -> RouteManager:
    manager = RouteManager.__new__(RouteManager)
    manager._region_labels_cache = labels
    manager._annotation_coord_transform_cache = None
    return manager


def _solid_sprite(width: int = 10, height: int = 10) -> np.ndarray:
    sprite = np.zeros((height, width, 4), dtype=np.uint8)
    sprite[:, :, :3] = 255
    sprite[:, :, 3] = 255
    return sprite


class RegionLabelDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(S3_ANNOTATION_FILE.read_text(encoding="utf-8"))
        cls.labels = cls.payload["regionLabels"]

    def test_s3_region_labels_have_expected_counts_order_and_bounds(self) -> None:
        self.assertEqual(len(self.labels), 95)
        self.assertEqual(sum(item["scaleId"] == 3 for item in self.labels), 43)
        self.assertEqual(sum(item["scaleId"] == 4 for item in self.labels), 52)
        self.assertFalse(any(item["scaleId"] == 2 for item in self.labels))
        self.assertEqual(len({item["worldMapId"] for item in self.labels}), 95)
        self.assertEqual(
            self.labels,
            sorted(self.labels, key=lambda item: (item["scaleId"], item["worldMapId"])),
        )
        self.assertTrue(
            all(0 <= item["x"] <= 8192 and 0 <= item["y"] <= 8192 for item in self.labels)
        )

    def test_fixed_region_samples_match_ids_scales_and_coordinates(self) -> None:
        expected = {
            6: ("风息山口", 3, 2919, 4127),
            74: ("望风半岛", 3, 5742, 4683),
            8129: ("结晶森林", 3, 5952, 2883),
            8130: ("仪式镇", 3, 5251, 2340),
            8133: ("威廉古堡", 3, 4358, 2577),
            40: ("商店街西", 4, 2423, 5195),
            46: ("月影钓场", 4, 1978, 5273),
            85: ("巡鹰哨站", 4, 5053, 4118),
            87: ("下沉区", 4, 5232, 5621),
            94: ("黄金巷", 4, 5747, 3662),
        }
        by_id = {item["worldMapId"]: item for item in self.labels}
        for world_map_id, (name, scale_id, x, y) in expected.items():
            item = by_id[world_map_id]
            self.assertEqual(
                (item["name"], item["scaleId"], item["x"], item["y"]),
                (name, scale_id, x, y),
            )

    def test_region_label_config_defaults_and_source_config_are_present(self) -> None:
        source_config = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        expected = {
            "REGION_LABEL_MAJOR_VISIBLE": True,
            "REGION_LABEL_MINOR_VISIBLE": True,
            "REGION_LABEL_MAJOR_FONT_SIZE": 70,
            "REGION_LABEL_MINOR_FONT_SIZE": 40,
            "REGION_LABEL_SCALE_SWITCH_RATIO": 2.0,
            "ANNOTATION_LABEL_VISIBLE": False,
        }
        for key, value in expected.items():
            self.assertEqual(DEFAULT_CONFIG[key], value)
            self.assertIn(key, source_config)
            self.assertEqual(getattr(config, key), source_config[key])

        merged, _repaired = config.merge_config_payload(DEFAULT_CONFIG, {"CONFIG_VERSION": 5})
        self.assertEqual(merged["CONFIG_VERSION"], 5)
        for key, value in expected.items():
            self.assertEqual(merged[key], value)

    def test_removed_region_label_config_keys_are_pruned(self) -> None:
        source_config = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        merged, repaired = config.merge_config_payload(
            DEFAULT_CONFIG,
            {
                "CONFIG_VERSION": 5,
                "REGION_LABEL_VISIBLE": False,
                "REGION_LABEL_FONT_SIZE": 27,
            },
        )
        self.assertNotIn("REGION_LABEL_VISIBLE", DEFAULT_CONFIG)
        self.assertNotIn("REGION_LABEL_FONT_SIZE", DEFAULT_CONFIG)
        self.assertNotIn("REGION_LABEL_VISIBLE", source_config)
        self.assertNotIn("REGION_LABEL_FONT_SIZE", source_config)
        self.assertFalse(hasattr(config, "REGION_LABEL_VISIBLE"))
        self.assertFalse(hasattr(config, "REGION_LABEL_FONT_SIZE"))
        self.assertNotIn("REGION_LABEL_VISIBLE", merged)
        self.assertNotIn("REGION_LABEL_FONT_SIZE", merged)
        self.assertIn("REGION_LABEL_VISIBLE", repaired)
        self.assertIn("REGION_LABEL_FONT_SIZE", repaired)


class RegionLabelLoadingTests(unittest.TestCase):
    def test_missing_and_malformed_region_labels_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            annotation_file = Path(tmp) / "annotations.json"
            payload = {
                "types": [],
                "pointsByType": {},
                "regionLabels": [
                    {"worldMapId": 1, "name": "Valid", "x": 10, "y": 20, "scaleId": 3},
                    {"worldMapId": 2, "name": "", "x": 10, "y": 20, "scaleId": 3},
                    {"worldMapId": 3, "name": "Wrong scale", "x": 10, "y": 20, "scaleId": 2},
                    {"worldMapId": 4, "name": "Bad x", "x": "bad", "y": 20, "scaleId": 4},
                    {"worldMapId": "5", "name": "Bad id", "x": 10, "y": 20, "scaleId": 4},
                    "not an object",
                ],
            }
            annotation_file.write_text(json.dumps(payload), encoding="utf-8")
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch.object(rm, "_default_annotation_points_file", return_value=str(annotation_file)):
                labels = manager.region_labels()

            self.assertEqual(labels, [_RegionLabel(1, "Valid", (10.0, 20.0), 3)])

            payload.pop("regionLabels")
            annotation_file.write_text(json.dumps(payload), encoding="utf-8")
            manager.invalidate_annotation_cache()
            with patch.object(rm, "_default_annotation_points_file", return_value=str(annotation_file)):
                self.assertEqual(manager.region_labels(), [])

    def test_annotation_add_change_and_delete_preserve_region_labels_top_level_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            annotation_file = Path(tmp) / "annotations.json"
            region_labels = [
                {"worldMapId": 6, "name": "风息山口", "x": 2919, "y": 4127, "scaleId": 3}
            ]
            annotation_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {"typeId": "ore", "type": "Ore", "count": 0},
                            {"typeId": "flower", "type": "Flower", "count": 0},
                        ],
                        "pointsByType": {"ore": [], "flower": []},
                        "regionLabels": region_labels,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch.object(rm, "_default_annotation_points_file", return_value=str(annotation_file)):
                self.assertTrue(manager.add_annotation_point(10, 20, "ore", "Ore"))
                saved = json.loads(annotation_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["regionLabels"], region_labels)

                self.assertTrue(manager.change_annotation_point_type("ore", 0, "flower", "Flower"))
                saved = json.loads(annotation_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["regionLabels"], region_labels)

                self.assertTrue(manager.delete_annotation_point("flower", 0))
                saved = json.loads(annotation_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["regionLabels"], region_labels)


class RegionLabelRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        rm._REGION_LABEL_FONT_CACHE.clear()
        rm._REGION_LABEL_SPRITE_CACHE.clear()

    def tearDown(self) -> None:
        rm._REGION_LABEL_FONT_CACHE.clear()
        rm._REGION_LABEL_SPRITE_CACHE.clear()

    def _draw_with_ratio(
        self,
        ratio: float,
        *,
        major_visible: bool = True,
        minor_visible: bool = True,
    ) -> list[int]:
        manager = _bare_manager(
            [
                _RegionLabel(1, "large", (20.0, 20.0), 3),
                _RegionLabel(2, "detail", (80.0, 80.0), 4),
            ]
        )
        canvas = np.zeros((100, 100, 3), dtype=np.uint8)
        blit = Mock()
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", major_visible),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", minor_visible),
            patch.object(config, "REGION_LABEL_MAJOR_FONT_SIZE", 60),
            patch.object(config, "REGION_LABEL_MINOR_FONT_SIZE", 60),
            patch.object(config, "REGION_LABEL_SCALE_SWITCH_RATIO", 3.0),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite()),
            patch.object(rm, "_blit_bgra_topleft", blit),
        ):
            manager._draw_region_labels(canvas, 0, 0, 100, 100, map_pixels_per_screen_px=ratio)
        return [call.args[2] for call in blit.call_args_list]

    def test_scale_switch_has_no_gap_or_overlap_at_threshold(self) -> None:
        self.assertEqual(self._draw_with_ratio(3.001), [15])
        self.assertEqual(self._draw_with_ratio(3.0), [15])
        self.assertEqual(self._draw_with_ratio(2.999), [75])

    def test_independent_visibility_supports_all_four_checkbox_combinations(self) -> None:
        self.assertEqual(self._draw_with_ratio(1.0, major_visible=True, minor_visible=False), [15])
        self.assertEqual(self._draw_with_ratio(5.0, major_visible=False, minor_visible=True), [75])
        self.assertEqual(self._draw_with_ratio(1.0, major_visible=True, minor_visible=True), [75])
        self.assertEqual(self._draw_with_ratio(5.0, major_visible=True, minor_visible=True), [15])
        self.assertEqual(self._draw_with_ratio(1.0, major_visible=False, minor_visible=False), [])

    def test_visibility_switch_disables_region_labels(self) -> None:
        manager = _bare_manager([_RegionLabel(1, "hidden", (20.0, 20.0), 3)])
        canvas = np.zeros((50, 50, 3), dtype=np.uint8)
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", False),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", False),
            patch.object(rm, "_region_label_sprite") as sprite,
        ):
            manager._draw_region_labels(canvas, 0, 0, 50, 50, map_pixels_per_screen_px=3.0)
        sprite.assert_not_called()
        self.assertFalse(np.any(canvas))

    def test_font_size_and_stroke_scale_with_the_map(self) -> None:
        manager = _bare_manager([_RegionLabel(1, "sized", (40.0, 40.0), 3)])
        canvas = np.zeros((100, 100, 3), dtype=np.uint8)
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", False),
            patch.object(config, "REGION_LABEL_MAJOR_FONT_SIZE", 60),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite()) as sprite,
        ):
            manager._draw_region_labels(
                canvas,
                0,
                0,
                100,
                100,
                scale_x=0.5,
                scale_y=0.5,
                map_pixels_per_screen_px=3.0,
            )
            manager._draw_region_labels(
                canvas,
                0,
                0,
                100,
                100,
                scale_x=2.0,
                scale_y=2.0,
                map_pixels_per_screen_px=3.0,
            )
        self.assertEqual(
            [call.args for call in sprite.call_args_list],
            [("sized", 30, 3), ("sized", 120, 12)],
        )

    def test_minor_region_uses_its_own_map_relative_font_size(self) -> None:
        manager = _bare_manager([_RegionLabel(1, "minor sized", (20.0, 20.0), 4)])
        canvas = np.zeros((100, 100, 3), dtype=np.uint8)
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", False),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_FONT_SIZE", 50),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite()) as sprite,
        ):
            manager._draw_region_labels(
                canvas,
                0,
                0,
                100,
                100,
                scale_x=2.0,
                scale_y=2.0,
                map_pixels_per_screen_px=1.0,
            )
        sprite.assert_called_once_with("minor sized", 100, 10)

    def test_overlapping_region_labels_are_all_drawn_without_moving_source_coordinates(self) -> None:
        labels = [
            _RegionLabel(1, "first", (30.0, 30.0), 4),
            _RegionLabel(2, "overlap", (35.0, 30.0), 4),
            _RegionLabel(3, "separate", (80.0, 30.0), 4),
        ]
        manager = _bare_manager(labels)
        original_coordinates = [label.xy for label in labels]
        canvas = np.zeros((100, 100, 3), dtype=np.uint8)
        blit = Mock()
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_SCALE_SWITCH_RATIO", 3.0),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite(20, 10)),
            patch.object(rm, "_blit_bgra_topleft", blit),
        ):
            manager._draw_region_labels(canvas, 0, 0, 100, 100, map_pixels_per_screen_px=1.0)

        self.assertEqual(
            [(call.args[2], call.args[3]) for call in blit.call_args_list],
            [(20, 25), (25, 25), (70, 25)],
        )
        self.assertEqual([label.xy for label in labels], original_coordinates)

    def test_file_coordinate_transform_changes_only_rendered_position(self) -> None:
        label = _RegionLabel(1, "moved", (10.0, 15.0), 3)
        manager = _bare_manager([label])
        manager._annotation_coord_transform_cache = {
            "scale_x": 2.0,
            "scale_y": 1.0,
            "offset_x": 5.0,
            "offset_y": 10.0,
        }
        canvas = np.zeros((100, 100, 3), dtype=np.uint8)
        blit = Mock()
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", True),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite()),
            patch.object(rm, "_blit_bgra_topleft", blit),
        ):
            manager._draw_region_labels(canvas, 0, 0, 100, 100, map_pixels_per_screen_px=3.0)

        self.assertEqual((blit.call_args.args[2], blit.call_args.args[3]), (20, 20))
        self.assertEqual(label.xy, (10.0, 15.0))

    def test_partially_visible_label_is_clipped_at_canvas_edge(self) -> None:
        manager = _bare_manager([_RegionLabel(1, "edge", (1.0, 10.0), 3)])
        canvas = np.zeros((20, 20, 3), dtype=np.uint8)
        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", True),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite(10, 10)),
        ):
            manager._draw_region_labels(canvas, 0, 0, 20, 20, map_pixels_per_screen_px=3.0)
        self.assertTrue(np.any(canvas[:, :6]))

    def test_region_labels_draw_before_annotations_and_skip_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            canvas = np.zeros((20, 20, 3), dtype=np.uint8)
            order: list[str] = []
            with patch.object(
                manager, "_draw_region_labels", side_effect=lambda *_args, **_kwargs: order.append("region")
            ) as draw_regions, patch.object(
                manager, "_draw_annotations", side_effect=lambda *_args, **_kwargs: order.append("annotation")
            ) as draw_annotations:
                manager.draw_on(canvas, 0, 0, 20, skip_annotations=False)
                self.assertEqual(order, ["region", "annotation"])
                manager.draw_on(canvas, 0, 0, 20, skip_annotations=True)
                self.assertEqual(draw_regions.call_count, 1)
                self.assertEqual(draw_annotations.call_count, 1)

    def test_normal_annotation_icon_covers_region_label(self) -> None:
        manager = _bare_manager([_RegionLabel(1, "behind", (30.0, 30.0), 4)])
        manager._annotation_points_cache = {
            "ore": [{"x": 30, "y": 30, "typeId": "ore"}],
        }
        manager._annotation_spatial_index = None
        manager._annotation_type_ids = {"ore"}
        icon = np.zeros((10, 10, 4), dtype=np.uint8)
        icon[:, :, 1] = 255
        icon[:, :, 3] = 255
        manager._annotation_icon_cache = {"ore": icon}
        canvas = np.zeros((60, 60, 3), dtype=np.uint8)

        with (
            patch.object(config, "REGION_LABEL_MAJOR_VISIBLE", True),
            patch.object(config, "REGION_LABEL_MINOR_VISIBLE", True),
            patch.object(rm, "_region_label_sprite", return_value=_solid_sprite(20, 10)),
        ):
            manager._draw_region_labels(canvas, 0, 0, 60, 60, map_pixels_per_screen_px=1.0)
            manager._draw_annotations(
                canvas,
                0,
                0,
                60,
                60,
                map_pixels_per_screen_px=1.0,
            )

        self.assertEqual(tuple(canvas[30, 30]), (0, 255, 0))

    def test_bold_chinese_font_fallback_chain_is_safe(self) -> None:
        fallback = object()
        with patch.object(rm.ImageFont, "truetype", side_effect=OSError), patch.object(
            rm.ImageFont, "load_default", return_value=fallback
        ) as load_default:
            self.assertIs(rm._region_label_font(20), fallback)
        self.assertEqual(load_default.call_count, 1)

    def test_offscreen_chinese_sprite_is_cached_without_snapshot(self) -> None:
        first = rm._region_label_sprite("威廉古堡", 20, 2)
        second = rm._region_label_sprite("威廉古堡", 20, 2)
        self.assertIs(first, second)
        self.assertEqual(first.shape[2], 4)
        self.assertTrue(np.any(first[:, :, 3]))


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ui_island.services import resource_metadata
from ui_island.services.route_manager import (
    _GuideTarget,
    _config_opacity,
    _distance_to_segment,
    _guide_distance_label,
    _guide_target_for_player,
    _line_color_for_style,
    _load_teleport_points,
    _nearest_segment,
    _nearest_teleport_label,
    _nearest_unvisited_node,
    _route_color_from_hex,
    RouteManager,
    NODE_TYPE_COLLECT,
    NODE_TYPE_TELEPORT,
    NODE_TYPE_VIRTUAL,
)


def _is_13_digit_route_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 13 and value.isdigit()


def _manager_with_visible_route(base: Path, route_id: str = "2026010101") -> RouteManager:
    category = base / "category"
    category.mkdir()
    (category / "route.json").write_text(
        json.dumps(
            {
                "id": route_id,
                "name": "route",
                "points": [{"x": 10, "y": 10}, {"x": 80, "y": 80}],
            }
        ),
        encoding="utf-8",
    )
    manager = RouteManager(str(base))
    manager.visibility[route_id] = True
    return manager


class RouteGuideTests(unittest.TestCase):
    def test_route_color_uses_existing_multi_color_cache_when_enabled(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._color_cache = {"a": (1, 2, 3), "b": (4, 5, 6)}

        with patch("config.ROUTE_MULTI_COLOR_ENABLED", True):
            self.assertEqual(manager.color_for("a"), (1, 2, 3))
            self.assertEqual(manager.color_for("b"), (4, 5, 6))

    def test_route_color_uses_default_color_when_multi_color_disabled(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._color_cache = {"a": (1, 2, 3), "b": (4, 5, 6)}

        with patch("config.ROUTE_MULTI_COLOR_ENABLED", False), patch("config.ROUTE_DEFAULT_COLOR", "#1ad1ff"):
            self.assertEqual(manager.color_for("a"), (255, 209, 26))
            self.assertEqual(manager.color_for("b"), (255, 209, 26))

    def test_route_color_override_takes_priority_over_global_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            category = Path(tmp) / "category"
            category.mkdir()
            route_id = "1234567890123"
            (category / "route.json").write_text(
                json.dumps({
                    "id": route_id,
                    "name": "route",
                    "color": "#334455",
                    "points": [{"x": 1, "y": 2}],
                }),
                encoding="utf-8",
            )

            manager = RouteManager(tmp)

            with patch("config.ROUTE_MULTI_COLOR_ENABLED", True):
                self.assertEqual(manager.color_for(route_id), (0x55, 0x44, 0x33))
            with patch("config.ROUTE_MULTI_COLOR_ENABLED", False), patch("config.ROUTE_DEFAULT_COLOR", "#1ad1ff"):
                self.assertEqual(manager.color_for(route_id), (0x55, 0x44, 0x33))

    def test_route_without_color_override_keeps_default_color_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            category = Path(tmp) / "category"
            category.mkdir()
            route_id = "1234567890123"
            (category / "route.json").write_text(
                json.dumps({
                    "id": route_id,
                    "name": "route",
                    "points": [{"x": 1, "y": 2}],
                }),
                encoding="utf-8",
            )

            manager = RouteManager(tmp)

            with patch("config.ROUTE_MULTI_COLOR_ENABLED", False), patch("config.ROUTE_DEFAULT_COLOR", "#1ad1ff"):
                self.assertEqual(manager.color_for(route_id), (255, 209, 26))

    def test_update_route_notes_and_color_normalizes_and_resets_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            category = Path(tmp) / "category"
            category.mkdir()
            route_id = "1234567890123"
            path = category / "route.json"
            path.write_text(
                json.dumps({
                    "id": route_id,
                    "name": "route",
                    "notes": "",
                    "points": [{"x": 1, "y": 2}],
                }),
                encoding="utf-8",
            )
            manager = RouteManager(tmp)

            self.assertTrue(manager.update_route_notes_and_color("category", "route", "说明", "#AABBCC"))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["notes"], "说明")
            self.assertEqual(saved["color"], "#aabbcc")

            self.assertTrue(manager.update_route_notes_and_color("category", "route", "说明 2", None))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["notes"], "说明 2")
            self.assertNotIn("color", saved)

    def test_invalid_route_default_color_falls_back_to_blue(self) -> None:
        self.assertEqual(_route_color_from_hex("not-a-color"), (255, 209, 26))

    def test_special_line_colors_use_independent_defaults(self) -> None:
        route_color = (1, 2, 3)
        with (
            patch("config.ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", False),
            patch("config.ROUTE_TELEPORT_LINE_COLOR", "#112233"),
            patch("config.ROUTE_GUIDE_LINE_COLOR", "#445566"),
        ):
            self.assertEqual(_line_color_for_style(NODE_TYPE_COLLECT, route_color), route_color)
            self.assertEqual(_line_color_for_style(NODE_TYPE_TELEPORT, route_color), (0x33, 0x22, 0x11))
            self.assertEqual(_line_color_for_style(NODE_TYPE_VIRTUAL, route_color), (0x66, 0x55, 0x44))

    def test_special_line_colors_can_follow_route_color(self) -> None:
        route_color = (7, 8, 9)
        with patch("config.ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", True):
            self.assertEqual(_line_color_for_style(NODE_TYPE_TELEPORT, route_color), route_color)
            self.assertEqual(_line_color_for_style(NODE_TYPE_VIRTUAL, route_color), route_color)

    def test_pointer_arrow_color_is_independent(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        with patch("config.ROUTE_POINTER_ARROW_COLOR", "#010203"):
            self.assertEqual(manager.pointer_arrow_color(), (3, 2, 1))
        with patch("config.ROUTE_POINTER_ARROW_COLOR", "bad"):
            self.assertEqual(manager.pointer_arrow_color(), (0, 0, 0))

    def test_pointer_arrow_visibility_reads_config(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        with patch("config.ROUTE_POINTER_ARROW_VISIBLE", True):
            self.assertTrue(manager.pointer_arrow_visible())
        with patch("config.ROUTE_POINTER_ARROW_VISIBLE", False):
            self.assertFalse(manager.pointer_arrow_visible())

    def test_draw_on_skips_pointer_arrow_when_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager_with_visible_route(Path(tmp))
            manager.route_for_id("2026010101")["points"][0]["visited"] = True
            canvas = np.zeros((180, 180, 3), dtype=np.uint8)

            with (
                patch("config.ROUTE_POINTER_ARROW_VISIBLE", False),
                patch("ui_island.services.route_manager._draw_spaced_direction_arrows") as draw_arrows,
            ):
                manager.draw_on(canvas, 0, 0, 180, player_x=0, player_y=0, auto_visit=False)

            draw_arrows.assert_not_called()

    def test_draw_on_draws_pointer_arrow_when_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager_with_visible_route(Path(tmp))
            manager.route_for_id("2026010101")["points"][0]["visited"] = True
            canvas = np.zeros((180, 180, 3), dtype=np.uint8)

            with (
                patch("config.ROUTE_POINTER_ARROW_VISIBLE", True),
                patch("ui_island.services.route_manager._draw_spaced_direction_arrows") as draw_arrows,
            ):
                manager.draw_on(canvas, 0, 0, 180, player_x=0, player_y=0, auto_visit=False)

            draw_arrows.assert_called_once()

    def test_draw_on_route_nodes_use_numeric_order_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager_with_visible_route(Path(tmp))
            manager.route_for_id("2026010101")["points"][0]["label"] = "宝箱 99"
            canvas = np.zeros((180, 180, 3), dtype=np.uint8)

            with patch("cv2.putText", wraps=__import__("cv2").putText) as put_text:
                manager.draw_on(canvas, 0, 0, 180, auto_visit=False)

            labels = [call.args[1] for call in put_text.call_args_list]
            self.assertIn("1", labels)
            self.assertIn("2", labels)
            self.assertNotIn("宝箱 99", labels)

    def test_config_opacity_clamps_invalid_values(self) -> None:
        with patch("config.ROUTE_VISITED_ICON_OPACITY", 0.35):
            self.assertEqual(_config_opacity("ROUTE_VISITED_ICON_OPACITY", 1.0), 0.35)
        with patch("config.ROUTE_VISITED_ICON_OPACITY", 1.5):
            self.assertEqual(_config_opacity("ROUTE_VISITED_ICON_OPACITY", 0.35), 1.0)
        with patch("config.ROUTE_VISITED_ICON_OPACITY", -0.2):
            self.assertEqual(_config_opacity("ROUTE_VISITED_ICON_OPACITY", 0.35), 0.0)
        with patch("config.ROUTE_VISITED_ICON_OPACITY", "bad"):
            self.assertEqual(_config_opacity("ROUTE_VISITED_ICON_OPACITY", 0.35), 0.35)

    def test_distance_to_segment_projects_inside_segment(self) -> None:
        distance, projection = _distance_to_segment((5.0, 5.0), (0.0, 0.0), (10.0, 0.0))

        self.assertAlmostEqual(distance, 5.0)
        self.assertAlmostEqual(projection[0], 5.0)
        self.assertAlmostEqual(projection[1], 0.0)

    def test_nearest_unvisited_node_ignores_visited_points(self) -> None:
        routes = [
            {
                "points": [
                    {"x": 1, "y": 0, "visited": True},
                    {"x": 100, "y": 0, "visited": False},
                ],
            },
            {"points": [{"x": 12, "y": 9, "visited": False}]},
        ]

        result = _nearest_unvisited_node(routes, (0.0, 0.0))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[1], (12.0, 9.0))

    def test_segment_with_visited_start_targets_end_point(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": True},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (50.0, 5.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (100.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (50.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (100.0, 0.0))

    def test_unvisited_segment_targets_nearest_unvisited_node(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (5.0, 4.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (0.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (5.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (0.0, 0.0))

    def test_unvisited_segment_can_target_nearer_end_point(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (92.0, 4.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (100.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (92.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (100.0, 0.0))

    def test_segment_outside_snap_distance_falls_back_to_player_arrow(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": True},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (100.0, 50.0), 30.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (100.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (100.0, 50.0))
        self.assertEqual(target.arrow_target_xy, (100.0, 0.0))

    def test_strict_mode_targets_first_unvisited_node_on_current_segment(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": True},
                {"x": 100, "y": 0, "visited": False},
                {"x": 200, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (50.0, 5.0), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (100.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (50.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (100.0, 0.0))

    def test_strict_mode_uses_current_segment_endpoint_toward_first_unvisited(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 100, "y": 0, "visited": False},
                {"x": 200, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (150.0, 5.0), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (0.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (150.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (100.0, 0.0))

    def test_strict_mode_points_to_reachable_endpoint_on_later_segment(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 0, "y": 1, "visited": False},
                {"x": 0, "y": 3, "visited": False},
                {"x": 3, "y": 4, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (1.5, 3.5), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (0.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (1.5, 3.5))
        self.assertEqual(target.arrow_target_xy, (0.0, 3.0))

    def test_strict_mode_points_forward_when_first_unvisited_is_after_current_segment(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": True},
                {"x": 100, "y": 0, "visited": True},
                {"x": 200, "y": 0, "visited": False},
                {"x": 300, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (150.0, 5.0), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (200.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (150.0, 0.0))
        self.assertEqual(target.arrow_target_xy, (200.0, 0.0))

    def test_strict_mode_loop_chooses_shorter_route_distance(self) -> None:
        route = {
            "loop": True,
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 100, "y": 0, "visited": False},
                {"x": 51, "y": 10, "visited": False},
                {"x": 0, "y": 1, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (75.5, 5.0), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (0.0, 0.0))
        self.assertEqual(target.arrow_start_xy, (75.5, 5.0))
        self.assertEqual(target.arrow_target_xy, (51.0, 10.0))

    def test_strict_mode_loop_tie_is_stable(self) -> None:
        route = {
            "loop": True,
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 1, "y": 0, "visited": False},
                {"x": 0, "y": 1, "visited": False},
            ],
        }

        first = _guide_target_for_player([route], (0.5, 0.5), 80.0, 10.0, strict_mode=True)
        second = _guide_target_for_player([route], (0.5, 0.5), 80.0, 10.0, strict_mode=True)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.arrow_target_xy, (1.0, 0.0))
        self.assertEqual(second.arrow_target_xy, first.arrow_target_xy)

    def test_visited_segment_end_falls_back_to_nearest_unvisited_node(self) -> None:
        routes = [
            {
                "points": [
                    {"x": 0, "y": 0, "visited": True},
                    {"x": 100, "y": 0, "visited": True},
                    {"x": 200, "y": 0, "visited": False},
                ],
            },
        ]

        target = _guide_target_for_player(routes, (50.0, 5.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (200.0, 0.0))

    def test_nearest_segment_includes_loop_closing_segment(self) -> None:
        route = {
            "loop": True,
            "points": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 0, "y": 100},
            ],
        }

        result = _nearest_segment([route], (4.0, 50.0), 10.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[2], 2)
        self.assertEqual(result[3], 0)
        self.assertEqual(result[6], (0.0, 50.0))

    def test_distance_label_hidden_when_target_is_visible(self) -> None:
        target = _GuideTarget((75.0, 50.0), 75.0)

        label = _guide_distance_label(target, vx1=0, vy1=0, width=100, height=100)

        self.assertIsNone(label)

    def test_edges_route_uses_nodes_as_runtime_points_without_writing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "其他"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            payload = {
                "name": "edge-route",
                "points": [{"x": 999, "y": 999, "label": "legacy"}],
                "nodes": [
                    {"id": "a", "x": 10, "y": 20, "node_type": "collect"},
                    {"id": "b", "x": 30, "y": 40, "node_type": "virtual"},
                ],
                "edges": [
                    {"id": "e1", "from": "a", "to": "b", "edge_type": "virtual"},
                ],
            }
            source.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            before = source.read_text(encoding="utf-8")

            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")

            self.assertEqual(source.read_text(encoding="utf-8"), before)
            self.assertEqual([(point["x"], point["y"], point["node_type"]) for point in route["points"]], [
                (10, 20, "collect"),
                (30, 40, "virtual"),
            ])

            route_id = manager.route_id(route)
            self.assertTrue(manager.set_point_annotation(route_id, 1, "ore", "矿石"))
            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(saved["points"], payload["points"])
            self.assertEqual(saved["nodes"][1]["typeId"], "ore")
            self.assertEqual(saved["nodes"][1]["type"], "矿石")

    def test_edges_route_without_points_writes_node_edits_to_nodes_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "其他"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            source.write_text(
                json.dumps(
                    {
                        "name": "edge-route",
                        "nodes": [
                            {"id": "a", "x": 10, "y": 20},
                            {"id": "b", "x": 30, "y": 40},
                        ],
                        "edges": [
                            {"id": "e1", "from": "a", "to": "b", "edge_type": "normal"},
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")
            route_id = manager.route_id(route)

            self.assertTrue(manager.set_point_annotation(route_id, 0, "ore", "矿石"))
            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertNotIn("points", saved)
            self.assertEqual(saved["nodes"][0]["typeId"], "ore")
            self.assertEqual(saved["nodes"][0]["type"], "矿石")

    def test_distance_label_shown_when_target_is_outside_crop(self) -> None:
        target = _GuideTarget((180.0, 50.0), 180.2)

        label = _guide_distance_label(target, vx1=0, vy1=0, width=100, height=100)

        self.assertEqual(label, "180px")

    def test_distance_label_uses_map_coordinate_distance(self) -> None:
        target = _GuideTarget((250.0, 120.0), 130.6)

        label = _guide_distance_label(target, vx1=200, vy1=100, width=40, height=40)

        self.assertEqual(label, "131px")

    def test_distance_label_hidden_without_target(self) -> None:
        label = _guide_distance_label(None, vx1=0, vy1=0, width=100, height=100)

        self.assertIsNone(label)

    def test_load_teleport_points_from_route_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.json").write_text(
                json.dumps(
                    {
                        "name": "传送",
                        "points": [
                            {"x": 10, "y": 20, "label": "港口"},
                            {"x": 30, "y": 40, "label": "农庄"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            points = _load_teleport_points(folder)

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].xy, (10.0, 20.0))
        self.assertEqual(points[0].label, "港口")
        self.assertEqual(points[1].label, "农庄")

    def test_nearest_teleport_label_uses_target_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.json").write_text(
                json.dumps(
                    {
                        "points": [
                            {"x": 0, "y": 0, "label": "远处"},
                            {"x": 95, "y": 105, "label": "最近传送点"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            points = _load_teleport_points(folder)

        label = _nearest_teleport_label(points, (100.0, 100.0))

        self.assertEqual(label, "最近传送点")

    def test_load_teleport_points_tolerates_missing_invalid_and_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bad.json").write_text("{not json", encoding="utf-8")
            (folder / "empty.json").write_text(
                json.dumps({"points": []}),
                encoding="utf-8",
            )
            (folder / "partial.json").write_text(
                json.dumps({"points": [{"x": 1}, {"x": "bad", "y": 2}]}),
                encoding="utf-8",
            )

            points = _load_teleport_points(folder)

        self.assertEqual(points, [])
        self.assertEqual(_load_teleport_points(Path(tmp) / "missing"), [])
        self.assertIsNone(_nearest_teleport_label([], (0.0, 0.0)))

    def test_set_point_visited_updates_progress_without_rewriting_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertFalse(manager.point_visited("2026010101", 1))
            self.assertTrue(manager.set_point_visited("2026010101", 1, True))
            self.assertTrue(manager.point_visited("2026010101", 1))
            progress = json.loads((base / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress, {"2026010101": [1]})
            route_payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("visited", route_payload["points"][1])

            self.assertTrue(manager.set_point_visited("2026010101", 1, False))
            self.assertFalse(manager.point_visited("2026010101", 1))
            self.assertEqual(json.loads((base / "progress.json").read_text(encoding="utf-8")), {})

    def test_set_point_position_writes_coordinates_and_preserves_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "route",
                        "points": [
                            {
                                "id": "node-1",
                                "x": 1,
                                "y": 2,
                                "typeId": "flower",
                                "type": "Flower",
                                "node_type": "teleport",
                                "visited": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_position("2026010101", 0, 10.2, 20.6))

            point = manager.route_for_id("2026010101")["points"][0]
            self.assertEqual((point["x"], point["y"]), (10, 21))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            saved = payload["points"][0]
            self.assertEqual(saved["id"], "node-1")
            self.assertEqual(saved["typeId"], "flower")
            self.assertEqual(saved["type"], "Flower")
            self.assertEqual(saved["node_type"], "teleport")
            self.assertEqual((saved["x"], saved["y"]), (10, 21))
            self.assertNotIn("visited", saved)

    def test_save_route_preserves_format_version_and_appends_current_enable_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "format_version": "old-format",
                        "enable_versions": ["old-format"],
                        "name": "route",
                        "points": [{"x": 1, "y": 2}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_position("2026010101", 0, 10, 20))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], "old-format")
            self.assertEqual(payload["enable_versions"], ["old-format", resource_metadata.APP_FORMAT_VERSION])

    def test_save_existing_route_does_not_create_missing_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "enable_versions": ["old-format"],
                        "name": "route",
                        "points": [{"x": 1, "y": 2}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_position("2026010101", 0, 10, 20))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("format_version", payload)
            self.assertEqual(payload["enable_versions"], ["old-format", resource_metadata.APP_FORMAT_VERSION])

    def test_update_route_enable_versions_respects_manual_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "format_version": "old-format",
                        "enable_versions": ["old-format", resource_metadata.APP_FORMAT_VERSION],
                        "name": "route",
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.update_route_enable_versions("2026010101", ["old-format"]))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], "old-format")
            self.assertEqual(payload["enable_versions"], ["old-format"])

    def test_update_route_enable_versions_keeps_empty_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "format_version": "old-format",
                        "enable_versions": ["old-format"],
                        "name": "route",
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.update_route_enable_versions("2026010101", []))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["format_version"], "old-format")
            self.assertEqual(payload["enable_versions"], ["old-format"])

    def test_update_route_enable_versions_keeps_empty_array_without_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "enable_versions": ["old-format"],
                        "name": "route",
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.update_route_enable_versions("2026010101", []))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("format_version", payload)
            self.assertEqual(payload["enable_versions"], [])

    def test_route_enable_versions_uses_format_version_when_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            (category / "route.json").write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "format_version": "old-format",
                        "name": "route",
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertEqual(manager.route_enable_versions("2026010101"), ["old-format"])

    def test_route_and_annotation_warnings_only_check_current_enable_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            (category / "missing.json").write_text(
                json.dumps({"id": "2026010101", "name": "missing", "points": []}),
                encoding="utf-8",
            )
            (category / "unsupported.json").write_text(
                json.dumps(
                    {"id": "2026010102", "name": "unsupported", "enable_versions": ["old-format"], "points": []},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            warnings = manager.route_metadata_warnings()

            self.assertEqual(len(warnings), 1)
            self.assertIn("unsupported", warnings[0])

            missing_annotation = base / "missing_annotation.json"
            missing_annotation.write_text(json.dumps({"types": [], "pointsByType": {}}), encoding="utf-8")
            unsupported_annotation = base / "unsupported_annotation.json"
            unsupported_annotation.write_text(
                json.dumps(
                    {"enable_versions": ["old-format"], "types": [], "pointsByType": {}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("config.selected_annotation_file_from_settings", return_value="missing_annotation.json"), patch(
                "config.selected_annotation_path_from_settings", return_value=str(missing_annotation)
            ):
                self.assertEqual(manager.annotation_metadata_warnings(), [])
            with patch("config.selected_annotation_file_from_settings", return_value="unsupported_annotation.json"), patch(
                "config.selected_annotation_path_from_settings", return_value=str(unsupported_annotation)
            ):
                annotation_warnings = manager.annotation_metadata_warnings()

            self.assertEqual(len(annotation_warnings), 1)
            self.assertIn("unsupported_annotation.json", annotation_warnings[0])

    def test_set_point_position_preview_updates_memory_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps({"id": "2026010101", "name": "route", "points": [{"x": 1, "y": 2}]}),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_position("2026010101", 0, 7, 8, persist=False))

            self.assertEqual(manager.route_for_id("2026010101")["points"][0]["x"], 7)
            self.assertEqual(manager.route_for_id("2026010101")["points"][0]["y"], 8)
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_set_point_position_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps({"id": "2026010101", "name": "route", "points": [{"x": 1, "y": 2}]}),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.set_point_position("missing", 0, 7, 8))
            self.assertFalse(manager.set_point_position("2026010101", 9, 7, 8))
            self.assertFalse(manager.set_point_position("2026010101", 0, "bad", 8))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_set_point_position_rolls_back_memory_when_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            (category / "route.json").write_text(
                json.dumps({"id": "2026010101", "name": "route", "points": [{"x": 1, "y": 2}]}),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            with patch.object(manager, "_write_route_file", side_effect=RuntimeError("boom")):
                self.assertFalse(manager.set_point_position("2026010101", 0, 7, 8))

            self.assertEqual(manager.route_for_id("2026010101")["points"][0]["x"], 1)
            self.assertEqual(manager.route_for_id("2026010101")["points"][0]["y"], 2)

    def test_set_point_position_writes_external_nodes_without_overwriting_legacy_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "other"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            legacy_points = [{"x": 999, "y": 999, "label": "legacy"}]
            source.write_text(
                json.dumps(
                    {
                        "name": "edge-route",
                        "points": legacy_points,
                        "nodes": [{"id": "a", "x": 10, "y": 20}, {"id": "b", "x": 30, "y": 40}],
                        "edges": [{"id": "e1", "from": "a", "to": "b", "edge_type": "virtual"}],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")
            route_id = manager.route_id(route)

            self.assertTrue(manager.set_point_position(route_id, 1, 70, 80))

            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual((saved["nodes"][1]["x"], saved["nodes"][1]["y"]), (70, 80))
            self.assertEqual(saved["points"], legacy_points)

    def test_point_visited_rejects_invalid_route_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            (category / "路线.json").write_text(
                json.dumps({"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2}]}),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertIsNone(manager.point_visited("missing", 0))
            self.assertIsNone(manager.point_visited("2026010101", 9))
            self.assertFalse(manager.set_point_visited("missing", 0, True))
            self.assertFalse(manager.set_point_visited("2026010101", 9, True))

    def test_draw_on_can_skip_auto_visit_for_manual_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager_with_visible_route(Path(tmp))
            canvas = np.zeros((120, 120, 3), dtype=np.uint8)

            manager.draw_on(canvas, 0, 0, 120, player_x=10, player_y=10, auto_visit=False)

            self.assertFalse(manager.point_visited("2026010101", 0))

    def test_draw_on_auto_visit_marks_nearby_route_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager_with_visible_route(Path(tmp))
            canvas = np.zeros((120, 120, 3), dtype=np.uint8)

            manager.draw_on(canvas, 0, 0, 120, player_x=10, player_y=10, auto_visit=True)

            self.assertTrue(manager.point_visited("2026010101", 0))

    def test_route_point_annotation_detection_accepts_type_or_type_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            (category / "路线.json").write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {"x": 1, "y": 2},
                            {"x": 3, "y": 4, "typeId": "flower"},
                            {"x": 5, "y": 6, "type": "矿石"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertFalse(manager.route_point_has_annotation("2026010101", 0))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 1))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 2))
            self.assertFalse(manager.route_point_has_annotation("2026010101", 9))

    def test_set_point_annotation_writes_type_fields_to_route_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2, "visited": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_annotation("2026010101", 0, "flower", "向阳花"))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 0))
            self.assertEqual(manager.route_point_annotation_type_id("2026010101", 0), "flower")
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["typeId"], "flower")
            self.assertEqual(payload["points"][0]["type"], "向阳花")
            self.assertEqual(payload["points"][0]["label"], "向阳花 1")
            self.assertNotIn("visited", payload["points"][0])

    def test_set_point_annotation_can_update_node_type_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2, "node_type": "virtual"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_annotation("2026010101", 0, "flower", "向阳花", node_type="collect"))

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["typeId"], "flower")
            self.assertEqual(payload["points"][0]["node_type"], "collect")

    def test_set_point_annotation_rolls_back_node_type_on_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2, "node_type": "virtual"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            with patch.object(manager, "_write_route_file", side_effect=RuntimeError("boom")):
                self.assertFalse(manager.set_point_annotation("2026010101", 0, "flower", "向阳花", node_type="collect"))

            point = manager.route_for_id("2026010101")["points"][0]
            self.assertNotIn("typeId", point)
            self.assertEqual(point["node_type"], "virtual")

    def test_route_point_mutations_refresh_auto_labels_without_overwriting_manual_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {"x": 1, "y": 2, "label": "宝箱 9", "typeId": "chest", "type": "宝箱"},
                            {"x": 3, "y": 4, "label": "手写", "typeId": "ore", "type": "矿石"},
                            {"x": 5, "y": 6, "node_type": "teleport"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_annotation("2026010101", 1, "chest", "宝箱"))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual([point.get("label") for point in payload["points"]], ["宝箱 1", "手写", "传送点 1"])

            self.assertTrue(manager.clear_point_annotation("2026010101", 0))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual([point.get("label") for point in payload["points"]], ["节点 1", "手写", "传送点 1"])

            self.assertTrue(manager.reorder_route_point("2026010101", 2, 0))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual([point.get("label") for point in payload["points"]], ["传送点 1", "节点 2", "手写"])

            outcomes = manager.delete_points_from_routes({"2026010101": [1]})
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(outcomes["2026010101"], [1])
            self.assertEqual([point.get("label") for point in payload["points"]], ["传送点 1", "手写"])

    def test_save_route_points_writes_loop_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "loop": False,
                        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))
            points = manager.route_for_id("2026010101")["points"]

            self.assertTrue(manager.save_route_points("2026010101", points, loop=True))
            self.assertTrue(json.loads(route_file.read_text(encoding="utf-8"))["loop"])

            self.assertTrue(manager.save_route_points("2026010101", points, loop=False))
            self.assertFalse(json.loads(route_file.read_text(encoding="utf-8"))["loop"])

    def test_save_route_points_preserves_progress_in_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))
            points = manager.route_for_id("2026010101")["points"]
            points[1]["visited"] = True
            points[0]["label"] = "起点"

            self.assertTrue(manager.save_route_points("2026010101", points))

            route_payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("visited", route_payload["points"][1])
            self.assertEqual(json.loads((base / "progress.json").read_text(encoding="utf-8")), {"2026010101": [1]})
            self.assertTrue(manager.point_visited("2026010101", 1))

    def test_save_route_points_auto_labels_missing_and_typed_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps({"id": "2026010101", "name": "路线", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(
                manager.save_route_points(
                    "2026010101",
                    [
                        {"x": 1, "y": 2, "typeId": "flower", "type": "向阳花"},
                        {"x": 3, "y": 4, "typeId": "flower", "type": "向阳花"},
                        {"x": 5, "y": 6, "node_type": "collect"},
                        {"x": 7, "y": 8, "label": "手写名", "node_type": "collect"},
                        {"x": 9, "y": 10},
                    ],
                )
            )

            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(
                [point.get("label") for point in payload["points"]],
                ["向阳花 1", "向阳花 2", "采集点 1", "手写名", "节点 5"],
            )
            self.assertFalse(any("display_order" in point for point in payload["points"]))

    def test_set_point_annotation_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.set_point_annotation("missing", 0, "flower", "向阳花"))
            self.assertFalse(manager.set_point_annotation("2026010101", 9, "flower", "向阳花"))
            self.assertFalse(manager.set_point_annotation("2026010101", 0, "", "向阳花"))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_set_point_node_type_writes_supported_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "route",
                        "points": [{"x": 1, "y": 2, "visited": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            for node_type in ("teleport", "virtual", "collect"):
                self.assertTrue(manager.set_point_node_type("2026010101", 0, node_type))
                payload = json.loads(route_file.read_text(encoding="utf-8"))
                self.assertEqual(payload["points"][0]["node_type"], node_type)
                self.assertNotIn("visited", payload["points"][0])

    def test_set_point_node_type_defaults_missing_or_invalid_to_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "route",
                        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4, "node_type": "bad"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_node_type("2026010101", 0, ""))
            self.assertTrue(manager.set_point_node_type("2026010101", 1, "bad"))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["node_type"], "collect")
            self.assertEqual(payload["points"][1]["node_type"], "collect")

    def test_set_point_node_type_writes_external_nodes_without_overwriting_legacy_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "other"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            legacy_points = [{"x": 999, "y": 999, "label": "legacy"}]
            source.write_text(
                json.dumps(
                    {
                        "name": "edge-route",
                        "points": legacy_points,
                        "nodes": [
                            {"id": "a", "x": 10, "y": 20},
                            {"id": "b", "x": 30, "y": 40, "node_type": "collect"},
                        ],
                        "edges": [
                            {"id": "e1", "from": "a", "to": "b", "edge_type": "virtual"},
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")
            route_id = manager.route_id(route)

            self.assertTrue(manager.set_point_node_type(route_id, 0, "teleport"))
            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(saved["nodes"][0]["node_type"], "teleport")
            self.assertEqual(saved["points"], legacy_points)

    def test_set_point_node_type_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {"id": "2026010101", "name": "route", "points": [{"x": 1, "y": 2}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.set_point_node_type("missing", 0, "teleport"))
            self.assertFalse(manager.set_point_node_type("2026010101", 9, "teleport"))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_clear_point_annotation_removes_type_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {
                                "x": 1,
                                "y": 2,
                                "label": "节点",
                                "radius": 30,
                                "typeId": "flower",
                                "type": "向阳花",
                                "visited": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.clear_point_annotation("2026010101", 0))
            self.assertFalse(manager.route_point_has_annotation("2026010101", 0))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            point = payload["points"][0]
            self.assertNotIn("typeId", point)
            self.assertNotIn("type", point)
            self.assertEqual(point["label"], "节点")
            self.assertEqual(point["radius"], 30)
            self.assertNotIn("visited", point)

    def test_clear_point_annotation_handles_partial_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {"x": 1, "y": 2, "typeId": "flower"},
                            {"x": 3, "y": 4, "type": "矿石"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.clear_point_annotation("2026010101", 0))
            self.assertTrue(manager.clear_point_annotation("2026010101", 1))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("typeId", payload["points"][0])
            self.assertNotIn("type", payload["points"][0])
            self.assertNotIn("typeId", payload["points"][1])
            self.assertNotIn("type", payload["points"][1])

    def test_clear_point_annotation_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2, "typeId": "flower"}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.clear_point_annotation("missing", 0))
            self.assertFalse(manager.clear_point_annotation("2026010101", 9))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_add_annotation_point_appends_point_and_updates_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {
                                "typeId": "flower",
                                "type": "Sunflower",
                                "group": "Collect",
                                "groupId": "1",
                                "count": 1,
                            }
                        ],
                        "pointsByType": {
                            "flower": [{"x": 1, "y": 2, "label": "old", "type": "Sunflower", "typeId": "flower"}]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"flower": []}

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.add_annotation_point(10, 20, "flower", "Sunflower"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            points = payload["pointsByType"]["flower"]
            self.assertEqual(len(points), 2)
            self.assertEqual(payload["types"][0]["count"], 2)
            self.assertEqual(points[-1]["x"], 10)
            self.assertEqual(points[-1]["y"], 20)
            self.assertEqual(points[-1]["label"], "Sunflower")
            self.assertEqual(points[-1]["type"], "Sunflower")
            self.assertEqual(points[-1]["typeId"], "flower")
            self.assertTrue(points[-1]["manual"])
            self.assertIsNone(manager._annotation_points_cache)

    def test_add_annotation_point_creates_missing_points_bucket_for_known_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "ore", "type": "Ore", "group": "Ore", "count": 0}],
                        "pointsByType": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.add_annotation_point(3, 4, "ore", "Ore"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 1)
            self.assertEqual(payload["pointsByType"]["ore"][0]["typeId"], "ore")

    def test_add_annotation_point_rejects_invalid_type_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 0}],
                        "pointsByType": {"flower": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = points_file.read_text(encoding="utf-8")
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertFalse(manager.add_annotation_point(10, 20, "", "Sunflower"))
                self.assertFalse(manager.add_annotation_point(10, 20, "missing", "Missing"))
            self.assertEqual(points_file.read_text(encoding="utf-8"), before)

    def test_add_annotation_point_rejects_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            missing_file = Path(tmp) / "missing.json"

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(missing_file)):
                self.assertFalse(manager.add_annotation_point(10, 20, "flower", "Sunflower"))

    def test_hit_test_annotation_point_returns_raw_points_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 2}],
                        "pointsByType": {
                            "flower": [
                                {"x": "bad", "y": 2},
                                {"x": 100, "y": 100, "typeId": "flower"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager.set_annotation_type_ids(["flower"])

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                hit = manager.hit_test_annotation_point(102, 101, 5)

            self.assertIsNotNone(hit)
            self.assertEqual(hit["typeId"], "flower")
            self.assertEqual(hit["pointIndex"], 1)

    def test_annotation_spatial_index_filters_visible_rect_and_invalidates(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._annotation_points_cache = {
            "flower": [
                {"x": 10, "y": 10, "typeId": "flower"},
                {"x": 500, "y": 500, "typeId": "flower"},
            ],
            "ore": [{"x": 20, "y": 20, "typeId": "ore"}],
        }
        manager._annotation_spatial_index = None
        manager._annotation_icon_cache = {}
        manager._point_icon_cache = {}
        manager._point_icon_index = None
        manager._annotation_type_ids = {"flower"}

        entries = manager._annotation_entries_in_rect(0, 0, 100, 100)

        self.assertEqual([(entry.type_id, entry.point_index) for entry in entries], [("flower", 0)])
        self.assertIsNotNone(manager._annotation_spatial_index)

        manager.invalidate_annotation_cache()

        self.assertIsNone(manager._annotation_points_cache)
        self.assertIsNone(manager._annotation_spatial_index)

    def test_draw_annotations_clusters_far_zoom_overlapping_points(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._annotation_points_cache = {
            "flower": [
                {"x": 100, "y": 100, "typeId": "flower"},
                {"x": 110, "y": 108, "typeId": "flower"},
            ]
        }
        manager._annotation_spatial_index = None
        manager._annotation_type_ids = {"flower"}
        manager._annotation_icon_cache = {"flower": np.full((20, 20, 4), 255, dtype=np.uint8)}
        canvas = np.zeros((120, 120, 3), dtype=np.uint8)

        manager._draw_annotations(
            canvas,
            0,
            0,
            120,
            120,
            viewport_width=480,
            viewport_height=480,
            scale_x=0.25,
            scale_y=0.25,
            map_pixels_per_screen_px=4.0,
        )

        self.assertTrue(np.any(canvas))
        self.assertGreater(canvas[26, 26].sum(), 0)

    def test_draw_annotations_near_zoom_draws_single_icons(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._annotation_points_cache = {
            "flower": [
                {"x": 20, "y": 20, "typeId": "flower"},
                {"x": 90, "y": 90, "typeId": "flower"},
            ]
        }
        manager._annotation_spatial_index = None
        manager._annotation_type_ids = {"flower"}
        icon = np.zeros((20, 20, 4), dtype=np.uint8)
        icon[:, :, 1] = 255
        icon[:, :, 3] = 255
        manager._annotation_icon_cache = {"flower": icon}
        canvas = np.zeros((120, 120, 3), dtype=np.uint8)

        manager._draw_annotations(
            canvas,
            0,
            0,
            120,
            120,
            viewport_width=120,
            viewport_height=120,
            scale_x=1.0,
            scale_y=1.0,
            map_pixels_per_screen_px=1.0,
        )

        self.assertEqual(int(canvas[20, 20, 1]), 255)
        self.assertEqual(int(canvas[90, 90, 1]), 255)

    def test_hit_test_annotation_point_uses_spatial_index_and_returns_nearest(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._annotation_points_cache = {
            "flower": [
                {"x": 100, "y": 100, "typeId": "flower"},
                {"x": 104, "y": 103, "typeId": "flower"},
                {"x": 900, "y": 900, "typeId": "flower"},
            ]
        }
        manager._annotation_spatial_index = None
        manager._annotation_type_ids = {"flower"}

        hit = manager.hit_test_annotation_point(105, 104, 8)

        self.assertIsNotNone(hit)
        self.assertEqual(hit["pointIndex"], 1)

    def test_change_annotation_point_type_moves_point_and_updates_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {"typeId": "flower", "type": "Sunflower", "count": 1},
                            {"typeId": "ore", "type": "Ore", "count": 0},
                        ],
                        "pointsByType": {
                            "flower": [{"x": 1, "y": 2, "label": "Keep Label", "sourceId": 7}],
                            "ore": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"flower": []}

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.change_annotation_point_type("flower", 0, "ore", "Ore"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 0)
            self.assertEqual(payload["types"][1]["count"], 1)
            self.assertEqual(payload["pointsByType"]["flower"], [])
            moved = payload["pointsByType"]["ore"][0]
            self.assertEqual(moved["x"], 1)
            self.assertEqual(moved["y"], 2)
            self.assertEqual(moved["label"], "Keep Label")
            self.assertEqual(moved["sourceId"], 7)
            self.assertEqual(moved["typeId"], "ore")
            self.assertEqual(moved["type"], "Ore")
            self.assertTrue(moved["manual"])
            self.assertIsNone(manager._annotation_points_cache)

    def test_change_annotation_point_type_marks_same_type_edit_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 1}],
                        "pointsByType": {
                            "flower": [{"x": 1, "y": 2, "typeId": "flower", "type": "Old Name"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.change_annotation_point_type("flower", 0, "flower", "Sunflower"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            point = payload["pointsByType"]["flower"][0]
            self.assertEqual(point["typeId"], "flower")
            self.assertEqual(point["type"], "Sunflower")
            self.assertTrue(point["manual"])

    def test_delete_annotation_point_removes_point_and_updates_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 2}],
                        "pointsByType": {
                            "flower": [
                                {"x": 1, "y": 2, "label": "A"},
                                {"x": 3, "y": 4, "label": "B"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.delete_annotation_point("flower", 0))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 1)
            self.assertEqual(len(payload["pointsByType"]["flower"]), 1)
            self.assertEqual(payload["pointsByType"]["flower"][0]["label"], "B")

    def test_insert_annotation_point_into_route_preserves_type_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps({"id": "2026010101", "name": "route", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            outcomes = manager.insert_point_into_routes(
                10,
                20,
                ["2026010101"],
                point_fields={"typeId": "flower", "type": "Sunflower", "label": "Field Flower", "visited": True},
            )

            self.assertEqual(outcomes["2026010101"], 0)
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            point = payload["points"][0]
            self.assertEqual(point["x"], 10)
            self.assertEqual(point["y"], 20)
            self.assertEqual(point["typeId"], "flower")
            self.assertEqual(point["type"], "Sunflower")
            self.assertEqual(point["label"], "Field Flower")
            self.assertNotIn("visited", point)

    def test_insert_point_into_route_uses_user_position_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "route",
                        "points": [
                            {"x": 0, "y": 0},
                            {"x": 100, "y": 0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            outcomes = manager.insert_point_into_routes(
                90,
                0,
                ["2026010101"],
                overrides={"2026010101": 0},
            )

            self.assertEqual(outcomes["2026010101"], 0)
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual([(point["x"], point["y"]) for point in payload["points"]], [
                (90, 0),
                (0, 0),
                (100, 0),
            ])

    def test_create_route_uses_13_digit_string_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            manager = RouteManager(str(base))

            self.assertTrue(manager.create_route("采集", "路线"))

            payload = json.loads((category / "路线.json").read_text(encoding="utf-8"))
            self.assertTrue(_is_13_digit_route_id(payload["id"]))
            self.assertEqual(payload["format_version"], resource_metadata.APP_FORMAT_VERSION)

    def test_create_route_avoids_generated_id_collisions_before_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            manager = RouteManager(str(base))

            with patch("ui_island.services.route_manager.secrets.randbelow", side_effect=[7, 7, 8]):
                self.assertTrue(manager.create_route("采集", "路线一"))
                self.assertTrue(manager.create_route("采集", "路线二"))

            first = json.loads((category / "路线一.json").read_text(encoding="utf-8"))
            second = json.loads((category / "路线二.json").read_text(encoding="utf-8"))
            self.assertEqual(first["id"], "1000000000007")
            self.assertEqual(second["id"], "1000000000008")

    def test_route_id_repair_uses_13_digit_string_and_preserves_old_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            (category / "a_old.json").write_text(
                json.dumps({"id": "2026010101", "name": "old", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (category / "b_duplicate.json").write_text(
                json.dumps({"id": "2026010101", "name": "duplicate", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (category / "c_invalid.json").write_text(
                json.dumps({"id": 1234567890123, "name": "invalid", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (category / "d_missing.json").write_text(
                json.dumps({"name": "missing", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            manager = RouteManager(str(base))

            old = json.loads((category / "a_old.json").read_text(encoding="utf-8"))
            duplicate = json.loads((category / "b_duplicate.json").read_text(encoding="utf-8"))
            invalid = json.loads((category / "c_invalid.json").read_text(encoding="utf-8"))
            missing = json.loads((category / "d_missing.json").read_text(encoding="utf-8"))
            repaired_ids = {duplicate["id"], invalid["id"], missing["id"]}

            self.assertEqual(old["id"], "2026010101")
            self.assertIsNotNone(manager.route_for_id("2026010101"))
            self.assertTrue(all(_is_13_digit_route_id(route_id) for route_id in repaired_ids))
            self.assertEqual(len(repaired_ids), 3)

    def test_annotation_point_mutations_reject_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 1}],
                        "pointsByType": {"flower": [{"x": 1, "y": 2}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = points_file.read_text(encoding="utf-8")
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("ui_island.services.route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertFalse(manager.change_annotation_point_type("flower", 2, "flower", "Sunflower"))
                self.assertFalse(manager.change_annotation_point_type("flower", 0, "missing", "Missing"))
                self.assertFalse(manager.delete_annotation_point("flower", 2))
                self.assertIsNone(manager.annotation_point("flower", 2))
            self.assertEqual(points_file.read_text(encoding="utf-8"), before)

    def test_create_optimized_annotation_route_writes_algorithm_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {
                "flower": [
                    {"x": 100, "y": 100, "label": "花 A", "radius": 30, "typeId": "flower"},
                    {"x": 150, "y": 100, "label": "花 B", "radius": 30, "typeId": "flower"},
                    {"x": 120, "y": 140, "label": "花 C", "radius": 30, "typeId": "flower"},
                ]
            }

            result = manager.create_optimized_annotation_route("flower", "向阳花")
            route_path = Path(result["path"])
            payload = json.loads(route_path.read_text(encoding="utf-8"))

            self.assertEqual(route_path.name, "向阳花_路线(算法生成).json")
            self.assertEqual(route_path.parent.name, "算法生成")
            self.assertEqual(payload["name"], "向阳花_路线(算法生成)")
            self.assertFalse(payload["loop"])
            self.assertEqual(len(payload["points"]), 3)
            self.assertTrue(all(point["typeId"] == "flower" for point in payload["points"]))
            self.assertTrue(all(point["radius"] == 30 for point in payload["points"]))
            self.assertIn("来源标注：向阳花", payload["notes"])
            self.assertTrue(_is_13_digit_route_id(result["id"]))
            self.assertEqual(payload["id"], result["id"])
            self.assertIn(result["id"], manager._route_index_by_id)

    def test_create_optimized_annotation_route_auto_numbers_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {
                "ore": [
                    {"x": 0, "y": 0, "typeId": "ore"},
                    {"x": 10, "y": 0, "typeId": "ore"},
                ]
            }

            first = manager.create_optimized_annotation_route("ore", "矿石")
            second = manager.create_optimized_annotation_route("ore", "矿石")

            self.assertEqual(Path(first["path"]).name, "矿石_路线(算法生成).json")
            self.assertEqual(Path(second["path"]).name, "矿石_路线(算法生成) 2.json")
            self.assertTrue(Path(first["path"]).exists())
            self.assertTrue(Path(second["path"]).exists())
            self.assertTrue(_is_13_digit_route_id(first["id"]))
            self.assertTrue(_is_13_digit_route_id(second["id"]))
            self.assertNotEqual(first["id"], second["id"])

    def test_create_optimized_annotation_route_rejects_empty_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"empty": [{"x": "bad", "y": 1}]}

            with self.assertRaises(ValueError):
                manager.create_optimized_annotation_route("empty", "空标注")

            generated = Path(tmp) / "routes" / "算法生成"
            self.assertFalse(generated.exists())


if __name__ == "__main__":
    unittest.main()

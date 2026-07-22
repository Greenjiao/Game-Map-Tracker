import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from ui_island.controllers.map_interaction_controller import MapInteractionController
from ui_island.design import strings
from ui_island.state import RouteDrawingState


class _FakeMapView:
    def __init__(self) -> None:
        self.refresh_count = 0
        self.undo_available_values: list[bool] = []

    def _refresh_from_last_frame(self) -> None:
        self.refresh_count += 1

    def set_route_point_move_undo_available(self, available: bool) -> None:
        self.undo_available_values.append(bool(available))


class _FakeRoutePanelController:
    def __init__(self, window=None) -> None:
        self.window = window
        self.refresh_count = 0
        self.append_calls: list[tuple[int, int, dict | None, str | None]] = []
        self.direct_append_calls: list[tuple[int, int, dict | None, str | None]] = []
        self.change_order_calls: list[int] = []
        self.active_notes_route_id = ""
        self.notes_nodes: list[dict] | None = None

    def refresh_tracked_routes(self) -> None:
        self.refresh_count += 1

    def append_drawing_point_from_context_menu(
        self,
        x: int,
        y: int,
        point_fields: dict | None = None,
        node_type_override: str | None = None,
    ) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and not drawing.paused:
            self.append_calls.append((x, y, dict(point_fields or {}), node_type_override))

    def append_drawing_point(
        self,
        x: int,
        y: int,
        point_fields: dict | None = None,
        node_type_override: str | None = None,
    ) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and not drawing.paused:
            self.direct_append_calls.append((x, y, dict(point_fields or {}), node_type_override))

    def change_drawing_point_order(self, point_index: int) -> None:
        self.change_order_calls.append(int(point_index))

    def has_active_route_notes_draft(self, route_id: str) -> bool:
        return route_id == self.active_notes_route_id

    def route_notes_draft_nodes(self, route_id: str) -> list[dict] | None:
        if not self.has_active_route_notes_draft(route_id) or self.notes_nodes is None:
            return None
        return [dict(point) for point in self.notes_nodes]

    def update_route_notes_draft_nodes(self, route_id: str, nodes: list[dict], refresh: bool = True) -> bool:
        if not self.has_active_route_notes_draft(route_id):
            return False
        self.notes_nodes = [dict(point) for point in nodes]
        route = self.window.route_mgr.routes.get(route_id)
        if route is not None:
            route["points"] = [dict(point) for point in self.notes_nodes]
        return True

    def move_route_notes_point(self, route_id: str, point_index: int, x: int, y: int, **_kwargs) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not (0 <= point_index < len(nodes)):
            return False
        nodes[point_index]["x"] = int(x)
        nodes[point_index]["y"] = int(y)
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def reorder_route_notes_point(self, route_id: str, from_index: int, to_index: int) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not (0 <= from_index < len(nodes)):
            return False
        point = nodes.pop(from_index)
        nodes.insert(max(0, min(len(nodes), int(to_index))), point)
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def set_route_notes_point_annotation(
        self,
        route_id: str,
        point_index: int,
        type_id: str,
        type_name: str,
        *,
        node_type: str | None = None,
    ) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not (0 <= point_index < len(nodes)):
            return False
        nodes[point_index]["typeId"] = type_id
        nodes[point_index]["type"] = type_name
        if node_type is not None:
            nodes[point_index]["node_type"] = node_type
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def set_route_notes_point_layer(self, route_id: str, point_index: int, layer: str) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not (0 <= point_index < len(nodes)):
            return False
        nodes[point_index]["layer"] = str(layer or "").strip()
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def set_drawing_point_layer(self, point_index: int, layer: str) -> bool:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is None or not drawing.active or not (0 <= point_index < len(drawing.draft_points)):
            return False
        drawing.draft_points[point_index]["layer"] = str(layer or "").strip()
        return True


class _FakeRouteManager:
    def __init__(self) -> None:
        self.routes = {
            "route-1": {
                "display_name": "Route 1",
                "points": [{"x": 1, "y": 2}, {"x": 10, "y": 20}],
            }
        }
        self.position_calls: list[tuple[str, int, int, int, bool]] = []
        self.fail_persist = False
        self.delete_outcomes = {"route-1": [0]}
        self.insert_outcomes = {"route-1": 1}
        self.visible_ids = ["route-1"]
        self.annotation_items = [{"typeId": "flower", "type": "Sunflower"}, {"typeId": "tp", "type": "Teleport"}]
        self.annotation_points = {
            ("flower", 0): {
                "x": 12,
                "y": 34,
                "typeId": "flower",
                "type": "Sunflower",
                "label": "Field Flower",
                "radius": 25,
                "layer": "地上层",
                "sourceId": "source-flower",
                "manual": True,
                "id": "annotation-flower",
            }
        }
        self.insert_calls: list[dict] = []
        self.annotation_calls: list[tuple[str, int, str, str, str | None]] = []
        self.annotation_label_calls: list[tuple[str, int, str]] = []
        self.annotation_layer_calls: list[tuple[str, int, str]] = []
        self.point_layer_calls: list[tuple[str, int, str]] = []
        self.reorder_calls: list[tuple[str, int, int]] = []
        self.fail_reorder = False

    def set_point_position(self, route_id: str, point_index: int, x: int, y: int, persist: bool = True) -> bool:
        self.position_calls.append((route_id, point_index, int(x), int(y), bool(persist)))
        if persist and self.fail_persist:
            return False
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= point_index < len(points)):
            return False
        points[point_index]["x"] = int(x)
        points[point_index]["y"] = int(y)
        return True

    def route_for_id(self, route_id: str) -> dict | None:
        return self.routes.get(route_id)

    def summarize_route(self, route_id: str) -> dict | None:
        route = self.routes.get(route_id)
        if route is None:
            return None
        return {
            "display_label": route.get("display_name", ""),
            "points_count": len(route.get("points", [])),
        }

    def delete_points_from_routes(self, _deletions: dict[str, list[int]]) -> dict[str, list[int]]:
        return self.delete_outcomes

    def visible_route_ids(self) -> list[str]:
        return list(self.visible_ids)

    def annotation_type_items(self) -> list[dict]:
        return [dict(item) for item in self.annotation_items]

    def annotation_type_ids(self) -> list[str]:
        return [str(item.get("typeId") or "") for item in self.annotation_items]

    def route_point_annotation_type_id(self, route_id: str, point_index: int) -> str:
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= point_index < len(points)):
            return ""
        point = points[point_index]
        return str(point.get("typeId") or "") if isinstance(point, dict) else ""

    def annotation_point(self, type_id: str, point_index: int) -> dict | None:
        point = self.annotation_points.get((type_id, point_index))
        return dict(point) if point is not None else None

    def change_annotation_point_label(self, type_id: str, point_index: int, label: str) -> bool:
        point = self.annotation_points.get((type_id, point_index))
        if point is None:
            return False
        point["label"] = label
        self.annotation_label_calls.append((type_id, point_index, label))
        return True

    def change_annotation_point_layer(self, type_id: str, point_index: int, layer: str) -> bool:
        point = self.annotation_points.get((type_id, point_index))
        if point is None:
            return False
        point["layer"] = str(layer or "").strip()
        self.annotation_layer_calls.append((type_id, point_index, str(layer or "").strip()))
        return True

    def route_point_layer(self, route_id: str, point_index: int) -> str:
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= point_index < len(points)):
            return ""
        return str(points[point_index].get("layer") or "").strip()

    def set_point_layer(self, route_id: str, point_index: int, layer: str) -> bool:
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= point_index < len(points)):
            return False
        normalized = str(layer or "").strip()
        points[point_index]["layer"] = normalized
        self.point_layer_calls.append((route_id, point_index, normalized))
        return True

    def set_point_annotation(
        self,
        route_id: str,
        point_index: int,
        type_id: str,
        type_name: str,
        *,
        node_type: str | None = None,
    ) -> bool:
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        point["typeId"] = type_id
        point["type"] = type_name
        if node_type is not None:
            point["node_type"] = node_type
        self.annotation_calls.append((route_id, point_index, type_id, type_name, node_type))
        return True

    def suggest_insertion_index(self, _route_id: str, _x: int, _y: int) -> int:
        return 1

    def insert_point_into_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str],
        overrides: dict[str, int] | None = None,
        point_fields: dict | None = None,
    ) -> dict[str, int | None]:
        self.insert_calls.append({
            "x": x,
            "y": y,
            "route_ids": list(route_ids),
            "overrides": dict(overrides or {}),
            "point_fields": dict(point_fields or {}),
        })
        return self.insert_outcomes

    def reorder_route_point(self, route_id: str, from_index: int, to_index: int) -> bool:
        self.reorder_calls.append((route_id, int(from_index), int(to_index)))
        if self.fail_reorder:
            return False
        route = self.routes.get(route_id)
        points = route.get("points", []) if route is not None else []
        if not (0 <= from_index < len(points)):
            return False
        target = max(0, min(len(points) - 1, int(to_index)))
        if from_index == target:
            return False
        point = points.pop(from_index)
        points.insert(target, point)
        return True


class _FakeWindow:
    def __init__(self) -> None:
        self.route_mgr = _FakeRouteManager()
        self.map_view = _FakeMapView()
        self.route_drawing_state = RouteDrawingState()
        self.route_panel_controller = _FakeRoutePanelController(self)


class MapInteractionControllerTests(unittest.TestCase):
    def _controller(self) -> tuple[MapInteractionController, _FakeWindow]:
        window = _FakeWindow()
        return MapInteractionController(window), window

    def _annotation_file(self, root: Path) -> Path:
        path = root / "annotations" / "points.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            """
{
  "types": [
    {"typeId": "flower", "type": "Sunflower"},
    {"typeId": "ore", "type": "Ore"},
    {"typeId": "tp", "type": "Teleport"}
  ],
  "pointsByType": {
    "flower": [{"x": 12, "y": 34, "label": "Flower"}],
    "ore": [{"x": 13, "y": 34, "label": "Ore"}],
    "tp": [{"x": 20, "y": 30, "label": "Portal"}]
  }
}
""",
            encoding="utf-8",
        )
        return path

    def _teleport_dir(self, root: Path) -> Path:
        path = root / "tools" / "points_get" / "teleport"
        path.mkdir(parents=True)
        (path / "Teleport.json").write_text("{}", encoding="utf-8")
        return path

    def test_move_route_point_preview_updates_memory_without_persisting(self) -> None:
        controller, window = self._controller()

        controller.move_route_point_preview("route-1", 0, 5, 6)

        self.assertEqual(window.route_mgr.routes["route-1"]["points"][0], {"x": 5, "y": 6})
        self.assertEqual(window.route_mgr.position_calls, [("route-1", 0, 5, 6, False)])
        self.assertEqual(window.map_view.refresh_count, 1)
        self.assertEqual(window.route_panel_controller.refresh_count, 1)

    def test_move_route_point_preview_updates_active_notes_draft_without_route_manager_call(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = [{"x": 1, "y": 2}, {"x": 10, "y": 20}]

        controller.move_route_point_preview("route-1", 0, 5, 6)
        controller.finish_move_route_point("route-1", 0, 1, 2, 7, 8)

        self.assertEqual(window.route_panel_controller.notes_nodes[0], {"x": 7, "y": 8})
        self.assertEqual(window.route_mgr.position_calls, [])
        self.assertFalse(controller.has_route_point_move_undo())
        self.assertGreaterEqual(window.map_view.refresh_count, 2)

    def test_add_annotated_point_selects_annotation_then_reuses_route_insert_flow(self) -> None:
        controller, window = self._controller()

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "flower", "type": "Sunflower", "label": "ignored"},
            ) as picker,
            patch.object(controller, "add_point_to_routes") as add_point_to_routes,
        ):
            controller.add_annotated_point_to_routes(12, 34)

        picker.assert_called_once_with(window, window.route_mgr.annotation_items, "")
        add_point_to_routes.assert_called_once_with(
            12,
            34,
            point_fields={"typeId": "flower", "type": "Sunflower", "node_type": "collect"},
        )

    def test_add_annotated_point_marks_teleport_type_as_teleport_node(self) -> None:
        controller, window = self._controller()

        with (
            patch("tools.route_format_converter.default_route_teleport_type_ids", return_value=["tp"]),
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "tp", "type": "Teleport"},
            ),
            patch.object(controller, "add_point_to_routes") as add_point_to_routes,
        ):
            controller.add_annotated_point_to_routes(12, 34)

        add_point_to_routes.assert_called_once_with(
            12,
            34,
            point_fields={"typeId": "tp", "type": "Teleport", "node_type": "teleport"},
        )

    def test_add_annotated_point_can_target_single_route_without_route_dialog(self) -> None:
        controller, window = self._controller()

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "flower", "type": "Sunflower"},
            ),
            patch.object(controller, "add_point_to_routes") as add_point_to_routes,
        ):
            controller.add_annotated_point_to_routes(
                12,
                34,
                route_ids=["route-1"],
                show_dialog=False,
            )

        add_point_to_routes.assert_called_once_with(
            12,
            34,
            route_ids=["route-1"],
            show_dialog=False,
            point_fields={"typeId": "flower", "type": "Sunflower", "node_type": "collect"},
        )

    def test_add_collect_route_node_matches_non_teleport_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_items = [
                    {"typeId": "flower", "type": "Sunflower"},
                    {"typeId": "tp", "type": "Teleport"},
                ]

                with (
                    patch("ui_island.controllers.map_interaction_controller.open_annotation_match_candidate_picker") as picker,
                    patch(
                        "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                        return_value=(["route-1"], {}),
                    ),
                    patch("ui_island.controllers.map_interaction_controller.toast"),
                ):
                    controller.add_route_node_from_context_menu(12, 34, "collect")

                picker.assert_not_called()
                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "collect",
                    "typeId": "flower",
                    "type": "Sunflower",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_collect_route_node_matches_when_annotation_display_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_type_ids = lambda: []

                with (
                    patch(
                        "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                        return_value=(["route-1"], {}),
                    ),
                    patch("ui_island.controllers.map_interaction_controller.toast"),
                ):
                    controller.add_route_node_from_context_menu(12, 34, "collect")

                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "collect",
                    "typeId": "flower",
                    "type": "Sunflower",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_teleport_route_node_matches_only_teleport_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()

                with patch(
                    "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                    return_value=(["route-1"], {}),
                ), patch("ui_island.controllers.map_interaction_controller.toast"):
                    controller.add_route_node_from_context_menu(20, 30, "teleport")

                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "teleport",
                    "typeId": "tp",
                    "type": "Teleport",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_teleport_route_node_matches_when_annotation_display_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_type_ids = lambda: []

                with patch(
                    "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                    return_value=(["route-1"], {}),
                ), patch("ui_island.controllers.map_interaction_controller.toast"):
                    controller.add_route_node_from_context_menu(20, 30, "teleport")

                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "teleport",
                    "typeId": "tp",
                    "type": "Teleport",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_guide_route_node_only_sets_virtual_node_type(self) -> None:
        controller, window = self._controller()

        with (
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
            patch(
                "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                return_value=(["route-1"], {}),
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.add_route_node_from_context_menu(12, 34, "virtual")

        picker.assert_not_called()
        self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {"node_type": "virtual"})

    def test_add_route_node_can_target_single_route_without_route_dialog(self) -> None:
        controller, window = self._controller()

        with (
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
            patch(
                "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
            ) as insert_dialog,
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.add_route_node_from_context_menu(
                12,
                34,
                "virtual",
                route_ids=["route-1"],
                show_dialog=False,
            )

        picker.assert_not_called()
        insert_dialog.assert_not_called()
        self.assertEqual(window.route_mgr.insert_calls[-1]["route_ids"], ["route-1"])
        self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {"node_type": "virtual"})

    def test_add_route_node_while_drawing_passes_node_type_override_to_draft(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[])

        with (
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
            patch.object(controller, "add_point_to_routes") as add_point_to_routes,
        ):
            controller.add_route_node_from_context_menu(12, 34, "virtual")

        picker.assert_not_called()
        add_point_to_routes.assert_not_called()
        self.assertEqual(window.route_panel_controller.append_calls, [
            (12, 34, {"node_type": "virtual"}, "virtual")
        ])

    def test_add_route_node_without_match_uses_filtered_manual_picker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_items = [
                    {"typeId": "flower", "type": "Sunflower"},
                    {"typeId": "tp", "type": "Teleport"},
                ]

                with patch(
                    "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                    return_value={"typeId": "flower", "type": "Sunflower"},
                ) as picker, patch(
                    "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                    return_value=(["route-1"], {}),
                ), patch("ui_island.controllers.map_interaction_controller.toast"):
                    controller.add_route_node_from_context_menu(200, 200, "collect")

                args = picker.call_args.args
                self.assertEqual([item["typeId"] for item in args[1]], ["flower"])
                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "collect",
                    "typeId": "flower",
                    "type": "Sunflower",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_route_node_without_match_uses_all_types_for_manual_picker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_type_ids = lambda: []
                window.route_mgr.annotation_items = [
                    {"typeId": "flower", "type": "Sunflower"},
                    {"typeId": "ore", "type": "Ore"},
                    {"typeId": "tp", "type": "Teleport"},
                ]

                with patch(
                    "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                    return_value=None,
                ) as picker:
                    controller.add_route_node_from_context_menu(200, 200, "collect")

                args = picker.call_args.args
                self.assertEqual([item["typeId"] for item in args[1]], ["flower", "ore"])
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_route_node_ambiguous_match_uses_candidate_picker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                root = Path(tmp)
                config.BASE_DIR = str(root)
                config.ANNOTATION_FILE = "annotations/points.json"
                self._annotation_file(root)
                self._teleport_dir(root)
                controller, window = self._controller()
                window.route_mgr.annotation_items = [
                    {"typeId": "flower", "type": "Sunflower"},
                    {"typeId": "ore", "type": "Ore"},
                    {"typeId": "tp", "type": "Teleport"},
                ]

                def choose_candidate(_parent, candidates, **_kwargs):
                    return candidates[1]

                with patch(
                    "ui_island.controllers.map_interaction_controller.open_annotation_match_candidate_picker",
                    side_effect=choose_candidate,
                ) as picker, patch(
                    "ui_island.controllers.map_interaction_controller.open_insert_point_dialog",
                    return_value=(["route-1"], {}),
                ), patch("ui_island.controllers.map_interaction_controller.toast"):
                    controller.add_route_node_from_context_menu(12, 34, "collect")

                picker.assert_called_once()
                self.assertEqual(window.route_mgr.insert_calls[-1]["point_fields"], {
                    "node_type": "collect",
                    "typeId": "ore",
                    "type": "Ore",
                })
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_add_annotated_point_cancel_does_not_insert(self) -> None:
        controller, window = self._controller()

        with patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker", return_value=None):
            controller.add_annotated_point_to_routes(12, 34)

        self.assertEqual(window.route_mgr.insert_calls, [])

    def test_add_annotated_point_without_annotation_types_shows_info_before_insert(self) -> None:
        controller, window = self._controller()
        window.route_mgr.annotation_items = []

        with (
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
            patch("ui_island.controllers.map_interaction_controller.styled_info") as styled_info,
        ):
            controller.add_annotated_point_to_routes(12, 34)

        picker.assert_not_called()
        styled_info.assert_called_once()
        self.assertEqual(window.route_mgr.insert_calls, [])

    def test_add_annotated_point_without_visible_routes_does_not_open_picker(self) -> None:
        controller, window = self._controller()
        window.route_mgr.visible_ids = []

        with (
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
            patch("ui_island.controllers.map_interaction_controller.styled_info") as styled_info,
        ):
            controller.add_annotated_point_to_routes(12, 34)

        picker.assert_not_called()
        styled_info.assert_called_once()
        self.assertEqual(window.route_mgr.insert_calls, [])

    def test_add_annotation_to_route_uses_drawing_draft_when_pure_drawing_active(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[])

        with patch.object(controller, "add_point_to_routes") as add_point_to_routes:
            controller.add_annotation_to_route("flower", 0)

        add_point_to_routes.assert_not_called()
        self.assertEqual(len(window.route_panel_controller.append_calls), 1)
        x, y, point_fields, node_type_override = window.route_panel_controller.append_calls[0]
        self.assertEqual((x, y), (12, 34))
        self.assertEqual(point_fields["typeId"], "flower")
        self.assertEqual(point_fields["type"], "Sunflower")
        self.assertEqual(point_fields["label"], "Field Flower")
        self.assertEqual(point_fields["layer"], "地上层")
        self.assertEqual(point_fields["node_type"], "collect")
        self.assertEqual(node_type_override, "collect")

    def test_add_annotation_to_drawing_route_uses_exact_annotation_data_without_context_dialog(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[])
        window.route_drawing_state.annotation_point_mode = True
        window.route_drawing_state.add_node_annotation = True

        with (
            patch.object(controller, "add_point_to_routes") as add_point_to_routes,
            patch("ui_island.controllers.map_interaction_controller.open_annotation_type_picker") as picker,
        ):
            controller.add_annotation_to_drawing_route("flower", 0)

        add_point_to_routes.assert_not_called()
        picker.assert_not_called()
        self.assertEqual(window.route_panel_controller.append_calls, [])
        self.assertEqual(len(window.route_panel_controller.direct_append_calls), 1)
        x, y, point_fields, node_type_override = window.route_panel_controller.direct_append_calls[0]
        self.assertEqual((x, y), (12, 34))
        self.assertEqual(point_fields["typeId"], "flower")
        self.assertEqual(point_fields["type"], "Sunflower")
        self.assertEqual(point_fields["label"], "Field Flower")
        self.assertEqual(point_fields["layer"], "地上层")
        self.assertEqual(point_fields["radius"], 25)
        self.assertEqual(point_fields["sourceId"], "source-flower")
        self.assertTrue(point_fields["manual"])
        self.assertEqual(node_type_override, "collect")

    def test_add_annotation_to_drawing_route_failure_keeps_draft_unchanged(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[])

        with patch("ui_island.controllers.map_interaction_controller.styled_info") as styled_info:
            controller.add_annotation_to_drawing_route("missing", 0)

        self.assertEqual(window.route_panel_controller.direct_append_calls, [])
        styled_info.assert_called_once_with(
            window,
            strings.MAP_ANNOTATION_FAIL_TITLE,
            strings.MAP_ANNOTATION_ROUTE_FAIL_BODY,
        )

    def test_add_annotation_to_route_does_not_write_json_when_pure_drawing_paused(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[])
        window.route_drawing_state.paused = True

        with patch.object(controller, "add_point_to_routes") as add_point_to_routes:
            controller.add_annotation_to_route("flower", 0)

        add_point_to_routes.assert_not_called()
        self.assertEqual(window.route_panel_controller.append_calls, [])
        self.assertEqual(window.route_mgr.insert_calls, [])

    def test_add_annotation_to_route_keeps_json_flow_outside_pure_drawing(self) -> None:
        controller, window = self._controller()

        with patch.object(controller, "add_point_to_routes") as add_point_to_routes:
            controller.add_annotation_to_route("flower", 0)

        add_point_to_routes.assert_called_once()
        args, kwargs = add_point_to_routes.call_args
        self.assertEqual(args, (12, 34))
        self.assertEqual(kwargs["point_fields"]["typeId"], "flower")
        self.assertEqual(kwargs["point_fields"]["layer"], "地上层")
        self.assertEqual(kwargs["point_fields"]["node_type"], "collect")

    def test_change_map_annotation_label_prompts_saves_and_refreshes(self) -> None:
        controller, window = self._controller()

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.prompt_text_input",
                return_value=(True, "花园入口"),
            ) as prompt,
            patch.object(controller, "_refresh_annotation_ui") as refresh,
            patch("ui_island.controllers.map_interaction_controller.toast") as toast,
        ):
            controller.change_map_annotation_label("flower", 0)

        self.assertEqual(prompt.call_args.kwargs["value"], "Field Flower")
        self.assertEqual(window.route_mgr.annotation_label_calls, [("flower", 0, "花园入口")])
        refresh.assert_called_once_with()
        toast.assert_called_once()

    def test_change_map_annotation_label_cancel_keeps_point_unchanged(self) -> None:
        controller, window = self._controller()

        with patch(
            "ui_island.controllers.map_interaction_controller.prompt_text_input",
            return_value=(False, "ignored"),
        ):
            controller.change_map_annotation_label("flower", 0)

        self.assertEqual(window.route_mgr.annotation_label_calls, [])

    def test_change_map_annotation_layer_prompts_saves_and_can_clear(self) -> None:
        controller, window = self._controller()

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.prompt_text_input",
                return_value=(True, ""),
            ) as prompt,
            patch.object(controller, "_refresh_annotation_ui") as refresh,
            patch("ui_island.controllers.map_interaction_controller.toast") as toast,
        ):
            controller.change_map_annotation_layer("flower", 0)

        self.assertEqual(prompt.call_args.kwargs["value"], "地上层")
        self.assertEqual(window.route_mgr.annotation_layer_calls, [("flower", 0, "")])
        refresh.assert_called_once_with()
        toast.assert_called_once()

    def test_change_saved_route_point_layer_persists_and_refreshes(self) -> None:
        controller, window = self._controller()
        window.route_mgr.routes["route-1"]["points"][0]["layer"] = "地上层"

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.prompt_text_input",
                return_value=(True, "  地下层  "),
            ) as prompt,
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_layer("route-1", 0)

        self.assertEqual(prompt.call_args.kwargs["value"], "地上层")
        self.assertEqual(window.route_mgr.point_layer_calls, [("route-1", 0, "地下层")])
        self.assertEqual(window.map_view.refresh_count, 1)
        self.assertEqual(window.route_panel_controller.refresh_count, 1)

    def test_change_notes_draft_point_layer_does_not_persist_route_file(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = [{"x": 1, "y": 2}]
        window.route_mgr.set_point_layer = lambda *_args: (_ for _ in ()).throw(AssertionError("persisted"))

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.prompt_text_input",
                return_value=(True, "地下层"),
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_layer("route-1", 0)

        self.assertEqual(window.route_panel_controller.notes_nodes[0]["layer"], "地下层")

    def test_change_saved_point_annotation_syncs_node_type(self) -> None:
        controller, window = self._controller()
        window.route_mgr.routes["route-1"]["points"][0]["node_type"] = "virtual"

        with (
            patch("tools.route_format_converter.default_route_teleport_type_ids", return_value=["tp"]),
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "tp", "type": "Teleport"},
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_annotation("route-1", 0)

        self.assertEqual(window.route_mgr.annotation_calls[-1], ("route-1", 0, "tp", "Teleport", "teleport"))
        self.assertEqual(window.route_mgr.routes["route-1"]["points"][0]["node_type"], "teleport")

    def test_change_notes_draft_point_annotation_syncs_node_type(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = [{"x": 1, "y": 2, "node_type": "virtual"}]

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "flower", "type": "Sunflower"},
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_annotation("route-1", 0)

        self.assertEqual(window.route_panel_controller.notes_nodes[0]["typeId"], "flower")
        self.assertEqual(window.route_panel_controller.notes_nodes[0]["node_type"], "collect")

    def test_finish_move_route_point_persists_and_records_single_undo(self) -> None:
        controller, window = self._controller()

        with patch("ui_island.controllers.map_interaction_controller.toast") as toast:
            controller.finish_move_route_point("route-1", 0, 1, 2, 7, 8)

        self.assertEqual(window.route_mgr.routes["route-1"]["points"][0], {"x": 7, "y": 8})
        self.assertEqual(window.route_mgr.position_calls[-2:], [
            ("route-1", 0, 1, 2, False),
            ("route-1", 0, 7, 8, True),
        ])
        self.assertTrue(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], True)
        toast.assert_called_once()

    def test_finish_move_route_point_ignores_unchanged_coordinates(self) -> None:
        controller, window = self._controller()

        controller.finish_move_route_point("route-1", 0, 1, 2, 1, 2)

        self.assertEqual(window.route_mgr.position_calls, [])
        self.assertFalse(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values, [])

    def test_finish_move_route_point_failure_restores_before_position(self) -> None:
        controller, window = self._controller()
        window.route_mgr.routes["route-1"]["points"][0] = {"x": 7, "y": 8}
        window.route_mgr.fail_persist = True

        with patch("ui_island.controllers.map_interaction_controller.styled_info") as styled_info:
            controller.finish_move_route_point("route-1", 0, 1, 2, 7, 8)

        self.assertEqual(window.route_mgr.routes["route-1"]["points"][0], {"x": 1, "y": 2})
        self.assertFalse(controller.has_route_point_move_undo())
        styled_info.assert_called_once()

    def test_undo_route_point_move_restores_before_position_and_clears_undo(self) -> None:
        controller, window = self._controller()
        with patch("ui_island.controllers.map_interaction_controller.toast"):
            controller.finish_move_route_point("route-1", 0, 1, 2, 7, 8)

        with patch("ui_island.controllers.map_interaction_controller.toast") as toast:
            controller.undo_route_point_move()

        self.assertEqual(window.route_mgr.routes["route-1"]["points"][0], {"x": 1, "y": 2})
        self.assertEqual(window.route_mgr.position_calls[-1], ("route-1", 0, 1, 2, True))
        self.assertFalse(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], False)
        toast.assert_called_once()

    def test_change_point_order_uses_drawing_branch_without_json_write(self) -> None:
        controller, window = self._controller()
        window.route_drawing_state.begin(route_id="route-1", category="routes", name="Route 1", points=[
            {"x": 1, "y": 2},
            {"x": 10, "y": 20},
        ])

        with patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog") as dialog:
            controller.change_point_order("route-1", 1)

        dialog.assert_not_called()
        self.assertEqual(window.route_panel_controller.change_order_calls, [1])
        self.assertEqual(window.route_mgr.reorder_calls, [])

    def test_change_point_order_reorders_route_and_records_undo(self) -> None:
        controller, window = self._controller()
        window.route_mgr.routes["route-1"]["points"] = [
            {"id": "a", "x": 1, "y": 2},
            {"id": "b", "x": 10, "y": 20},
            {"id": "c", "x": 30, "y": 40},
        ]

        with (
            patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=2) as dialog,
            patch("ui_island.controllers.map_interaction_controller.toast") as toast,
        ):
            controller.change_point_order("route-1", 0)

        dialog.assert_called_once_with(window, "Route 1", 0, 3)
        self.assertEqual(window.route_mgr.reorder_calls, [("route-1", 0, 2)])
        self.assertEqual([point["id"] for point in window.route_mgr.routes["route-1"]["points"]], ["b", "c", "a"])
        self.assertTrue(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], True)
        self.assertEqual(window.map_view.refresh_count, 1)
        self.assertEqual(window.route_panel_controller.refresh_count, 1)
        toast.assert_called_once()

    def test_change_point_order_updates_active_notes_draft_without_json_write(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = [
            {"id": "a", "x": 1, "y": 2},
            {"id": "b", "x": 10, "y": 20},
            {"id": "c", "x": 30, "y": 40},
        ]

        with patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=2):
            controller.change_point_order("route-1", 0)

        self.assertEqual([point["id"] for point in window.route_panel_controller.notes_nodes], ["b", "c", "a"])
        self.assertEqual(window.route_mgr.reorder_calls, [])
        self.assertFalse(controller.has_route_point_move_undo())

    def test_change_point_annotation_updates_active_notes_draft_without_json_write(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = [{"x": 1, "y": 2}]
        window.route_mgr.set_point_annotation = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("persisted"))

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.open_annotation_type_picker",
                return_value={"typeId": "flower", "type": "Sunflower"},
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_annotation("route-1", 0)

        self.assertEqual(window.route_panel_controller.notes_nodes[0]["typeId"], "flower")
        self.assertEqual(window.route_panel_controller.notes_nodes[0]["type"], "Sunflower")

    def test_change_point_order_cancel_or_same_position_is_noop(self) -> None:
        controller, window = self._controller()

        with patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=None):
            controller.change_point_order("route-1", 0)
        with patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=0):
            controller.change_point_order("route-1", 0)

        self.assertEqual(window.route_mgr.reorder_calls, [])
        self.assertFalse(controller.has_route_point_move_undo())

    def test_undo_route_point_order_restores_previous_order_and_clears_undo(self) -> None:
        controller, window = self._controller()
        window.route_mgr.routes["route-1"]["points"] = [
            {"id": "a", "x": 1, "y": 2},
            {"id": "b", "x": 10, "y": 20},
            {"id": "c", "x": 30, "y": 40},
        ]
        with (
            patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=2),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.change_point_order("route-1", 0)

        with patch("ui_island.controllers.map_interaction_controller.toast") as toast:
            controller.undo_route_point_move()

        self.assertEqual(window.route_mgr.reorder_calls[-1], ("route-1", 2, 0))
        self.assertEqual([point["id"] for point in window.route_mgr.routes["route-1"]["points"]], ["a", "b", "c"])
        self.assertFalse(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], False)
        toast.assert_called_once()

    def test_change_point_order_failure_shows_info_without_undo(self) -> None:
        controller, window = self._controller()
        window.route_mgr.fail_reorder = True

        with (
            patch("ui_island.controllers.map_interaction_controller.open_point_order_dialog", return_value=1),
            patch("ui_island.controllers.map_interaction_controller.styled_info") as styled_info,
        ):
            controller.change_point_order("route-1", 0)

        styled_info.assert_called_once()
        self.assertFalse(controller.has_route_point_move_undo())

    def test_successful_delete_clears_point_move_undo(self) -> None:
        controller, window = self._controller()
        controller._set_point_move_undo({
            "route_id": "route-1",
            "point_index": 0,
            "before": (1, 2),
            "after": (7, 8),
        })

        with (
            patch("ui_island.controllers.map_interaction_controller.styled_confirm", return_value=True),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.delete_points_from_routes({"route-1": [0]})

        self.assertFalse(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], False)

    def test_successful_insert_clears_point_move_undo(self) -> None:
        controller, window = self._controller()
        controller._set_point_move_undo({
            "route_id": "route-1",
            "point_index": 0,
            "before": (1, 2),
            "after": (7, 8),
        })

        with patch("ui_island.controllers.map_interaction_controller.toast"):
            controller.add_point_to_routes(3, 4, show_dialog=False)

        self.assertFalse(controller.has_route_point_move_undo())
        self.assertEqual(window.map_view.undo_available_values[-1], False)

    def test_insert_into_route_notes_draft_uses_default_layer(self) -> None:
        controller, window = self._controller()
        window.route_panel_controller.active_notes_route_id = "route-1"
        window.route_panel_controller.notes_nodes = []
        window.route_mgr.new_route_point_id = lambda: "point-1"

        with (
            patch(
                "ui_island.controllers.map_interaction_controller.resource_metadata.default_point_layer",
                return_value="卡洛西亚大陆",
            ),
            patch("ui_island.controllers.map_interaction_controller.toast"),
        ):
            controller.add_point_to_routes(3, 4, route_ids=["route-1"], show_dialog=False)

        self.assertEqual(window.route_panel_controller.notes_nodes[0]["layer"], "卡洛西亚大陆")
        self.assertEqual(window.route_mgr.insert_calls, [])


if __name__ == "__main__":
    unittest.main()

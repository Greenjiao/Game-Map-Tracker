import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

import config
from ui_island.views.map_coordinates import MapCoordinateAdapter
from ui_island.design import strings
from ui_island.views.map_view import MapView


class _FakeRouteManager:
    def __init__(self) -> None:
        self.routes = {"route-1": {"points": [{"x": 10, "y": 10}]}}
        self.hit_route = True

    def route_for_id(self, route_id: str) -> dict | None:
        return self.routes.get(route_id)

    def point_visited(self, _route_id: str, _point_index: int) -> bool:
        return False

    def route_point_has_annotation(self, _route_id: str, _point_index: int) -> bool:
        return False

    def hit_test_point(self, _x: float, _y: float, _threshold: float):
        if not self.hit_route:
            return None
        return "route-1", 0

    def hit_test_annotation_point(self, _x: float, _y: float, _threshold: float):
        return None


class MapViewRouteDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _view(self, route_mgr: _FakeRouteManager | None = None) -> MapView:
        view = MapView(route_mgr or _FakeRouteManager())
        view.set_coordinate_adapter(MapCoordinateAdapter.for_map_file("maps/test-map.png"))
        view.resize(200, 200)
        view._pixmap = QPixmap(200, 200)
        view._last_draw_rect = QRectF(0, 0, 200, 200)
        view._last_crop_size = (200, 200)
        view._last_vx1 = 0
        view._last_vy1 = 0
        view._view_center = QPointF(100, 100)
        view._center_locked = True
        return view

    def _mouse_event(self, event_type: QEvent.Type, pos: QPointF, button=Qt.LeftButton) -> QMouseEvent:
        buttons = Qt.LeftButton if event_type != QEvent.Type.MouseButtonRelease else Qt.NoButton
        return QMouseEvent(event_type, pos, pos, button, buttons, Qt.NoModifier)

    class _ContextMenuEvent:
        def __init__(self, pos: QPointF) -> None:
            self._pos = pos.toPoint()
            self.accepted = False
            self.ignored = False

        def pos(self):
            return self._pos

        def globalPos(self):
            return self._pos

        def accept(self) -> None:
            self.accepted = True

        def ignore(self) -> None:
            self.ignored = True

    def test_enabled_route_node_press_drags_node_without_panning(self) -> None:
        view = self._view()
        view.set_route_point_drag_enabled(True)
        previews: list[tuple[str, int, int, int]] = []
        finishes: list[tuple[str, int, int, int, int, int]] = []
        manual_changes: list[bool] = []
        view.route_point_move_requested.connect(lambda rid, idx, x, y: previews.append((rid, idx, x, y)))
        view.route_point_move_finished.connect(
            lambda rid, idx, bx, by, ax, ay: finishes.append((rid, idx, bx, by, ax, ay))
        )
        view.manual_view_changed.connect(lambda: manual_changes.append(True))

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(40, 40), button=Qt.NoButton))
        view.mouseReleaseEvent(self._mouse_event(QEvent.Type.MouseButtonRelease, QPointF(40, 40)))

        self.assertEqual(previews, [("route-1", 0, 40, 40)])
        self.assertEqual(finishes, [("route-1", 0, 10, 10, 40, 40)])
        self.assertEqual(view._view_center, QPointF(100, 100))
        self.assertEqual(manual_changes, [])

    def test_disabled_route_node_press_keeps_existing_pan_behavior(self) -> None:
        view = self._view()
        view.set_route_point_drag_enabled(False)
        manual_changes: list[bool] = []
        view.manual_view_changed.connect(lambda: manual_changes.append(True))

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(40, 40), button=Qt.NoButton))

        self.assertNotEqual(view._view_center, QPointF(100, 100))
        self.assertEqual(manual_changes, [True])

    def test_calibration_route_press_drags_route_offsets(self) -> None:
        view = self._view()
        deltas: list[tuple[float, float]] = []
        view.route_calibration_drag_delta_requested.connect(lambda dx, dy: deltas.append((dx, dy)))
        context = {
            "active": True,
            "route_id": "route-1",
            "route": {"id": "route-1", "points": [{"x": 10, "y": 10}]},
            "coord_transform": {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0},
        }
        view.set_route_calibration_context(context)

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(25, 30), button=Qt.NoButton))
        updated_context = dict(context)
        updated_context["coord_transform"] = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 15.0, "offset_y": 20.0}
        view.set_route_calibration_context(updated_context)
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(35, 45), button=Qt.NoButton))
        view.mouseReleaseEvent(self._mouse_event(QEvent.Type.MouseButtonRelease, QPointF(25, 30)))

        self.assertEqual(deltas, [(15.0, 20.0), (10.0, 15.0)])
        self.assertEqual(view._view_center, QPointF(100, 100))

    def test_calibration_blank_drag_keeps_map_pan_behavior(self) -> None:
        view = self._view()
        deltas: list[tuple[float, float]] = []
        manual_changes: list[bool] = []
        view.route_calibration_drag_delta_requested.connect(lambda dx, dy: deltas.append((dx, dy)))
        view.manual_view_changed.connect(lambda: manual_changes.append(True))
        view.set_route_calibration_context({
            "active": True,
            "route_id": "route-1",
            "route": {"id": "route-1", "points": [{"x": 10, "y": 10}]},
            "coord_transform": {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0},
        })

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(100, 100)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(120, 120), button=Qt.NoButton))

        self.assertEqual(deltas, [])
        self.assertNotEqual(view._view_center, QPointF(100, 100))
        self.assertEqual(manual_changes, [True])

    def test_annotation_calibration_drag_continues_across_context_updates(self) -> None:
        view = self._view()
        deltas: list[tuple[float, float]] = []
        view.route_calibration_drag_delta_requested.connect(lambda dx, dy: deltas.append((dx, dy)))
        context = {
            "active": True,
            "target_type": "annotation",
            "annotation_path": "annotations/test.json",
            "annotation_points": [{"x": 10, "y": 10, "typeId": "ore"}],
            "coord_transform": {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0},
        }
        view.set_route_calibration_context(context)

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(25, 30), button=Qt.NoButton))
        updated_context = dict(context)
        updated_context["coord_transform"] = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 15.0, "offset_y": 20.0}
        view.set_route_calibration_context(updated_context)
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(35, 45), button=Qt.NoButton))

        self.assertEqual(deltas, [(15.0, 20.0), (10.0, 15.0)])
        self.assertEqual(view._view_center, QPointF(100, 100))

    def test_annotation_calibration_blank_drag_still_pans_map(self) -> None:
        view = self._view()
        deltas: list[tuple[float, float]] = []
        manual_changes: list[bool] = []
        view.route_calibration_drag_delta_requested.connect(lambda dx, dy: deltas.append((dx, dy)))
        view.manual_view_changed.connect(lambda: manual_changes.append(True))
        view.set_route_calibration_context({
            "active": True,
            "target_type": "annotation",
            "annotation_path": "annotations/test.json",
            "annotation_points": [{"x": 10, "y": 10, "typeId": "ore"}],
            "coord_transform": {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0},
        })

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(100, 100)))
        view.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, QPointF(120, 120), button=Qt.NoButton))

        self.assertEqual(deltas, [])
        self.assertNotEqual(view._view_center, QPointF(100, 100))
        self.assertEqual(manual_changes, [True])

    def test_annotation_calibration_blocks_context_menu(self) -> None:
        view = self._view()
        view.set_route_calibration_context({
            "active": True,
            "target_type": "annotation",
            "annotation_path": "annotations/test.json",
            "annotation_points": [{"x": 10, "y": 10, "typeId": "ore"}],
            "coord_transform": {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0},
        })
        event = self._ContextMenuEvent(QPointF(12, 34))

        view.contextMenuEvent(event)

        self.assertTrue(event.accepted)

    def test_drawing_node_drag_keeps_priority_over_route_node_drag(self) -> None:
        view = self._view()
        view.set_route_point_drag_enabled(True)
        view.set_route_drawing_context({
            "active": True,
            "paused": False,
            "points": [{"x": 10, "y": 10}],
        })

        view.mousePressEvent(self._mouse_event(QEvent.Type.MouseButtonPress, QPointF(10, 10)))

        self.assertEqual(view._drawing_drag_index, 0)
        self.assertIsNone(view._route_point_drag_index)

    def test_ctrl_z_uses_route_undo_only_outside_drawing_mode(self) -> None:
        view = self._view()
        route_undo_count: list[bool] = []
        drawing_undo_count: list[bool] = []
        view.route_point_move_undo_requested.connect(lambda: route_undo_count.append(True))
        view.drawing_undo_requested.connect(lambda: drawing_undo_count.append(True))
        view.set_route_point_move_undo_available(True)

        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Z, Qt.ControlModifier))

        self.assertEqual(route_undo_count, [True])
        self.assertEqual(drawing_undo_count, [])

        view.set_route_drawing_context({"active": True, "points": []})
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Z, Qt.ControlModifier))

        self.assertEqual(route_undo_count, [True])
        self.assertEqual(drawing_undo_count, [True])

    def test_undo_context_item_is_only_available_outside_drawing_mode(self) -> None:
        view = self._view()
        view.set_route_point_move_undo_available(True)

        items = view._route_point_undo_context_items()

        self.assertEqual(items[0].text, strings.UNDO_ROUTE_POINT_MOVE_MENU_LABEL)
        self.assertTrue(items[1].separator)

        view.set_route_drawing_context({"active": True, "points": []})

        self.assertEqual(view._route_point_undo_context_items(), [])

    def test_blank_menu_includes_add_annotated_point_when_not_drawing(self) -> None:
        route_mgr = _FakeRouteManager()
        route_mgr.hit_route = False
        view = self._view(route_mgr)
        view.set_route_point_drag_enabled(True)
        captured: dict[str, object] = {}

        def capture_menu(_parent, _global_pos, items, *, object_name: str = "") -> None:
            captured["items"] = list(items)
            captured["object_name"] = object_name

        with patch("ui_island.views.map_view.show_context_menu", capture_menu):
            view.contextMenuEvent(self._ContextMenuEvent(QPointF(12, 34)))

        items = captured["items"]
        labels = [item.text for item in items if not item.separator and item.visible]
        self.assertNotIn(strings.MAP_ADD_POINT_MENU_LABEL, labels)
        self.assertIn(strings.MAP_ADD_COLLECT_POINT_MENU_LABEL, labels)
        self.assertIn(strings.MAP_ADD_TELEPORT_POINT_MENU_LABEL, labels)
        self.assertIn(strings.MAP_ADD_GUIDE_POINT_MENU_LABEL, labels)
        self.assertIn(strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL, labels)

        emitted_nodes: list[tuple[int, int, object]] = []
        view.add_route_node_requested.connect(lambda x, y, node_type: emitted_nodes.append((x, y, node_type)))
        for label in (
            strings.MAP_ADD_COLLECT_POINT_MENU_LABEL,
            strings.MAP_ADD_TELEPORT_POINT_MENU_LABEL,
            strings.MAP_ADD_GUIDE_POINT_MENU_LABEL,
        ):
            item = next(item for item in items if item.text == label)
            item.callback()
        self.assertEqual(emitted_nodes, [(12, 34, "collect"), (12, 34, "teleport"), (12, 34, "virtual")])

        emitted: list[tuple[int, int]] = []
        view.add_annotated_point_requested.connect(lambda x, y: emitted.append((x, y)))
        annotated_item = next(item for item in items if item.text == strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL)
        annotated_item.callback()
        self.assertEqual(emitted, [(12, 34)])

    def test_blank_menu_hides_add_annotated_point_while_drawing(self) -> None:
        route_mgr = _FakeRouteManager()
        route_mgr.hit_route = False
        view = self._view(route_mgr)
        view.set_route_point_drag_enabled(True)
        view.set_route_drawing_context({"active": True, "points": []})
        captured: dict[str, object] = {}

        with patch(
            "ui_island.views.map_view.show_context_menu",
            lambda _parent, _global_pos, items, *, object_name="": captured.__setitem__("items", list(items)),
        ):
            view.contextMenuEvent(self._ContextMenuEvent(QPointF(12, 34)))

        labels = [item.text for item in captured["items"] if not item.separator and item.visible]
        self.assertNotIn(strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL, labels)

    def test_route_node_menu_includes_change_order_and_emits_signal(self) -> None:
        view = self._view()
        captured: dict[str, object] = {}

        with patch(
            "ui_island.views.map_view.show_context_menu",
            lambda _parent, _global_pos, items, *, object_name="": captured.__setitem__("items", list(items)),
        ):
            view.contextMenuEvent(self._ContextMenuEvent(QPointF(10, 10)))

        items = captured["items"]
        labels = [item.text for item in items if not item.separator and item.visible]
        self.assertIn(strings.CHANGE_POINT_ORDER_MENU_LABEL, labels)
        emitted: list[tuple[str, int]] = []
        view.change_point_order_requested.connect(lambda route_id, index: emitted.append((route_id, index)))
        order_item = next(item for item in items if item.text == strings.CHANGE_POINT_ORDER_MENU_LABEL)
        order_item.callback()
        self.assertEqual(emitted, [("route-1", 0)])

    def test_drawing_node_menu_includes_change_order_and_emits_signal(self) -> None:
        view = self._view()
        view.set_route_drawing_context({
            "active": True,
            "route_id": "route-1",
            "points": [{"x": 10, "y": 10}],
        })
        captured: dict[str, object] = {}

        with patch(
            "ui_island.views.map_view.show_context_menu",
            lambda _parent, _global_pos, items, *, object_name="": captured.__setitem__("items", list(items)),
        ):
            view.contextMenuEvent(self._ContextMenuEvent(QPointF(10, 10)))

        items = captured["items"]
        labels = [item.text for item in items if not item.separator and item.visible]
        self.assertIn(strings.CHANGE_POINT_ORDER_MENU_LABEL, labels)
        emitted: list[tuple[str, int]] = []
        view.change_point_order_requested.connect(lambda route_id, index: emitted.append((route_id, index)))
        order_item = next(item for item in items if item.text == strings.CHANGE_POINT_ORDER_MENU_LABEL)
        order_item.callback()
        self.assertEqual(emitted, [("route-1", 0)])


if __name__ == "__main__":
    unittest.main()

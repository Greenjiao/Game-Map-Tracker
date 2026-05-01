import os
import tempfile
import unittest
from enum import Enum
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ui_island.controllers.route_panel_controller import RoutePanelController
from ui_island.design import strings
from ui_island.dialogs.route_notes_dialog import _NODE_ICON_SIZE
from ui_island.services.route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL
from ui_island.state import RouteDrawingState


class _Mode(Enum):
    PAUSED = "paused"
    MAXIMIZED = "maximized"
    TRACKING_STABLE = "tracking_stable"


class _FakeSearchInput:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class _FakeSection:
    def __init__(self) -> None:
        self.visible: bool | None = None
        self.force_open: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def set_force_open(self, force_open: bool) -> None:
        self.force_open = bool(force_open)


class _FakeRouteItem:
    def __init__(self) -> None:
        self.visible: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakeCheckbox:
    def __init__(self) -> None:
        self.checked: bool | None = None
        self.blocked_states: list[bool] = []
        self.stylesheets: list[str] = []

    def blockSignals(self, blocked: bool) -> None:
        self.blocked_states.append(bool(blocked))

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheets.append(stylesheet)


class _FakeSize:
    def __init__(self, width: int = 0, height: int = 0) -> None:
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FakeMargins:
    def __init__(self, top: int = 0, bottom: int = 0) -> None:
        self._top = top
        self._bottom = bottom

    def top(self) -> int:
        return self._top

    def bottom(self) -> int:
        return self._bottom


class _FakeTrackedLayout:
    def __init__(self) -> None:
        self._margins = _FakeMargins(top=2, bottom=3)

    def contentsMargins(self) -> _FakeMargins:
        return self._margins

    def spacing(self) -> int:
        return 4


class _FakeTrackedHeader:
    def sizeHint(self) -> _FakeSize:
        return _FakeSize(height=20)


class _FakeTrackedGrid:
    def verticalSpacing(self) -> int:
        return 6


class _FakeTrackedScroll:
    def __init__(self) -> None:
        self.visible = True
        self.fixed_height: int | None = None

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def setFixedHeight(self, height: int) -> None:
        self.fixed_height = height


class _FakeTrackedCard:
    def __init__(self) -> None:
        self.minimum_height: int | None = None
        self.maximum_height: int | None = None

    def setMinimumHeight(self, height: int) -> None:
        self.minimum_height = height

    def setMaximumHeight(self, height: int) -> None:
        self.maximum_height = height


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.checked: bool | None = None
        self.visible: bool | None = None
        self.blocked_states: list[bool] = []

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)

    def blockSignals(self, blocked: bool) -> None:
        self.blocked_states.append(bool(blocked))

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakeToolbar:
    def __init__(self) -> None:
        self.shown = False
        self.raised = False

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        self.raised = True


class _FakeWindowModeController:
    def __init__(self) -> None:
        self.layout_refresh_count = 0

    def schedule_layout_refresh(self) -> None:
        self.layout_refresh_count += 1


class _FakeMapView:
    def __init__(self) -> None:
        self.focus_calls: list[tuple[int, int]] = []
        self.refresh_count = 0

    def focus_map_position(self, x: int, y: int) -> None:
        self.focus_calls.append((x, y))

    def _refresh_from_last_frame(self) -> None:
        self.refresh_count += 1


class _FakeRouteManager:
    def __init__(self, routes: dict[str, dict] | None = None) -> None:
        self.routes = routes or {}
        self.visibility: dict[str, bool] = {}
        self.save_visibility_count = 0
        self.colors: dict[str, tuple[int, int, int]] = {}
        self.saved_points_calls: list[tuple[str, list[dict], bool | None]] = []
        self.saved_notes_calls: list[tuple[str, str, str, str | None]] = []
        self.saved_enable_versions_calls: list[tuple[str, list[str]]] = []
        self._new_point_id = 0

    @staticmethod
    def route_id(route: dict | None) -> str:
        return str(route.get("id") or "") if isinstance(route, dict) else ""

    def iter_routes(self):
        for route in self.routes.values():
            yield str(route.get("category") or "category"), route

    def route_for_id(self, route_id: str) -> dict | None:
        return self.routes.get(route_id)

    def route_name_for_id(self, route_id: str) -> str:
        route = self.routes.get(route_id)
        return str(route.get("display_name") or route_id) if route is not None else ""

    def save_visibility(self) -> None:
        self.save_visibility_count += 1

    def visible_routes(self) -> list[dict]:
        return [
            route
            for route_id, route in self.routes.items()
            if self.visibility.get(route_id, False)
        ]

    def has_progress(self, _route_id: str) -> bool:
        return False

    def color_for(self, route_id: str) -> tuple[int, int, int]:
        return self.colors.get(route_id, (10, 20, 30))

    def route_color_override(self, route_id: str) -> str:
        route = self.routes.get(route_id)
        return str(route.get("color") or "") if route is not None else ""

    def point_icon_path_for(self, _type_id: str) -> str:
        return ""

    def get_route_notes(self, category: str, name: str) -> str:
        route = self._route_by_category_name(category, name)
        return str(route.get("notes") or "") if route is not None else ""

    def route_enable_versions(self, route_id: str) -> list[str] | None:
        route = self.routes.get(route_id)
        enable_versions = route.get("enable_versions") if route is not None else None
        if not isinstance(enable_versions, list):
            return None
        return [str(item).strip() for item in enable_versions if str(item or "").strip()]

    def update_route_enable_versions(self, route_id: str, versions: list[str]) -> bool:
        route = self.routes.get(route_id)
        if route is None:
            return False
        cleaned = []
        for item in versions:
            value = str(item or "").strip()
            if value and value not in cleaned:
                cleaned.append(value)
        if cleaned:
            route["enable_versions"] = cleaned
        else:
            route.pop("enable_versions", None)
        self.saved_enable_versions_calls.append((route_id, cleaned))
        return True

    def update_route_notes_and_color(
        self,
        category: str,
        name: str,
        notes: str,
        color: str | None,
    ) -> bool:
        route = self._route_by_category_name(category, name)
        if route is None:
            return False
        route["notes"] = notes
        if color is None:
            route.pop("color", None)
        else:
            route["color"] = color
            raw = color[1:] if color.startswith("#") else color
            self.colors[str(route.get("id") or "")] = (int(raw[4:6], 16), int(raw[2:4], 16), int(raw[0:2], 16))
        self.saved_notes_calls.append((category, name, notes, color))
        return True

    def new_route_point_id(self) -> str:
        self._new_point_id += 1
        return f"point-{self._new_point_id}"

    def save_route_points(self, route_id: str, points: list[dict], loop: bool | None = None) -> bool:
        route = self.routes.get(route_id)
        if route is None:
            return False
        saved_points = [dict(point) for point in points]
        route["points"] = saved_points
        if loop is not None:
            route["loop"] = bool(loop)
        self.saved_points_calls.append((route_id, [dict(point) for point in saved_points], loop))
        return True

    def _route_by_category_name(self, category: str, name: str) -> dict | None:
        return next(
            (
                route
                for known_category, route in self.iter_routes()
                if known_category == category and route.get("display_name") == name
            ),
            None,
        )


class _FakeWindow:
    def __init__(self, search_text: str = "") -> None:
        self.search_input = _FakeSearchInput(search_text)
        self._route_sections: dict[str, _FakeSection] = {}
        self._route_widgets_by_category: dict[str, list[tuple[str, str, _FakeRouteItem]]] = {}
        self._route_checkboxes: dict[str, list[_FakeCheckbox]] = {}
        self.tracked_refreshed_count = 0
        self._mode = _Mode.PAUSED
        self.route_mgr = _FakeRouteManager()
        self.map_view = _FakeMapView()
        self.relocate_calls: list[tuple[int, int]] = []

    def _on_relocate(self, x: int, y: int) -> None:
        self.relocate_calls.append((x, y))

    def frameGeometry(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            return screen.availableGeometry()
        from PySide6.QtCore import QRect

        return QRect(0, 0, 800, 600)


class _ToolbarHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.search_input = _FakeSearchInput("")
        self._route_sections: dict[str, _FakeSection] = {}
        self._route_widgets_by_category: dict[str, list[tuple[str, str, _FakeRouteItem]]] = {}
        self._route_checkboxes: dict[str, list[_FakeCheckbox]] = {}
        self.tracked_refreshed_count = 0
        self.route_mgr = _FakeRouteManager()
        self.map_view = _FakeMapView()
        self.route_drawing_state = RouteDrawingState()
        self.resize(800, 600)

    def isMaximized(self) -> bool:
        return False


class RoutePanelFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _controller_for(self, window: _FakeWindow) -> RoutePanelController:
        controller = RoutePanelController.__new__(RoutePanelController)
        controller.window = window
        controller._route_notes_session = None
        controller.refresh_tracked_routes = lambda: setattr(
            window,
            "tracked_refreshed_count",
            window.tracked_refreshed_count + 1,
        )
        controller.confirm_exit_route_drawing = lambda: True
        return controller

    def test_empty_category_stays_visible_without_search_term(self) -> None:
        window = _FakeWindow("")
        section = _FakeSection()
        window._route_sections["空分类"] = section
        window._route_widgets_by_category["空分类"] = []

        self._controller_for(window).apply_route_filter()

        self.assertTrue(section.visible)
        self.assertFalse(section.force_open)

    def test_empty_category_hides_when_searching(self) -> None:
        window = _FakeWindow("采集")
        section = _FakeSection()
        window._route_sections["空分类"] = section
        window._route_widgets_by_category["空分类"] = []

        self._controller_for(window).apply_route_filter()

        self.assertFalse(section.visible)
        self.assertFalse(section.force_open)

    def test_matching_category_shows_and_force_opens_when_searching(self) -> None:
        window = _FakeWindow("矿")
        section = _FakeSection()
        route_item = _FakeRouteItem()
        window._route_sections["资源"] = section
        window._route_widgets_by_category["资源"] = [("route-1", "矿物采集", route_item)]

        self._controller_for(window).apply_route_filter()

        self.assertTrue(route_item.visible)
        self.assertTrue(section.visible)
        self.assertTrue(section.force_open)

    def test_route_checkbox_stylesheet_uses_route_color_as_rgb(self) -> None:
        stylesheet = RoutePanelController.route_checkbox_stylesheet((10, 20, 30))

        self.assertIn("rgb(30, 20, 10)", stylesheet)

    def test_refresh_route_checkbox_colors_updates_registered_widgets(self) -> None:
        window = _FakeWindow("")
        checkbox_a = _FakeCheckbox()
        checkbox_b = _FakeCheckbox()
        checkbox_other = _FakeCheckbox()
        window._route_checkboxes = {
            "route-1": [checkbox_a, checkbox_b],
            "route-2": [checkbox_other],
        }
        window.route_mgr.colors = {
            "route-1": (1, 2, 3),
            "route-2": (40, 50, 60),
        }

        self._controller_for(window).refresh_route_checkbox_colors()

        self.assertIn("rgb(3, 2, 1)", checkbox_a.stylesheets[-1])
        self.assertIn("rgb(3, 2, 1)", checkbox_b.stylesheets[-1])
        self.assertIn("rgb(60, 50, 40)", checkbox_other.stylesheets[-1])

    def test_route_notes_dialog_saves_color_only_change_and_refreshes_display(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "id": "route-1",
                "category": "矿物",
                "display_name": "矿线",
                "notes": "old",
                "points": [{"x": 1, "y": 2, "typeId": "ore", "type": "矿石"}],
            }
        })
        checkbox = _FakeCheckbox()
        window._route_checkboxes = {"route-1": [checkbox]}
        controller = self._controller_for(window)

        with (
            patch(
                "ui_island.controllers.route_panel_controller.edit_route_notes",
                return_value=(True, "old", "#112233", False, [{"x": 1, "y": 2}]),
            ),
            patch("ui_island.controllers.route_panel_controller.toast"),
        ):
            controller.show_route_notes_dialog("矿物", "矿线")

        self.assertEqual(window.route_mgr.saved_notes_calls, [("矿物", "矿线", "old", "#112233")])
        self.assertEqual(window.route_mgr.saved_points_calls, [])
        self.assertIn("rgb(17, 34, 51)", checkbox.stylesheets[-1])
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_route_notes_dialog_saves_notes_change_even_when_color_is_unchanged(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "id": "route-1",
                "category": "矿物",
                "display_name": "矿线",
                "notes": "old",
                "color": "#112233",
                "points": [],
            }
        })
        controller = self._controller_for(window)

        with (
            patch(
                "ui_island.controllers.route_panel_controller.edit_route_notes",
                return_value=(True, "new", "#112233", False, []),
            ),
            patch("ui_island.controllers.route_panel_controller.toast"),
        ):
            controller.show_route_notes_dialog("矿物", "矿线")

        self.assertEqual(window.route_mgr.saved_notes_calls, [("矿物", "矿线", "new", "#112233")])
        self.assertEqual(window.route_mgr.saved_points_calls, [])
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_route_notes_dialog_saves_node_changes_without_notes_change(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "id": "route-1",
                "category": "矿物",
                "display_name": "矿线",
                "notes": "old",
                "points": [{"x": 1, "y": 2, "label": "A"}, {"x": 3, "y": 4, "label": "B"}],
            }
        })
        controller = self._controller_for(window)
        edited_nodes = [{"x": 3, "y": 4, "label": "B"}, {"x": 1, "y": 2, "label": "A2"}]

        with (
            patch(
                "ui_island.controllers.route_panel_controller.edit_route_notes",
                return_value=(True, "old", None, True, edited_nodes),
            ),
            patch("ui_island.controllers.route_panel_controller.toast"),
        ):
            controller.show_route_notes_dialog("矿物", "矿线")

        self.assertEqual(window.route_mgr.saved_notes_calls, [])
        self.assertEqual(window.route_mgr.saved_points_calls, [("route-1", edited_nodes, None)])
        self.assertEqual(window.route_mgr.routes["route-1"]["points"], edited_nodes)
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_route_notes_dialog_saves_notes_and_nodes_together(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "id": "route-1",
                "category": "矿物",
                "display_name": "矿线",
                "notes": "old",
                "points": [{"x": 1, "y": 2}],
            }
        })
        controller = self._controller_for(window)
        edited_nodes = [{"x": 1, "y": 2, "typeId": "ore", "type": "矿石"}]

        with (
            patch(
                "ui_island.controllers.route_panel_controller.edit_route_notes",
                return_value=(True, "new", "#112233", True, edited_nodes),
            ),
            patch("ui_island.controllers.route_panel_controller.toast"),
        ):
            controller.show_route_notes_dialog("矿物", "矿线")

        self.assertEqual(window.route_mgr.saved_notes_calls, [("矿物", "矿线", "new", "#112233")])
        self.assertEqual(window.route_mgr.saved_points_calls, [("route-1", edited_nodes, None)])
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_route_notes_dialog_saves_enable_versions_without_auto_restoring_current_version(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "id": "route-1",
                "category": "鐭跨墿",
                "display_name": "鐭跨嚎",
                "notes": "old",
                "enable_versions": ["old-format", "GMT-N-0.1.3"],
                "points": [],
            }
        })
        controller = self._controller_for(window)

        with (
            patch(
                "ui_island.controllers.route_panel_controller.edit_route_notes",
                return_value=(True, "old", None, False, [], True, ["old-format"]),
            ),
            patch("ui_island.controllers.route_panel_controller.toast"),
        ):
            controller.show_route_notes_dialog("鐭跨墿", "鐭跨嚎")

        self.assertEqual(window.route_mgr.saved_notes_calls, [])
        self.assertEqual(window.route_mgr.saved_points_calls, [])
        self.assertEqual(window.route_mgr.saved_enable_versions_calls, [("route-1", ["old-format"])])
        self.assertEqual(window.route_mgr.routes["route-1"]["enable_versions"], ["old-format"])
        self.assertEqual(window.map_view.refresh_count, 1)


    def test_category_select_all_selects_only_category_and_saves_once(self) -> None:
        window = _FakeWindow("")
        window.route_mgr.visibility = {"route-1": False, "route-2": True, "other": False}
        route_1_checkbox = _FakeCheckbox()
        route_2_checkbox = _FakeCheckbox()
        other_checkbox = _FakeCheckbox()
        window._route_checkboxes = {
            "route-1": [route_1_checkbox],
            "route-2": [route_2_checkbox],
            "other": [other_checkbox],
        }
        window._route_widgets_by_category = {
            "cat-a": [
                ("route-1", "Route 1", _FakeRouteItem()),
                ("route-2", "Route 2", _FakeRouteItem()),
            ],
            "cat-b": [("other", "Other", _FakeRouteItem())],
        }

        self._controller_for(window).set_category_routes_visibility("cat-a", "select_all")

        self.assertEqual(window.route_mgr.visibility, {"route-1": True, "route-2": True, "other": False})
        self.assertEqual(window.route_mgr.save_visibility_count, 1)
        self.assertTrue(route_1_checkbox.checked)
        self.assertIsNone(other_checkbox.checked)
        self.assertEqual(window.tracked_refreshed_count, 1)
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_category_invert_flips_only_category_and_saves_once(self) -> None:
        window = _FakeWindow("")
        window.route_mgr.visibility = {"route-1": True, "route-2": False, "other": True}
        route_1_checkbox = _FakeCheckbox()
        route_2_checkbox = _FakeCheckbox()
        other_checkbox = _FakeCheckbox()
        window._route_checkboxes = {
            "route-1": [route_1_checkbox],
            "route-2": [route_2_checkbox],
            "other": [other_checkbox],
        }
        window._route_widgets_by_category = {
            "cat-a": [
                ("route-1", "Route 1", _FakeRouteItem()),
                ("route-2", "Route 2", _FakeRouteItem()),
            ],
            "cat-b": [("other", "Other", _FakeRouteItem())],
        }

        self._controller_for(window).set_category_routes_visibility("cat-a", "invert")

        self.assertEqual(window.route_mgr.visibility, {"route-1": False, "route-2": True, "other": True})
        self.assertEqual(window.route_mgr.save_visibility_count, 1)
        self.assertFalse(route_1_checkbox.checked)
        self.assertTrue(route_2_checkbox.checked)
        self.assertIsNone(other_checkbox.checked)
        self.assertEqual(window.tracked_refreshed_count, 1)
        self.assertEqual(window.map_view.refresh_count, 1)

    def test_tracked_routes_collapse_hides_scroll_and_restores_height(self) -> None:
        window = _FakeWindow("")
        window.route_mgr.routes = {"route-1": {"display_name": "Route 1"}}
        window.route_mgr.visibility = {"route-1": True}
        window.tracked_routes_collapsed = False
        window.tracked_routes_toggle_btn = _FakeButton()
        window.tracked_routes_scroll = _FakeTrackedScroll()
        window.tracked_routes_layout = _FakeTrackedLayout()
        window.tracked_routes_header = _FakeTrackedHeader()
        window.tracked_routes_grid = _FakeTrackedGrid()
        window.tracked_routes_card = _FakeTrackedCard()
        window.window_mode_controller = _FakeWindowModeController()
        controller = self._controller_for(window)

        controller.set_tracked_routes_collapsed(True)

        self.assertTrue(window.tracked_routes_collapsed)
        self.assertEqual(window.tracked_routes_toggle_btn.text, "▸")
        self.assertEqual(window.tracked_routes_toggle_btn.tooltip, "展开当前追踪路线")
        self.assertFalse(window.tracked_routes_scroll.visible)
        self.assertEqual(window.tracked_routes_scroll.fixed_height, 0)
        self.assertEqual(window.tracked_routes_card.minimum_height, 25)
        self.assertEqual(window.window_mode_controller.layout_refresh_count, 1)

        controller.set_tracked_routes_collapsed(False)

        self.assertFalse(window.tracked_routes_collapsed)
        self.assertEqual(window.tracked_routes_toggle_btn.text, "▾")
        self.assertEqual(window.tracked_routes_toggle_btn.tooltip, "收起当前追踪路线")
        self.assertTrue(window.tracked_routes_scroll.visible)
        self.assertGreater(window.tracked_routes_scroll.fixed_height, 0)
        self.assertGreater(window.tracked_routes_card.minimum_height, 25)
        self.assertEqual(window.window_mode_controller.layout_refresh_count, 2)

    def test_route_drawing_loop_change_marks_state_dirty(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="采集",
            name="路线",
            points=[{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}],
            loop=False,
        )
        controller = self._controller_for(window)

        controller._mark_drawing_dirty()
        self.assertFalse(window.route_drawing_state.dirty)

        window.route_drawing_state.loop = True
        controller._mark_drawing_dirty()

        self.assertTrue(window.route_drawing_state.dirty)

    def test_drawing_point_node_type_change_marks_dirty_and_undo_restores(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2, "node_type": "collect"}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.set_drawing_point_node_type(0, "teleport"))
        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "teleport")
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "collect")
        self.assertFalse(window.route_drawing_state.dirty)

    def test_drawing_point_node_type_defaults_missing_type_to_collect(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.set_drawing_point_node_type(0, ""))
        self.assertEqual(window.route_drawing_state.draft_points[0]["node_type"], "collect")
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        self.assertNotIn("node_type", window.route_drawing_state.draft_points[0])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_move_drawing_point_updates_draft_and_marks_dirty(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.move_drawing_point(0, 10, 20))

        self.assertEqual(window.route_drawing_state.draft_points[0]["x"], 10)
        self.assertEqual(window.route_drawing_state.draft_points[0]["y"], 20)
        self.assertTrue(window.route_drawing_state.dirty)
        self.assertEqual(window.route_drawing_state.undo_stack, [])

    def test_finish_move_drawing_point_records_undo_and_undo_restores(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2, "node_type": "collect"}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.move_drawing_point(0, 10, 20, sync=False))
        self.assertTrue(controller.finish_move_drawing_point(0, 1, 2, 10, 20))

        self.assertEqual(window.route_drawing_state.undo_stack[-1]["op"], "move")
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        point = window.route_drawing_state.draft_points[0]
        self.assertEqual(point["x"], 1)
        self.assertEqual(point["y"], 2)
        self.assertEqual(point["node_type"], "collect")
        self.assertFalse(window.route_drawing_state.dirty)

    def test_finish_move_drawing_point_ignores_unchanged_position(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertFalse(controller.finish_move_drawing_point(0, 1, 2, 1, 2))

        self.assertEqual(window.route_drawing_state.undo_stack, [])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_reorder_drawing_point_moves_forward_and_undo_restores(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 10, "y": 0}, {"id": "c", "x": 20, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.reorder_drawing_point(0, 2))

        self.assertEqual([point["id"] for point in window.route_drawing_state.draft_points], ["b", "c", "a"])
        self.assertEqual(window.route_drawing_state.undo_stack[-1], {"op": "reorder", "from": 0, "to": 2})
        self.assertTrue(window.route_drawing_state.dirty)

        controller.undo_route_drawing()

        self.assertEqual([point["id"] for point in window.route_drawing_state.draft_points], ["a", "b", "c"])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_reorder_drawing_point_moves_backward_and_ignores_same_position(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 10, "y": 0}, {"id": "c", "x": 20, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertFalse(controller.reorder_drawing_point(1, 1))
        self.assertEqual(window.route_drawing_state.undo_stack, [])

        self.assertTrue(controller.reorder_drawing_point(2, 0))

        self.assertEqual([point["id"] for point in window.route_drawing_state.draft_points], ["c", "a", "b"])
        self.assertEqual(window.route_drawing_state.undo_stack[-1], {"op": "reorder", "from": 2, "to": 0})

    def test_change_drawing_point_order_uses_dialog_target(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 10, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch("ui_island.controllers.route_panel_controller.open_point_order_dialog", return_value=1) as dialog:
            controller.change_drawing_point_order(0)

        dialog.assert_called_once_with(window, "route", 0, 2)
        self.assertEqual([point["id"] for point in window.route_drawing_state.draft_points], ["b", "a"])

    def test_save_route_drawing_writes_reordered_draft_order(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "2026010101": {
                "points": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 10, "y": 0}],
                "loop": False,
            }
        })
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 10, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        self.assertTrue(controller.reorder_drawing_point(0, 1))
        with patch("ui_island.controllers.route_panel_controller.toast"):
            self.assertTrue(controller.save_route_drawing())

        self.assertEqual([point["id"] for point in window.route_mgr.saved_points_calls[-1][1]], ["b", "a"])

    def test_append_drawing_point_defaults_to_end(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(10, 0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
            (10, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 2)

    def test_append_drawing_point_with_point_fields_binds_annotation_to_draft(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(route_id="2026010101", category="routes", name="route", points=[])
        window.route_drawing_state.node_type = "teleport"
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(
            10,
            20,
            point_fields={
                "typeId": "ore",
                "type": "矿石",
                "label": "黑矿",
                "radius": 30,
                "sourceId": "source-1",
                "manual": True,
                "node_type": "virtual",
                "visited": True,
            },
        )

        point = window.route_drawing_state.draft_points[-1]
        self.assertEqual(point["typeId"], "ore")
        self.assertEqual(point["type"], "矿石")
        self.assertEqual(point["label"], "黑矿")
        self.assertEqual(point["radius"], 30)
        self.assertEqual(point["sourceId"], "source-1")
        self.assertTrue(point["manual"])
        self.assertEqual(point["node_type"], "virtual")
        self.assertNotIn("visited", point)
        self.assertTrue(point["_drawing_new"])

    def test_change_drawing_point_annotation_syncs_node_type_with_resolver(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2, "node_type": "virtual"}],
        )
        window.route_mgr.annotation_type_items = lambda: [{"typeId": "ore", "type": "鐭跨煶"}]
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch(
            "ui_island.controllers.route_panel_controller.open_annotation_type_picker",
            return_value={"typeId": "ore", "type": "鐭跨煶"},
        ):
            controller.change_drawing_point_annotation(0, node_type_resolver=lambda _type_id: "collect")

        point = window.route_drawing_state.draft_points[0]
        self.assertEqual(point["typeId"], "ore")
        self.assertEqual(point["node_type"], "collect")

    def test_append_drawing_point_node_type_override_wins_over_toolbar_state(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(route_id="2026010101", category="routes", name="route", points=[])
        window.route_drawing_state.node_type = "collect"
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(10, 20, node_type_override="teleport")

        point = window.route_drawing_state.draft_points[-1]
        self.assertEqual(point["node_type"], "teleport")

    def test_append_drawing_point_can_insert_after_nearest_node(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 200, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(110, 0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
            (110, 0),
            (200, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 2)

    def test_append_drawing_point_can_use_explicit_index_override(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(10, 0, index_override=0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (10, 0),
            (0, 0),
            (100, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 0)

    def test_append_drawing_point_clamps_explicit_index_override(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(10, 0, index_override=99)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (10, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 1)

    def test_append_drawing_point_tie_uses_earlier_nearest_node(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 10, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(5, 0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (5, 0),
            (10, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 1)

    def test_append_drawing_point_handles_empty_and_single_point_routes(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(route_id="2026010101", category="routes", name="route", points=[])
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(1, 2)
        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [(1, 2)])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 0)

        controller.append_drawing_point(3, 4)
        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (1, 2),
            (3, 4),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 1)

    def test_undo_removes_auto_inserted_point_from_recorded_index(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(10, 0)
        controller.undo_route_drawing()

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
        ])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_context_menu_drawing_point_insert_at_end_skips_position_dialog(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch("ui_island.controllers.route_panel_controller.open_insert_point_dialog") as dialog:
            controller.append_drawing_point_from_context_menu(10, 0)

        dialog.assert_not_called()
        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
            (10, 0),
        ])

    def test_context_menu_drawing_point_uses_default_suggestion_when_dialog_unchanged(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 200, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch(
            "ui_island.controllers.route_panel_controller.open_insert_point_dialog",
            return_value=(["2026010101"], {}),
        ) as dialog:
            controller.append_drawing_point_from_context_menu(110, 0)

        dialog.assert_called_once()
        args = dialog.call_args.args
        self.assertEqual(args[1:3], (110, 0))
        self.assertEqual(args[3][0]["suggested_index"], 2)
        self.assertEqual(args[3][0]["points_count"], 3)
        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
            (110, 0),
            (200, 0),
        ])

    def test_context_menu_drawing_point_uses_dialog_override(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch(
            "ui_island.controllers.route_panel_controller.open_insert_point_dialog",
            return_value=(["2026010101"], {"2026010101": 0}),
        ):
            controller.append_drawing_point_from_context_menu(10, 0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (10, 0),
            (0, 0),
            (100, 0),
        ])
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 0)

    def test_context_menu_drawing_point_with_point_fields_uses_dialog_override(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch(
            "ui_island.controllers.route_panel_controller.open_insert_point_dialog",
            return_value=(["2026010101"], {"2026010101": 0}),
        ):
            controller.append_drawing_point_from_context_menu(
                10,
                0,
                point_fields={"typeId": "ore", "type": "矿石", "label": "黑矿"},
            )

        point = window.route_drawing_state.draft_points[0]
        self.assertEqual((point["x"], point["y"]), (10, 0))
        self.assertEqual(point["typeId"], "ore")
        self.assertEqual(point["type"], "矿石")
        self.assertEqual(point["label"], "黑矿")
        self.assertEqual(window.route_drawing_state.undo_stack[-1]["index"], 0)

    def test_context_menu_drawing_point_cancel_or_unselected_does_not_insert(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch("ui_island.controllers.route_panel_controller.open_insert_point_dialog", return_value=None):
            controller.append_drawing_point_from_context_menu(10, 0)
        with patch(
            "ui_island.controllers.route_panel_controller.open_insert_point_dialog",
            return_value=([], {}),
        ):
            controller.append_drawing_point_from_context_menu(20, 0)

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [(0, 0)])
        self.assertEqual(window.route_drawing_state.undo_stack, [])

    def test_undo_removes_context_menu_inserted_point_from_recorded_index(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch(
            "ui_island.controllers.route_panel_controller.open_insert_point_dialog",
            return_value=(["2026010101"], {"2026010101": 0}),
        ):
            controller.append_drawing_point_from_context_menu(10, 0)
        controller.undo_route_drawing()

        self.assertEqual([(point["x"], point["y"]) for point in window.route_drawing_state.draft_points], [
            (0, 0),
            (100, 0),
        ])
        self.assertFalse(window.route_drawing_state.dirty)

    def test_save_route_drawing_preserves_insert_at_end_without_writing_route_field(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({
            "2026010101": {
                "points": [{"x": 1, "y": 2}],
                "loop": False,
            }
        })
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2}],
        )
        window.route_drawing_state.insert_at_end = False
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        with patch("ui_island.controllers.route_panel_controller.toast"):
            self.assertTrue(controller.save_route_drawing())

        self.assertFalse(window.route_drawing_state.insert_at_end)
        self.assertNotIn("insert_at_end", window.route_mgr.routes["2026010101"])
        self.assertNotIn("insert_at_end", window.route_mgr.saved_points_calls[-1][1][0])

    def test_save_route_drawing_writes_annotation_fields_and_strips_drawing_flags(self) -> None:
        window = _FakeWindow("")
        window.route_mgr = _FakeRouteManager({"2026010101": {"points": []}})
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(route_id="2026010101", category="routes", name="route", points=[])
        controller = self._controller_for(window)
        controller._sync_route_drawing_ui = lambda: None

        controller.append_drawing_point(
            10,
            20,
            point_fields={"typeId": "ore", "type": "矿石", "label": "黑矿"},
        )
        with patch("ui_island.controllers.route_panel_controller.toast"):
            self.assertTrue(controller.save_route_drawing())

        saved_point = window.route_mgr.saved_points_calls[-1][1][0]
        self.assertEqual(saved_point["typeId"], "ore")
        self.assertEqual(saved_point["type"], "矿石")
        self.assertEqual(saved_point["label"], "黑矿")
        self.assertNotIn("_drawing_new", saved_point)

    def test_update_route_drawing_toolbar_syncs_insert_at_end_checkbox(self) -> None:
        window = _FakeWindow("")
        window.route_drawing_state = RouteDrawingState()
        window.route_drawing_state.begin(route_id="2026010101", category="routes", name="route", points=[])
        window.route_drawing_state.insert_at_end = False
        window.route_drawing_toolbar = _FakeToolbar()
        window.route_drawing_toolbar_buttons = {
            "pause": _FakeButton(),
            "collect": _FakeButton(),
            "insert_at_end": _FakeButton(),
            "add_annotation": _FakeButton(),
            "same_annotation": _FakeButton(),
            "hide_other_routes": _FakeButton(),
            "loop": _FakeButton(),
            "select_annotation": _FakeButton(),
        }
        controller = self._controller_for(window)
        controller.position_route_drawing_toolbar = lambda: None

        controller._update_route_drawing_toolbar()

        self.assertFalse(window.route_drawing_toolbar_buttons["insert_at_end"].checked)
        self.assertEqual(window.route_drawing_toolbar_buttons["insert_at_end"].blocked_states, [True, False])
        self.assertTrue(window.route_drawing_toolbar.shown)

    def test_route_drawing_toolbar_node_panel_uses_right_picker_and_small_icons(self) -> None:
        window = _ToolbarHost()
        window.route_drawing_state.begin(
            route_id="2026010101",
            category="routes",
            name="route",
            points=[{"x": 1, "y": 2, "typeId": "ore", "type": "鐭跨煶"}],
        )
        window.route_mgr = _FakeRouteManager({"2026010101": {"points": []}})
        window.route_mgr.annotation_type_items = lambda: [{"typeId": "ore", "type": "鐭跨煶"}]
        controller = self._controller_for(window)

        controller._ensure_route_drawing_toolbar()
        controller._update_route_drawing_toolbar()
        self._app.processEvents()

        toolbar = window.route_drawing_toolbar
        node_panel = window.route_drawing_node_panel
        stats = node_panel.findChild(QWidget, "RouteNotesStatsPanel")
        stats_scroll = node_panel.findChild(QWidget, "RouteNotesStatsScroll")
        node_scroll = node_panel.findChild(QWidget, "RouteNotesNodeScroll")
        icons = node_panel.findChildren(QPushButton, "RouteNotesNodeIcon")
        self.assertIs(node_panel._annotation_picker_anchor, toolbar)
        self.assertEqual(node_panel._annotation_picker_placement, "right_of")
        self.assertIsNotNone(stats)
        self.assertIsNotNone(stats_scroll)
        self.assertIsNotNone(node_scroll)
        self.assertLess(stats_scroll.geometry().y(), node_scroll.geometry().y())
        self.assertTrue(icons)
        self.assertTrue(all(icon.iconSize() == QSize(_NODE_ICON_SIZE, _NODE_ICON_SIZE) for icon in icons))

    def test_route_drawing_toolbar_node_panel_hydrates_annotation_icons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            icon_path = os.path.join(tmpdir, "ore.png")
            pixmap = QPixmap(_NODE_ICON_SIZE, _NODE_ICON_SIZE)
            pixmap.fill(QColor("#00ff00"))
            self.assertTrue(pixmap.save(icon_path))

            window = _ToolbarHost()
            window.route_drawing_state.begin(
                route_id="2026010101",
                category="routes",
                name="route",
                points=[{"x": 1, "y": 2, "typeId": "ore", "type": "Ore"}],
            )
            window.route_mgr = _FakeRouteManager({"2026010101": {"points": []}})
            window.route_mgr.annotation_type_items = lambda: [{"typeId": "ore", "type": "Ore"}]
            window.route_mgr.point_icon_path_for = lambda type_id: icon_path if type_id == "ore" else ""
            controller = self._controller_for(window)

            controller._ensure_route_drawing_toolbar()
            controller._update_route_drawing_toolbar()
            self._app.processEvents()

            node_panel = window.route_drawing_node_panel
            icons = node_panel.findChildren(QPushButton, "RouteNotesNodeIcon")
            self.assertIs(node_panel._annotation_icon_path_provider, window.route_mgr.point_icon_path_for)
            self.assertTrue(icons)
            self.assertFalse(icons[0].property("fallbackIcon"))
            self.assertNotIn("icon_path", node_panel.draft_nodes()[0])

    def test_jump_to_route_node_paused_relocates_to_first_valid_node(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.PAUSED
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": "bad", "y": 2},
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": False},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast"):
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.relocate_calls, [(10, 20)])
        self.assertEqual(window.map_view.focus_calls, [])

    def test_jump_to_route_node_navigation_focuses_first_unvisited_without_relocating(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": False},
                    {"x": 50, "y": 60, "visited": False},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast"):
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.map_view.focus_calls, [(30, 40)])
        self.assertEqual(window.relocate_calls, [])

    def test_jump_to_route_node_navigation_completed_falls_back_to_first_node(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({
            "route-1": {
                "points": [
                    {"x": 10, "y": 20, "visited": True},
                    {"x": 30, "y": 40, "visited": True},
                ],
            }
        })
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.toast") as toast_mock:
            controller.jump_to_route_node("route-1")

        self.assertEqual(window.map_view.focus_calls, [(10, 20)])
        self.assertEqual(window.relocate_calls, [])
        self.assertIn("1", toast_mock.call_args.args[1])

    def test_jump_to_route_node_empty_route_shows_info_without_moving(self) -> None:
        window = _FakeWindow("")
        window._mode = _Mode.TRACKING_STABLE
        window.route_mgr = _FakeRouteManager({"route-1": {"points": [{"x": "bad"}]}})
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.styled_info") as info_mock:
            controller.jump_to_route_node("route-1")

        self.assertTrue(info_mock.called)
        self.assertEqual(window.map_view.focus_calls, [])
        self.assertEqual(window.relocate_calls, [])

    def test_current_position_add_menu_contains_new_node_actions(self) -> None:
        window = _FakeWindow("")
        window._last_player_xy = (12, 34)
        window.map_interaction_controller = Mock()
        controller = self._controller_for(window)
        anchor = QPushButton()

        with patch("ui_island.controllers.route_panel_controller.show_context_menu") as menu:
            controller.show_current_position_add_menu("route-1", anchor)

        menu.assert_called_once()
        items = list(menu.call_args.args[2])
        self.assertEqual(
            [item.text for item in items],
            [
                strings.MAP_ADD_COLLECT_POINT_MENU_LABEL,
                strings.MAP_ADD_TELEPORT_POINT_MENU_LABEL,
                strings.MAP_ADD_GUIDE_POINT_MENU_LABEL,
                strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL,
            ],
        )

        items[0].callback()
        window.map_interaction_controller.add_route_node_from_context_menu.assert_called_once_with(
            12,
            34,
            NODE_TYPE_COLLECT,
            route_ids=["route-1"],
            show_dialog=False,
        )
        window.map_interaction_controller.reset_mock()

        items[1].callback()
        window.map_interaction_controller.add_route_node_from_context_menu.assert_called_once_with(
            12,
            34,
            NODE_TYPE_TELEPORT,
            route_ids=["route-1"],
            show_dialog=False,
        )
        window.map_interaction_controller.reset_mock()

        items[2].callback()
        window.map_interaction_controller.add_route_node_from_context_menu.assert_called_once_with(
            12,
            34,
            NODE_TYPE_VIRTUAL,
            route_ids=["route-1"],
            show_dialog=False,
        )
        window.map_interaction_controller.reset_mock()

        items[3].callback()
        window.map_interaction_controller.add_annotated_point_to_routes.assert_called_once_with(
            12,
            34,
            route_ids=["route-1"],
            show_dialog=False,
        )

    def test_current_position_add_menu_does_not_insert_until_action_is_selected(self) -> None:
        window = _FakeWindow("")
        window._last_player_xy = (12, 34)
        window.map_interaction_controller = Mock()
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.show_context_menu"):
            controller.show_current_position_add_menu("route-1", QPushButton())

        window.map_interaction_controller.add_route_node_from_context_menu.assert_not_called()
        window.map_interaction_controller.add_annotated_point_to_routes.assert_not_called()
        window.map_interaction_controller.add_point_to_routes.assert_not_called()

    def test_current_position_add_action_requires_valid_player_position(self) -> None:
        window = _FakeWindow("")
        window._last_player_xy = None
        window.map_interaction_controller = Mock()
        controller = self._controller_for(window)

        with patch("ui_island.controllers.route_panel_controller.styled_info") as info:
            controller.add_current_position_to_route("route-1", NODE_TYPE_COLLECT)

        info.assert_called_once()
        window.map_interaction_controller.add_route_node_from_context_menu.assert_not_called()
        window.map_interaction_controller.add_annotated_point_to_routes.assert_not_called()
        window.map_interaction_controller.add_point_to_routes.assert_not_called()


if __name__ == "__main__":
    unittest.main()

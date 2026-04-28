import unittest
from enum import Enum
from unittest.mock import patch

from ui_island.controllers.route_panel_controller import RoutePanelController
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

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip


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


class RoutePanelFilterTests(unittest.TestCase):
    def _controller_for(self, window: _FakeWindow) -> RoutePanelController:
        controller = RoutePanelController.__new__(RoutePanelController)
        controller.window = window
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


if __name__ == "__main__":
    unittest.main()

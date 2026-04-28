import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget

from ui_island.app import window_view
from ui_island.controllers.route_panel_controller import RoutePanelController
from ui_island.design import theme
from ui_island.widgets.factory import make_route_panel_icon_button, make_route_panel_line_edit
from ui_island.widgets.route_widgets import RouteListItem, RouteSection


class _FakeRoutePanelController:
    def __init__(self) -> None:
        self.add_category_built = False
        self.sections_rebuilt = False
        self.tracked_refreshed = False
        self.filter_applied = False

    def show_route_drawing_help(self) -> None:
        pass

    def toggle_tracked_routes_collapsed(self) -> None:
        pass

    def apply_route_filter(self) -> None:
        self.filter_applied = True

    def reload_route_list(self) -> None:
        pass

    def show_add_category_row(self) -> None:
        pass

    def build_add_category_row(self) -> None:
        self.add_category_built = True

    def rebuild_route_sections(self) -> None:
        self.sections_rebuilt = True

    def refresh_tracked_routes(self) -> None:
        self.tracked_refreshed = True


class _FakeMapView(QWidget):
    relocate_requested = Signal(int, int)
    manual_view_changed = Signal()

    def __init__(self, _route_mgr=None) -> None:
        super().__init__()
        self.center_locked = False

    def set_map(self, _image) -> None:
        pass

    def set_center_locked(self, locked: bool) -> None:
        self.center_locked = bool(locked)


class _FakeWindowModeController:
    def __init__(self) -> None:
        self.sidebar_applied = False

    def toggle_maximize_restore(self) -> None:
        pass

    def handle_sidebar_action(self) -> None:
        pass

    def apply_sidebar_state(self) -> None:
        self.sidebar_applied = True


class _FakeTrackingController:
    def pause_navigation(self) -> None:
        pass


class _FakeTracker:
    logic_map_bgr = object()


class _FakeWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._shadow_enabled = False
        self._window_margin = 0
        self.tracker = _FakeTracker()
        self.route_mgr = object()
        self.route_panel_controller = _FakeRoutePanelController()
        self.window_mode_controller = _FakeWindowModeController()
        self.tracking_controller = _FakeTrackingController()

    def _update_header_button_labels(self) -> None:
        pass

    def _open_settings(self) -> None:
        pass

    def _collapse_to_icon(self) -> None:
        pass

    def _prompt_relocate(self) -> None:
        pass

    def _reset_map_view(self) -> None:
        pass

    def toggle_lock(self) -> None:
        pass

    def _on_relocate(self, _x: int, _y: int) -> None:
        pass

    def _handle_manual_map_navigation(self) -> None:
        pass

    def _update_window_controls(self) -> None:
        pass


class RoutePanelCompactWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def assert_route_panel_input(self, editor) -> None:
        self.assertEqual(editor.property("routePanelInput"), "true")
        self.assertEqual(editor.minimumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(editor.maximumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)

    def assert_route_panel_icon_button(self, button) -> None:
        self.assertEqual(button.property("routePanelIconButton"), "true")
        self.assertEqual(button.minimumWidth(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(button.maximumWidth(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(button.minimumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(button.maximumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)

    def test_factory_creates_compact_route_panel_input(self) -> None:
        editor = make_route_panel_line_edit(placeholder="Search")

        self.assert_route_panel_input(editor)
        self.assertEqual(editor.placeholderText(), "Search")

    def test_factory_creates_compact_route_panel_icon_button(self) -> None:
        button = make_route_panel_icon_button("✓", role="confirm", tooltip="Confirm")

        self.assert_route_panel_icon_button(button)
        self.assertEqual(button.toolTip(), "Confirm")

    def test_route_section_add_route_input_is_compact(self) -> None:
        section = RouteSection("Resources")

        self.assert_route_panel_input(section.add_route_input)
        self.assert_route_panel_icon_button(section.add_route_confirm_btn)
        self.assert_route_panel_icon_button(section.add_route_cancel_btn)

    def test_route_rename_input_is_compact(self) -> None:
        item = RouteListItem("Resources", "route-1", "Route 1", False)

        self.assert_route_panel_input(item.rename_input)
        self.assert_route_panel_icon_button(item.rename_confirm_btn)
        self.assert_route_panel_icon_button(item.rename_cancel_btn)

    def test_add_category_input_is_compact(self) -> None:
        window = type("FakeControllerWindow", (), {})()
        controller = RoutePanelController.__new__(RoutePanelController)
        controller.window = window

        controller.build_add_category_row()

        self.assert_route_panel_input(window._add_category_input)
        self.assert_route_panel_icon_button(window._add_category_confirm_btn)
        self.assert_route_panel_icon_button(window._add_category_cancel_btn)

    def test_search_input_and_route_header_buttons_are_compact(self) -> None:
        window = _FakeWindow()

        with patch.object(window_view, "MapView", _FakeMapView), patch.object(window_view, "AnnotationPanel", QWidget):
            window_view.build_window_ui(window)

        self.assert_route_panel_input(window.search_input)
        self.assertEqual(window.refresh_routes_btn.property("routePanelHeaderButton"), "true")
        self.assertEqual(window.add_category_btn.property("routePanelHeaderButton"), "true")
        self.assertEqual(window.refresh_routes_btn.minimumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(window.refresh_routes_btn.maximumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(window.add_category_btn.minimumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)
        self.assertEqual(window.add_category_btn.maximumHeight(), theme.RECENT_ROUTE_ITEM_HEIGHT)


if __name__ == "__main__":
    unittest.main()

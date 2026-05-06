"""Route panel and route list orchestration."""

from __future__ import annotations

import os
import subprocess
import sys
import math
from copy import deepcopy

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QDoubleValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import config
from ..design import strings, theme
from ..dialogs import StyledDialogBase, center_dialog, toast
from ..dialogs.annotation_type_picker import open_annotation_type_picker
from ..dialogs.insert_point_dialog import open_insert_point_dialog
from ..dialogs.point_order_dialog import open_point_order_dialog
from ..dialogs.route_notes_dialog import RouteNodeEditorPanel, RouteNotesDialog, edit_route_notes, route_color_to_hex
from ..dialogs.settings_dialog import styled_confirm, styled_info
from ..dialogs.text_input_dialog import prompt_text_input
from ..services import resource_metadata
from ..services.route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL
from ..widgets import ElidedCheckBox, RouteListItem, RouteSection, TrackedRouteItem
from ..widgets.context_menu import ContextMenuItem, show_context_menu
from ..widgets.factory import make_route_panel_icon_button, make_route_panel_line_edit
from ..widgets.node_type_popup import normalize_node_type, show_node_type_popup


class RouteDrawingToolbarFrame(QFrame):
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(28, 28, 30, 236))
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.drawRoundedRect(rect, 8, 8)


class RouteCalibrationPanelFrame(QFrame):
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(28, 28, 30, 214))
        painter.setPen(QPen(QColor(255, 255, 255, 46), 1))
        painter.drawRoundedRect(rect, 10, 10)


class RoutePanelController:
    def __init__(self, window) -> None:
        self.window = window
        self.state = window.route_panel_state
        self._route_notes_session: dict | None = None

    @staticmethod
    def matches_route(route_name: str, term: str) -> bool:
        return not term or term in route_name.casefold()

    @staticmethod
    def route_checkbox_stylesheet(route_color: tuple[int, int, int]) -> str:
        b, g, r = [max(0, min(255, int(channel))) for channel in route_color]
        return f"""
QCheckBox::indicator:checked {{
    background: rgb({r}, {g}, {b});
    border: 1px solid rgb({r}, {g}, {b});
}}
QCheckBox::indicator:checked:hover {{
    background: rgb({r}, {g}, {b});
    border: 1px solid rgb({r}, {g}, {b});
}}
"""

    def apply_route_checkbox_color(self, checkbox: QCheckBox, route_id: str) -> None:
        if not route_id:
            return
        checkbox.setStyleSheet(self.route_checkbox_stylesheet(self.window.route_mgr.color_for(route_id)))

    def refresh_route_checkbox_colors(self) -> None:
        for route_id, checkboxes in list(self.window._route_checkboxes.items()):
            if not route_id:
                continue
            for checkbox in list(checkboxes):
                self.apply_route_checkbox_color(checkbox, route_id)

    def resolve_route_section_expanded(self, category: str) -> bool:
        return bool(self.window._route_section_expanded.get(category, False))

    def remember_route_section_states_from_widgets(self) -> None:
        for category, section in self.window._route_sections.items():
            self.window._route_section_expanded[category] = section.is_expanded()

    def save_route_section_expanded(self) -> None:
        self.remember_route_section_states_from_widgets()
        try:
            self.window.window_prefs_store.save_route_section_expanded(dict(self.window._route_section_expanded))
        except Exception as e:
            print(f"Save route section expanded state failed: {e}")

    def handle_route_section_toggled(self, category: str, expanded: bool) -> None:
        self.window._route_section_expanded[category] = bool(expanded)
        self.save_route_section_expanded()

    def build_add_category_row(self) -> None:
        add_category_row = QFrame()
        add_category_row.setObjectName("PanelCard")
        add_category_row.hide()

        row_layout = QHBoxLayout(add_category_row)
        row_layout.setContentsMargins(8, 8, 8, 8)
        row_layout.setSpacing(6)

        add_category_input = make_route_panel_line_edit(placeholder=strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        add_category_input.returnPressed.connect(self.confirm_add_category)
        add_category_input.editingFinished.connect(self.queue_cancel_add_category_if_needed)
        row_layout.addWidget(add_category_input, stretch=1)

        add_category_confirm_btn = make_route_panel_icon_button(
            "✓",
            role="confirm",
            tooltip=strings.ROUTE_ADD_CATEGORY_CONFIRM,
        )
        add_category_confirm_btn.clicked.connect(self.confirm_add_category)
        row_layout.addWidget(add_category_confirm_btn)

        add_category_cancel_btn = make_route_panel_icon_button(
            "×",
            role="close",
            tooltip=strings.ROUTE_ADD_CATEGORY_CANCEL,
        )
        add_category_cancel_btn.clicked.connect(self.cancel_add_category)
        row_layout.addWidget(add_category_cancel_btn)

        self.window._add_category_row = add_category_row
        self.window._add_category_input = add_category_input
        self.window._add_category_confirm_btn = add_category_confirm_btn
        self.window._add_category_cancel_btn = add_category_cancel_btn

    def build_route_sections(self) -> None:
        for category in self.window.route_mgr.categories:
            section = RouteSection(category)
            section.set_expanded(self.resolve_route_section_expanded(category))
            self.window._route_sections[category] = section
            self.window._route_widgets_by_category[category] = []
            section.header.toggled.connect(
                lambda expanded, cat=category: self.handle_route_section_toggled(cat, expanded)
            )
            section.context_menu_requested.connect(
                lambda global_pos, cat=category: self.show_category_context_menu(cat, global_pos)
            )

            section.select_all_btn.clicked.connect(
                lambda _checked=False, cat=category: self.set_category_routes_visibility(cat, "select_all")
            )
            section.invert_select_btn.clicked.connect(
                lambda _checked=False, cat=category: self.set_category_routes_visibility(cat, "invert")
            )
            section.add_route_btn.clicked.connect(
                lambda _checked=False, cat=category: self.show_add_route_row(cat)
            )
            section.add_route_confirm_btn.clicked.connect(
                lambda _checked=False, cat=category: self.confirm_add_route(cat)
            )
            section.add_route_cancel_btn.clicked.connect(
                lambda _checked=False, cat=category: self.cancel_add_route(cat)
            )
            section.add_route_input.returnPressed.connect(
                lambda cat=category: self.confirm_add_route(cat)
            )

            routes = sorted(
                self.window.route_mgr.route_groups[category],
                key=lambda route: route.get("display_name", ""),
            )
            for route in routes:
                route_id = self.window.route_mgr.route_id(route)
                name = route.get("display_name", "")
                route_item = self.create_route_list_item(category, route)
                section.add_widget(route_item)
                self.window._route_widgets_by_category[category].append((route_id, name, route_item))

            self.window.routes_layout.addWidget(section)

    def clear_route_sections(self) -> None:
        for route_widgets in self.window._route_widgets_by_category.values():
            for route_id, _name, route_item in route_widgets:
                self.unregister_route_checkbox(route_id, route_item.checkbox)

        while self.window.routes_layout.count():
            item = self.window.routes_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if widget is self.window._add_category_row:
                    widget.hide()
                    continue
                if widget is self.window._active_route_rename_item:
                    self.window._active_route_rename_item = None
                widget.deleteLater()

        self.window._route_sections.clear()
        self.window._route_widgets_by_category.clear()

    def rebuild_route_sections(self) -> None:
        self.remember_route_section_states_from_widgets()
        self.clear_route_sections()
        if self.window._add_category_row is not None:
            self.window.routes_layout.addWidget(self.window._add_category_row)
        self.build_route_sections()
        self.window.routes_layout.addStretch()
        self.window.routes_scroll_inner.adjustSize()
        self.window.interaction_controller.install_resize_filters(self.window.routes_scroll_inner)

    def reload_route_list(self, _checked: bool = False) -> None:
        if not self.confirm_exit_route_drawing():
            return
        self.remember_route_section_states_from_widgets()
        self.cancel_active_route_rename()
        self.window.route_mgr.reload()
        self.window._route_section_expanded = {
            category: expanded
            for category, expanded in self.window._route_section_expanded.items()
            if category in self.window.route_mgr.categories
        }
        self.rebuild_route_sections()
        self.refresh_tracked_routes()
        self.apply_route_filter()
        self.window.map_view._refresh_from_last_frame()
        notice = getattr(self.window, "_show_resource_notice", None)
        if callable(notice):
            notice()
        self.window.window_mode_controller.schedule_layout_refresh()

    def create_route_list_item(self, category: str, route: dict) -> RouteListItem:
        route_id = self.window.route_mgr.route_id(route)
        name = route.get("display_name", "")
        route_item = RouteListItem(category, route_id, name, self.window.route_mgr.visibility.get(route_id, False))
        self.apply_route_checkbox_color(route_item.checkbox, route_id)
        route_item.checkbox.toggled.connect(
            lambda enabled, known_route_id=route_id, source=route_item.checkbox: self.toggle_route(known_route_id, enabled, source)
        )
        route_item.rename_confirm_btn.clicked.connect(lambda: self.confirm_route_rename(route_item))
        route_item.rename_cancel_btn.clicked.connect(self.cancel_active_route_rename)
        route_item.rename_input.returnPressed.connect(lambda: self.confirm_route_rename(route_item))
        route_item.context_menu_requested.connect(
            lambda global_pos, item=route_item: self.show_route_context_menu(item, global_pos)
        )
        self.window._route_checkboxes.setdefault(route_id, []).append(route_item.checkbox)
        return route_item

    def show_route_context_menu(self, route_item: RouteListItem, global_pos) -> None:
        show_context_menu(
            self.window,
            global_pos,
            [
                ContextMenuItem(strings.ROUTE_RENAME, lambda: self.begin_route_rename(route_item)),
                ContextMenuItem(
                    strings.ROUTE_NOTES,
                    lambda: self.show_route_notes_dialog(route_item.category, route_item.route_name),
                ),
                ContextMenuItem(strings.ROUTE_DRAWING_MENU_LABEL, lambda: self.begin_route_drawing(route_item)),
                ContextMenuItem(
                    strings.ROUTE_CALIBRATION_MENU_LABEL,
                    lambda: self.begin_route_calibration(route_item),
                ),
                ContextMenuItem(
                    strings.ROUTE_DELETE,
                    lambda: self.delete_route(route_item.category, route_item.route_name),
                ),
                ContextMenuItem.separator_item(),
                ContextMenuItem(
                    strings.ROUTE_OPEN_FILE_LOCATION,
                    lambda: self.open_route_file_location(route_item.category, route_item.route_name),
                ),
            ],
            object_name="RouteListContextMenu",
        )

    def show_category_context_menu(self, category: str, global_pos) -> None:
        show_context_menu(
            self.window,
            global_pos,
            [
                ContextMenuItem(strings.ROUTE_CATEGORY_RENAME, lambda: self.rename_category(category)),
                ContextMenuItem(strings.ROUTE_CATEGORY_DELETE, lambda: self.delete_category(category)),
                ContextMenuItem(
                    strings.ROUTE_CATEGORY_MARK_COMPATIBLE,
                    lambda: self.mark_category_routes_compatible(category),
                ),
                ContextMenuItem(
                    strings.ROUTE_BATCH_CALIBRATION_MENU_LABEL,
                    lambda: self.begin_batch_route_calibration(category),
                ),
                ContextMenuItem.separator_item(),
                ContextMenuItem(
                    strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION,
                    lambda: self.open_category_file_location(category),
                ),
            ],
            object_name="RouteListContextMenu",
        )

    def _drawing_allowed_modes(self) -> tuple[object, object]:
        mode_enum = self.window._mode.__class__
        return mode_enum.PAUSED, mode_enum.MAXIMIZED

    def begin_route_calibration(self, route_item: RouteListItem) -> None:
        if self.window._mode not in self._drawing_allowed_modes():
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_CALIBRATION_MODE_REQUIRED)
            return
        if not self.confirm_exit_route_drawing():
            return
        if not self.confirm_exit_route_calibration():
            return

        route = self.window.route_mgr.route_for_id(route_item.route_id)
        if route is None:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_CALIBRATION_ROUTE_MISSING)
            return

        transform = self._effective_route_coord_transform(route_item.route_id)
        self.window.route_calibration_state.begin(
            route_id=route_item.route_id,
            category=route_item.category,
            name=route_item.route_name,
            coord_transform=transform,
            route_center=self._route_internal_center(route),
        )
        self._sync_route_calibration_ui()
        toast(self.window, strings.ROUTE_CALIBRATION_ENTERED_FMT.format(name=route_item.route_name))

    def begin_batch_route_calibration(self, category: str) -> None:
        if self.window._mode not in self._drawing_allowed_modes():
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_CALIBRATION_MODE_REQUIRED)
            return
        if not self.confirm_exit_route_drawing():
            return
        if not self.confirm_exit_route_calibration():
            return

        routes = self.window.route_mgr.route_groups.get(category, [])
        if not routes:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_BATCH_CALIBRATION_EMPTY_CATEGORY)
            return

        batch_route_ids: list[str] = []
        for route in routes:
            route_id = self.window.route_mgr.route_id(route)
            if route_id:
                batch_route_ids.append(route_id)

        if not batch_route_ids:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_BATCH_CALIBRATION_EMPTY_CATEGORY)
            return

        first_route = self.window.route_mgr.route_for_id(batch_route_ids[0])
        if first_route is None:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_CALIBRATION_ROUTE_MISSING)
            return

        transform = self._effective_route_coord_transform(batch_route_ids[0])
        self.window.route_calibration_state.begin(
            route_id=batch_route_ids[0],
            category=category,
            name=category,
            coord_transform=transform,
            route_center=self._route_internal_center(first_route),
            batch=True,
            batch_route_ids=batch_route_ids,
        )
        self._sync_route_calibration_ui()
        toast(self.window, strings.ROUTE_BATCH_CALIBRATION_ENTERED_FMT.format(name=category))

    def begin_annotation_calibration(
        self,
        annotation_path: str,
        initial_transform: dict | None,
        *,
        settings_dialog: object | None = None,
    ) -> bool:
        if self.window._mode not in self._drawing_allowed_modes():
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, strings.ROUTE_CALIBRATION_MODE_REQUIRED)
            return False
        if not self.confirm_exit_route_drawing():
            return False
        if not self.confirm_exit_route_calibration():
            return False

        path = os.fspath(annotation_path or "")
        if not path or not os.path.isfile(path):
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, "未能找到当前标注文件，请重新选择后再校准。")
            return False

        enabled_type_ids = []
        type_getter = getattr(self.window.route_mgr, "annotation_type_ids", None)
        if callable(type_getter):
            enabled_type_ids = [str(type_id) for type_id in type_getter() if str(type_id or "")]
        if not enabled_type_ids:
            enabled_type_ids = [str(type_id) for type_id in getattr(self.window, "annotation_type_ids", []) if str(type_id or "")]
        if not enabled_type_ids:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, "请先启用至少一种标注类型，再进行手动校准。")
            return False

        payload = resource_metadata.read_json_payload(path)
        points_by_type = payload.get("pointsByType") if isinstance(payload, dict) else None
        if not isinstance(points_by_type, dict):
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, "当前标注文件格式无法读取，请检查标注 JSON。")
            return False

        calibration_points: list[dict] = []
        for type_id in enabled_type_ids:
            points = points_by_type.get(type_id)
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                copied = dict(point)
                copied["typeId"] = type_id
                calibration_points.append(copied)
        if not calibration_points:
            styled_info(self.window, strings.ROUTE_CALIBRATION_TITLE, "当前启用的标注类型没有可校准的点位。")
            return False

        name = f"标注数据：{os.path.basename(path)}"
        self.window.route_calibration_state.begin(
            route_id="",
            category="",
            name=name,
            coord_transform=initial_transform,
            route_center=self._route_internal_center({"points": calibration_points}),
            target_type="annotation",
            annotation_path=path,
            annotation_points=calibration_points,
            annotation_type_ids=enabled_type_ids,
        )
        self.window.route_calibration_settings_dialog = settings_dialog
        self._sync_route_calibration_ui()
        toast(self.window, strings.ROUTE_CALIBRATION_ENTERED_FMT.format(name=name))
        return True

    def _effective_route_coord_transform(self, route_id: str) -> dict:
        adapter = None
        adapter_getter = getattr(self.window.route_mgr, "route_coordinate_adapter", None)
        if callable(adapter_getter):
            fallback = None
            coordinate_adapter = getattr(self.window.map_view, "coordinate_adapter", None)
            if callable(coordinate_adapter):
                fallback = coordinate_adapter()
            adapter = adapter_getter(route_id, fallback)
        if adapter is None:
            coord_getter = getattr(self.window.route_mgr, "route_coord_transform", None)
            transform = coord_getter(route_id) if callable(coord_getter) else None
            if isinstance(transform, dict):
                return self._normalized_calibration_transform(transform)
            coordinate_adapter = getattr(self.window.map_view, "coordinate_adapter", None)
            adapter = coordinate_adapter() if callable(coordinate_adapter) else None
        to_dict = getattr(adapter, "to_dict", None)
        if callable(to_dict):
            return self._normalized_calibration_transform(to_dict())
        return self._normalized_calibration_transform(None)

    def _route_coordinate_adapter(self, route_id: str):
        adapter_getter = getattr(self.window.route_mgr, "route_coordinate_adapter", None)
        if callable(adapter_getter):
            coordinate_adapter = getattr(self.window.map_view, "coordinate_adapter", None)
            fallback = coordinate_adapter() if callable(coordinate_adapter) else None
            return adapter_getter(route_id, fallback)
        coordinate_adapter = getattr(self.window.map_view, "coordinate_adapter", None)
        return coordinate_adapter() if callable(coordinate_adapter) else None

    @staticmethod
    def _normalized_calibration_transform(transform: object) -> dict:
        defaults = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        result = dict(defaults)
        if isinstance(transform, dict):
            for key, default in defaults.items():
                try:
                    result[key] = float(transform.get(key, default))
                except (TypeError, ValueError):
                    result[key] = default
        return result

    @staticmethod
    def _route_internal_center(route: dict) -> tuple[float, float] | None:
        points = route.get("points") if isinstance(route, dict) else None
        if not isinstance(points, list):
            return None
        xs: list[float] = []
        ys: list[float] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            try:
                xs.append(float(point["x"]))
                ys.append(float(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
        if not xs or not ys:
            return None
        return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

    def begin_route_drawing(self, route_item: RouteListItem) -> None:
        if self.window._mode not in self._drawing_allowed_modes():
            styled_info(self.window, strings.ROUTE_DRAWING_TITLE, strings.ROUTE_DRAWING_MODE_REQUIRED)
            return
        if not self.confirm_exit_route_drawing():
            return
        if not self.confirm_exit_route_calibration():
            return

        route = self.window.route_mgr.route_for_id(route_item.route_id)
        if route is None:
            styled_info(self.window, strings.ROUTE_DRAWING_TITLE, strings.ROUTE_DRAWING_ROUTE_MISSING)
            return

        points = [
            self._normalize_drawing_point(point)
            for point in route.get("points", []) or []
            if isinstance(point, dict)
        ]
        self.window.route_drawing_state.begin(
            route_id=route_item.route_id,
            category=route_item.category,
            name=route_item.route_name,
            points=points,
            loop=bool(route.get("loop", False)),
        )
        self._sync_route_drawing_ui()
        toast(self.window, strings.ROUTE_DRAWING_ENTERED_FMT.format(name=route_item.route_name))

    @staticmethod
    def _normalize_drawing_point(point: dict) -> dict:
        copied = dict(point)
        copied["node_type"] = str(copied.get("node_type") or "collect").strip() or "collect"
        copied["visited"] = False
        return copied

    @staticmethod
    def _strip_drawing_fields(point: dict) -> dict:
        return {key: value for key, value in point.items() if key != "visited" and not str(key).startswith("_drawing_")}

    def _clean_draft_points(self) -> list[dict]:
        return [self._strip_drawing_fields(point) for point in self.window.route_drawing_state.draft_points]

    def _drawing_points_equal_original(self) -> bool:
        state = self.window.route_drawing_state
        original = [self._strip_drawing_fields(point) for point in state.original_points]
        current = [self._strip_drawing_fields(point) for point in state.draft_points]
        return original == current and bool(state.loop) == bool(state.original_loop)

    def _mark_drawing_dirty(self) -> None:
        self.window.route_drawing_state.dirty = not self._drawing_points_equal_original()

    def _sync_route_drawing_ui(self) -> None:
        state = self.window.route_drawing_state
        context = None
        if state.active:
            self._ensure_route_drawing_toolbar()
            context = {
                "active": True,
                "paused": state.paused,
                "route_id": state.route_id,
                "name": state.name,
                "points": deepcopy(state.draft_points),
                "node_type": state.node_type,
                "insert_at_end": state.insert_at_end,
                "add_node_annotation": state.add_node_annotation,
                "same_annotation_type": state.same_annotation_type,
                "annotation_type": state.annotation_type,
                "annotation_type_id": state.annotation_type_id,
                "hide_other_routes": state.hide_other_routes,
                "loop": state.loop,
            }
            self.window.state_hint_label.setVisible(True)
            self.window.state_hint_label.setText(strings.ROUTE_DRAWING_STATE_FMT.format(name=state.name))
            self.window.state_hint_label.setStyleSheet("")
            self._update_route_drawing_toolbar()
            help_btn = getattr(self.window, "route_drawing_help_btn", None)
            if help_btn is not None:
                help_btn.setVisible(True)
        else:
            toolbar = getattr(self.window, "route_drawing_toolbar", None)
            if toolbar is not None:
                toolbar.hide()
            node_panel = getattr(self.window, "route_drawing_node_panel", None)
            if node_panel is not None:
                node_panel.set_nodes([])
            help_btn = getattr(self.window, "route_drawing_help_btn", None)
            if help_btn is not None:
                help_btn.hide()
        self.window.map_view.set_route_drawing_context(context)

    def _ensure_route_drawing_toolbar(self) -> None:
        if getattr(self.window, "route_drawing_toolbar", None) is not None:
            return

        toolbar = RouteDrawingToolbarFrame(
            self.window,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        toolbar.setObjectName("RouteDrawingToolbar")
        toolbar.setWindowTitle(strings.ROUTE_DRAWING_TOOLBAR_TITLE)
        toolbar.setAttribute(Qt.WA_ShowWithoutActivating, True)
        toolbar.setAttribute(Qt.WA_TranslucentBackground, True)
        toolbar.setAttribute(Qt.WA_StyledBackground, True)
        toolbar.setStyleSheet(theme.ISLAND_QSS)
        toolbar.hide()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        node_panel = RouteNodeEditorPanel(
            toolbar,
            route_color_hex="#1ad1ff",
            annotation_items_provider=self.window.route_mgr.annotation_type_items,
            annotation_icon_path_provider=self.window.route_mgr.point_icon_path_for,
            include_coord_editors=True,
            annotation_picker_placement="right_of",
            annotation_picker_anchor=toolbar,
        )
        node_panel.setObjectName("RouteDrawingNodeEditorPanel")
        node_panel.setMinimumWidth(300)
        node_panel.setMaximumWidth(380)
        node_panel.node_order_changed.connect(self.reorder_drawing_point)
        node_panel.node_annotation_changed.connect(self._on_drawing_node_panel_annotation_changed)
        node_panel.node_label_changed.connect(self._on_drawing_node_panel_label_changed)
        node_panel.node_label_edit_committed.connect(self._on_drawing_node_panel_label_committed)
        node_panel.node_coord_changed.connect(self._on_drawing_node_panel_coord_changed)
        node_panel.node_coord_edit_committed.connect(self._on_drawing_node_panel_coord_committed)
        layout.addWidget(node_panel, stretch=1)

        controls = QWidget(toolbar)
        controls.setObjectName("RouteDrawingToolbarControls")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        layout.addWidget(controls)

        end_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_END)
        save_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_SAVE)
        pause_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_PAUSE)
        undo_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_UNDO)
        clear_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_CLEAR)
        hide_routes_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_HIDE_OTHER_ROUTES, checkable=True)
        end_btn.clicked.connect(self.end_route_drawing)
        save_btn.clicked.connect(self.save_route_drawing)
        pause_btn.clicked.connect(self.toggle_route_drawing_paused)
        undo_btn.clicked.connect(self.undo_route_drawing)
        clear_btn.clicked.connect(self.clear_route_drawing)
        hide_routes_btn.clicked.connect(
            lambda checked=False: self.set_route_drawing_hide_other_routes(bool(checked))
        )
        for button in (end_btn, save_btn, pause_btn, undo_btn, clear_btn, hide_routes_btn):
            controls_layout.addWidget(button)

        controls_layout.addWidget(self._drawing_toolbar_separator())

        type_group = QButtonGroup(toolbar)
        type_group.setExclusive(True)
        collect_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_NODE_COLLECT, checkable=True)
        teleport_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_NODE_TELEPORT, checkable=True)
        virtual_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_NODE_VIRTUAL, checkable=True)
        for node_type, button in (
            ("collect", collect_btn),
            ("teleport", teleport_btn),
            ("virtual", virtual_btn),
        ):
            type_group.addButton(button)
            button.clicked.connect(lambda _checked=False, value=node_type: self.set_route_drawing_node_type(value))
            controls_layout.addWidget(button)

        controls_layout.addWidget(self._drawing_toolbar_separator())

        insert_at_end_check = QCheckBox(strings.ROUTE_DRAWING_INSERT_AT_END)
        insert_at_end_check.toggled.connect(self.set_route_drawing_insert_at_end)
        controls_layout.addWidget(insert_at_end_check)

        loop_check = QCheckBox(strings.ROUTE_DRAWING_LOOP)
        loop_check.toggled.connect(self.set_route_drawing_loop)
        controls_layout.addWidget(loop_check)

        add_annotation_check = QCheckBox(strings.ROUTE_DRAWING_ADD_ANNOTATION)
        add_annotation_check.toggled.connect(self.set_route_drawing_add_annotation)
        controls_layout.addWidget(add_annotation_check)

        same_annotation_check = QCheckBox(strings.ROUTE_DRAWING_SAME_ANNOTATION_TYPE)
        same_annotation_check.toggled.connect(self.set_route_drawing_same_annotation)
        controls_layout.addWidget(same_annotation_check)

        select_annotation_btn = self._drawing_toolbar_button(strings.ROUTE_DRAWING_SELECT_ANNOTATION_TYPE)
        select_annotation_btn.clicked.connect(self.select_route_drawing_annotation_type)
        controls_layout.addWidget(select_annotation_btn)

        self.window.route_drawing_toolbar = toolbar
        self.window.route_drawing_node_panel = node_panel
        self.window.route_drawing_toolbar_buttons = {
            "end": end_btn,
            "save": save_btn,
            "pause": pause_btn,
            "undo": undo_btn,
            "clear": clear_btn,
            "hide_other_routes": hide_routes_btn,
            "collect": collect_btn,
            "teleport": teleport_btn,
            "virtual": virtual_btn,
            "insert_at_end": insert_at_end_check,
            "loop": loop_check,
            "add_annotation": add_annotation_check,
            "same_annotation": same_annotation_check,
            "select_annotation": select_annotation_btn,
        }

    @staticmethod
    def _drawing_toolbar_button(text: str, *, checkable: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(checkable)
        button.setMinimumWidth(96)
        return button

    @staticmethod
    def _drawing_toolbar_separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("RouteDrawingToolbarSeparator")
        separator.setFrameShape(QFrame.HLine)
        return separator

    def _update_route_drawing_toolbar(self) -> None:
        state = self.window.route_drawing_state
        toolbar = getattr(self.window, "route_drawing_toolbar", None)
        buttons = getattr(self.window, "route_drawing_toolbar_buttons", {})
        if toolbar is None or not buttons:
            return
        node_panel = getattr(self.window, "route_drawing_node_panel", None)
        if node_panel is not None:
            try:
                node_panel.set_route_color_hex(route_color_to_hex(self.window.route_mgr.color_for(state.route_id)))
            except Exception:
                pass
            focus = QApplication.focusWidget()
            editing_in_panel = focus is not None and node_panel.isAncestorOf(focus)
            if not editing_in_panel:
                node_panel.set_nodes(state.draft_points)

        buttons["pause"].setText(strings.ROUTE_DRAWING_RESUME if state.paused else strings.ROUTE_DRAWING_PAUSE)
        node_button = buttons.get(state.node_type) or buttons["collect"]
        node_button.setChecked(True)

        add_annotation = bool(state.add_node_annotation)
        same_annotation = bool(state.same_annotation_type)
        buttons["add_annotation"].blockSignals(True)
        buttons["add_annotation"].setChecked(add_annotation)
        buttons["add_annotation"].blockSignals(False)
        buttons["same_annotation"].blockSignals(True)
        buttons["same_annotation"].setChecked(same_annotation)
        buttons["same_annotation"].blockSignals(False)
        hide_routes_btn = buttons.get("hide_other_routes")
        if hide_routes_btn is not None:
            hide_routes_btn.blockSignals(True)
            hide_routes_btn.setChecked(bool(state.hide_other_routes))
            hide_routes_btn.blockSignals(False)
        insert_at_end_check = buttons.get("insert_at_end")
        if insert_at_end_check is not None:
            insert_at_end_check.blockSignals(True)
            insert_at_end_check.setChecked(bool(state.insert_at_end))
            insert_at_end_check.blockSignals(False)
        loop_check = buttons.get("loop")
        if loop_check is not None:
            loop_check.blockSignals(True)
            loop_check.setChecked(bool(state.loop))
            loop_check.blockSignals(False)
        buttons["same_annotation"].setVisible(add_annotation)
        buttons["select_annotation"].setVisible(add_annotation and same_annotation)
        buttons["select_annotation"].setText(state.annotation_type or strings.ROUTE_DRAWING_SELECT_ANNOTATION_TYPE)
        self.position_route_drawing_toolbar()
        toolbar.show()
        toolbar.raise_()

    def position_route_drawing_toolbar(self) -> None:
        state = getattr(self.window, "route_drawing_state", None)
        toolbar = getattr(self.window, "route_drawing_toolbar", None)
        if state is None or toolbar is None or not state.active:
            return

        toolbar.adjustSize()
        margin = 12
        if self.window.isMaximized():
            anchor = self.window.map_view.mapToGlobal(QPoint(margin, 0))
            center = self.window.map_view.mapToGlobal(
                QPoint(0, max(margin, (self.window.map_view.height() - toolbar.height()) // 2))
            )
            x = anchor.x()
            y = center.y()
        else:
            body = getattr(self.window, "body_container", None)
            window_frame = self.window.frameGeometry()
            x = window_frame.left() - toolbar.width()
            if body is None:
                y = window_frame.top() + max(margin, (window_frame.height() - toolbar.height()) // 2)
            else:
                body_top = body.mapToGlobal(QPoint(0, 0)).y()
                y = body_top + max(margin, (body.height() - toolbar.height()) // 2)

        screen = toolbar.screen() or self.window.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            min_x = available.left()
            min_y = available.top() + margin
            max_x = available.right() - toolbar.width() + 1
            max_y = available.bottom() - toolbar.height() - margin + 1
            x = max(min_x, min(x, max(min_x, max_x)))
            y = max(min_y, min(y, max(min_y, max_y)))
        toolbar.move(x, y)
        toolbar.raise_()

    def end_route_drawing(self) -> None:
        self.confirm_exit_route_drawing()

    def save_route_drawing(self) -> bool:
        state = self.window.route_drawing_state
        if not state.active:
            return True
        if not self.window.route_mgr.save_route_points(state.route_id, self._clean_draft_points(), loop=state.loop):
            styled_info(self.window, strings.ROUTE_DRAWING_SAVE_FAILED_TITLE, strings.ROUTE_DRAWING_SAVE_FAILED_BODY)
            return False
        drawing_options = {
            "paused": state.paused,
            "node_type": state.node_type,
            "add_node_annotation": state.add_node_annotation,
            "same_annotation_type": state.same_annotation_type,
            "annotation_type": state.annotation_type,
            "annotation_type_id": state.annotation_type_id,
            "hide_other_routes": state.hide_other_routes,
            "insert_at_end": state.insert_at_end,
            "loop": state.loop,
        }
        route = self.window.route_mgr.route_for_id(state.route_id)
        saved_points = route.get("points", []) if route is not None else self._clean_draft_points()
        saved_loop = bool(route.get("loop", state.loop)) if route is not None else bool(state.loop)
        state.begin(
            route_id=state.route_id,
            category=state.category,
            name=state.name,
            points=saved_points,
            loop=saved_loop,
        )
        for key, value in drawing_options.items():
            setattr(state, key, value)
        self._sync_route_drawing_ui()
        try:
            self.window.map_view._refresh_from_last_frame()
            self.refresh_tracked_routes()
        except Exception:
            pass
        toast(self.window, strings.ROUTE_DRAWING_SAVED_FMT.format(name=state.name))
        return True

    def discard_route_drawing(self) -> None:
        self.window.route_drawing_state.reset()
        self._sync_route_drawing_ui()

    def confirm_exit_route_drawing(self) -> bool:
        state = getattr(self.window, "route_drawing_state", None)
        if state is None or not state.active:
            return self.confirm_exit_route_calibration()
        self._mark_drawing_dirty()
        if not state.dirty:
            self.discard_route_drawing()
            return self.confirm_exit_route_calibration()

        choice = self._prompt_save_discard_cancel()
        if choice == "cancel":
            return False
        if choice == "save" and not self.save_route_drawing():
            return False
        self.discard_route_drawing()
        return self.confirm_exit_route_calibration()

    def _sync_route_calibration_ui(self, *, update_editors: bool = True) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        context = None
        if state is not None and state.active:
            self._ensure_route_calibration_controls()
            if getattr(state, "target_type", "route") == "annotation":
                context = {
                    "active": True,
                    "target_type": "annotation",
                    "annotation_path": state.annotation_path,
                    "annotation_points": deepcopy(state.annotation_points),
                    "annotation_type_ids": list(state.annotation_type_ids),
                    "name": state.name,
                    "coord_transform": dict(state.current_transform),
                }
            else:
                route = self.window.route_mgr.route_for_id(state.route_id)
                context = {
                    "active": True,
                    "target_type": "route",
                    "route_id": state.route_id,
                    "route": deepcopy(route) if isinstance(route, dict) else None,
                    "coord_transform": dict(state.current_transform),
                }
            hint = getattr(self.window, "state_hint_label", None)
            if hint is not None:
                hint.setVisible(True)
                if getattr(state, "batch", False):
                    hint.setText(strings.ROUTE_BATCH_CALIBRATION_STATE_FMT.format(name=state.name))
                else:
                    hint.setText(strings.ROUTE_CALIBRATION_STATE_FMT.format(name=state.name))
                hint.setStyleSheet("")
            for panel_name in (
                "route_calibration_action_panel",
                "route_calibration_x_panel",
                "route_calibration_y_panel",
            ):
                panel = getattr(self.window, panel_name, None)
                if panel is not None:
                    panel.show()
                    panel.raise_()
            if update_editors:
                self._update_route_calibration_editors()
            self.position_route_calibration_controls()
        else:
            for panel_name in (
                "route_calibration_action_panel",
                "route_calibration_x_panel",
                "route_calibration_y_panel",
            ):
                panel = getattr(self.window, panel_name, None)
                if panel is not None:
                    panel.hide()

        set_context = getattr(self.window.map_view, "set_route_calibration_context", None)
        if callable(set_context):
            set_context(context)

    def _ensure_route_calibration_controls(self) -> None:
        if getattr(self.window, "route_calibration_action_panel", None) is not None:
            return
        map_view = getattr(self.window, "map_view", None)
        if not isinstance(map_view, QWidget):
            return

        action_panel = RouteCalibrationPanelFrame(map_view)
        action_panel.setObjectName("RouteCalibrationActionPanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(6)
        end_btn = self._calibration_button(strings.ROUTE_CALIBRATION_END)
        save_btn = self._calibration_button(strings.ROUTE_CALIBRATION_SAVE)
        end_btn.clicked.connect(self.end_route_calibration)
        save_btn.clicked.connect(self.save_route_calibration)
        action_layout.addWidget(end_btn)
        action_layout.addWidget(save_btn)

        x_panel = self._build_route_calibration_axis_panel(
            map_view,
            axis="x",
            offset_label=strings.ROUTE_CALIBRATION_X_OFFSET,
            scale_label=strings.ROUTE_CALIBRATION_X_SCALE,
        )
        y_panel = self._build_route_calibration_axis_panel(
            map_view,
            axis="y",
            offset_label=strings.ROUTE_CALIBRATION_Y_OFFSET,
            scale_label=strings.ROUTE_CALIBRATION_Y_SCALE,
        )

        self.window.route_calibration_action_panel = action_panel
        self.window.route_calibration_x_panel = x_panel
        self.window.route_calibration_y_panel = y_panel
        self.window.route_calibration_editors = {
            "offset_x": x_panel.findChild(QLineEdit, "RouteCalibration_offset_x"),
            "scale_x": x_panel.findChild(QLineEdit, "RouteCalibration_scale_x"),
            "offset_y": y_panel.findChild(QLineEdit, "RouteCalibration_offset_y"),
            "scale_y": y_panel.findChild(QLineEdit, "RouteCalibration_scale_y"),
        }

    def _build_route_calibration_axis_panel(
        self,
        parent: QWidget,
        *,
        axis: str,
        offset_label: str,
        scale_label: str,
    ) -> QFrame:
        panel = RouteCalibrationPanelFrame(parent)
        panel.setObjectName(f"RouteCalibration{axis.upper()}Panel")
        if axis == "y":
            self._populate_route_calibration_y_panel(panel, offset_label, scale_label)
            panel.hide()
            return panel
        layout = QGridLayout(panel)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)

        labels = (offset_label, scale_label)
        keys = (f"offset_{axis}", f"scale_{axis}")
        for column, (label_text, key) in enumerate(zip(labels, keys)):
            label = QLabel(label_text, panel)
            label.setObjectName("FieldLabel")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 0, column * 2, 1, 2)
            editor = QLineEdit(panel)
            editor.setObjectName(f"RouteCalibration_{key}")
            editor.setAlignment(Qt.AlignRight)
            editor.setFixedHeight(26)
            editor.setFixedWidth(70)
            editor.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            validator = QDoubleValidator(-1e9, 1e9, 4, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
            editor.textEdited.connect(lambda _text, known_key=key: self._on_route_calibration_editor_changed(known_key))
            editor.editingFinished.connect(lambda known_key=key: self._on_route_calibration_editor_changed(known_key))
            layout.addWidget(editor, 1, column * 2, 1, 2)

        controls = (
            (f"offset_{axis}", -1.0, "-"),
            (f"offset_{axis}", 1.0, "+"),
            (f"scale_{axis}", -0.01, "缩"),
            (f"scale_{axis}", 0.01, "放"),
        )
        for column, (key, delta, text) in enumerate(controls):
            button = self._calibration_button(text)
            button.setFixedWidth(34)
            button.setToolTip(self._calibration_adjust_tooltip(key, delta))
            button.clicked.connect(
                lambda _checked=False, known_key=key, known_delta=delta:
                self.adjust_route_calibration_value(known_key, known_delta)
            )
            layout.addWidget(button, 2, column)
        panel.hide()
        return panel

    def _populate_route_calibration_y_panel(
        self,
        panel: QFrame,
        offset_label: str,
        scale_label: str,
    ) -> None:
        layout = QGridLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)

        rows = (
            (offset_label, "offset_y", "-", "+", 1.0),
            (scale_label, "scale_y", "缩", "放", 0.01),
        )
        for row, (label_text, key, minus_text, plus_text, step) in enumerate(rows):
            label = QLabel("\n".join(label_text), panel)
            label.setObjectName("FieldLabel")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, row, 0)

            controls = QWidget(panel)
            controls_layout = QVBoxLayout(controls)
            controls_layout.setContentsMargins(0, 0, 0, 0)
            controls_layout.setSpacing(3)

            editor = QLineEdit(controls)
            editor.setObjectName(f"RouteCalibration_{key}")
            editor.setAlignment(Qt.AlignRight)
            editor.setFixedHeight(26)
            editor.setFixedWidth(70)
            editor.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            validator = QDoubleValidator(-1e9, 1e9, 4, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
            editor.textEdited.connect(lambda _text, known_key=key: self._on_route_calibration_editor_changed(known_key))
            editor.editingFinished.connect(lambda known_key=key: self._on_route_calibration_editor_changed(known_key))
            controls_layout.addWidget(editor)

            button_row = QWidget(controls)
            button_layout = QHBoxLayout(button_row)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(3)
            for delta, text in ((-step, minus_text), (step, plus_text)):
                button = self._calibration_button(text)
                button.setFixedWidth(34)
                button.setToolTip(self._calibration_adjust_tooltip(key, delta))
                button.clicked.connect(
                    lambda _checked=False, known_key=key, known_delta=delta:
                    self.adjust_route_calibration_value(known_key, known_delta)
                )
                button_layout.addWidget(button)
            controls_layout.addWidget(button_row)
            layout.addWidget(controls, row, 1)

    @staticmethod
    def _calibration_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("RouteCalibrationButton")
        button.setMinimumHeight(28)
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(350)
        button.setAutoRepeatInterval(45)
        return button

    @staticmethod
    def _calibration_adjust_tooltip(key: str, delta: float) -> str:
        direction = "增加" if delta > 0 else "减少"
        if key.startswith("offset_"):
            axis = "X" if key.endswith("_x") else "Y"
            return f"{direction}{axis}方向偏移"
        axis = "X" if key.endswith("_x") else "Y"
        return f"{direction}{axis}方向缩放"

    def position_route_calibration_controls(self) -> None:
        map_view = getattr(self.window, "map_view", None)
        if not isinstance(map_view, QWidget):
            return
        action_panel = getattr(self.window, "route_calibration_action_panel", None)
        x_panel = getattr(self.window, "route_calibration_x_panel", None)
        y_panel = getattr(self.window, "route_calibration_y_panel", None)
        margin = 2
        action_margin = 8
        if action_panel is not None:
            action_panel.adjustSize()
            action_panel.move(
                max(action_margin, map_view.width() - action_panel.width() - action_margin),
                action_margin,
            )
        if x_panel is not None:
            x_panel.adjustSize()
            x_panel.move(
                max(margin, (map_view.width() - x_panel.width()) // 2),
                max(margin, map_view.height() - x_panel.height() - margin),
            )
        if y_panel is not None:
            y_panel.adjustSize()
            y_panel.move(
                max(margin, map_view.width() - y_panel.width() - margin),
                max(margin, (map_view.height() - y_panel.height()) // 2),
            )

    def _update_route_calibration_editors(self) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        editors = getattr(self.window, "route_calibration_editors", {}) or {}
        if state is None or not state.active:
            return
        for key, editor in editors.items():
            if editor is None:
                continue
            editor.blockSignals(True)
            editor.setText(self._format_calibration_value(state.current_transform.get(key, 0.0)))
            editor.blockSignals(False)

    @staticmethod
    def _format_calibration_value(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        return f"{number:.2f}".rstrip("0").rstrip(".") or "0"

    def _on_route_calibration_editor_changed(self, key: str) -> None:
        editors = getattr(self.window, "route_calibration_editors", {}) or {}
        editor = editors.get(key)
        if editor is None:
            return
        text = editor.text().strip()
        if text in {"", "-", "+", ".", "-.", "+."}:
            return
        try:
            value = float(text)
        except ValueError:
            return
        self.set_route_calibration_value(key, value, update_editors=False)

    def adjust_route_calibration_value(self, key: str, delta: float) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active:
            return
        current = float(state.current_transform.get(key, 1.0 if key.startswith("scale_") else 0.0))
        self.set_route_calibration_value(key, current + float(delta))

    def set_route_calibration_value(self, key: str, value: float, *, update_editors: bool = True) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active or key not in {"offset_x", "offset_y", "scale_x", "scale_y"}:
            return
        transform = dict(state.current_transform)
        if key.startswith("scale_"):
            value = max(0.001, float(value))
            offset_key = "offset_x" if key.endswith("_x") else "offset_y"
            center_index = 0 if key.endswith("_x") else 1
            center = state.route_center[center_index] if state.route_center is not None else None
            old_scale = float(transform.get(key, 1.0))
            old_offset = float(transform.get(offset_key, 0.0))
            transform[key] = value
            if center is not None:
                current_center = center * old_scale + old_offset
                transform[offset_key] = current_center - center * value
        else:
            transform[key] = float(value)
        state.current_transform = self._normalized_calibration_transform(transform)
        self._mark_calibration_dirty()
        self._sync_route_calibration_ui(update_editors=update_editors)

    def apply_route_calibration_drag_delta(self, dx: float, dy: float) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active:
            return
        transform = dict(state.current_transform)
        transform["offset_x"] = float(transform.get("offset_x", 0.0)) + float(dx)
        transform["offset_y"] = float(transform.get("offset_y", 0.0)) + float(dy)
        state.current_transform = self._normalized_calibration_transform(transform)
        self._mark_calibration_dirty()
        self._sync_route_calibration_ui()

    def _mark_calibration_dirty(self) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active:
            return
        state.dirty = (
            self._normalized_calibration_transform(state.current_transform)
            != self._normalized_calibration_transform(state.original_transform)
        )

    def end_route_calibration(self) -> None:
        self.confirm_exit_route_calibration()

    def save_route_calibration(self) -> bool:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active:
            return True
        if getattr(state, "target_type", "route") == "annotation":
            writer = getattr(self.window.route_mgr, "save_annotation_calibration", None)
            saved = bool(callable(writer) and writer(state.annotation_path, dict(state.current_transform)))
        else:
            if getattr(state, "batch", False):
                writer = getattr(self.window.route_mgr, "save_route_calibration", None)
                if not callable(writer):
                    styled_info(
                        self.window,
                        strings.ROUTE_CALIBRATION_SAVE_FAILED_TITLE,
                        strings.ROUTE_BATCH_CALIBRATION_SAVE_FAILED_BODY,
                    )
                    return False
                batch_ids = getattr(state, "batch_route_ids", [])
                if not batch_ids:
                    return True
                failed = 0
                for route_id in batch_ids:
                    if not writer(route_id, dict(state.current_transform)):
                        failed += 1
                if failed:
                    styled_info(
                        self.window,
                        strings.ROUTE_CALIBRATION_SAVE_FAILED_TITLE,
                        strings.ROUTE_BATCH_CALIBRATION_SAVE_FAILED_BODY,
                    )
                    return False
                saved = True
            else:
                writer = getattr(self.window.route_mgr, "save_route_calibration", None)
                if callable(writer):
                    saved = writer(state.route_id, dict(state.current_transform))
                else:
                    coord_writer = getattr(self.window.route_mgr, "update_route_coord_transform", None)
                    version_writer = getattr(self.window.route_mgr, "add_current_route_enable_version", None)
                    saved = bool(callable(coord_writer) and coord_writer(state.route_id, dict(state.current_transform)))
                    if saved and callable(version_writer):
                        saved = bool(version_writer(state.route_id))
        if not saved:
            styled_info(
                self.window,
                strings.ROUTE_CALIBRATION_SAVE_FAILED_TITLE,
                strings.ROUTE_CALIBRATION_SAVE_FAILED_BODY,
            )
            return False
        saved_name = state.name
        if getattr(state, "target_type", "route") == "annotation":
            state.reset()
            self._sync_route_calibration_ui()
            try:
                self.window.route_mgr.invalidate_annotation_cache()
                self.window.map_view._refresh_from_last_frame()
            except Exception:
                pass
            self._restore_route_calibration_settings_dialog(refresh=True)
        else:
            state.original_transform = dict(state.current_transform)
            state.dirty = False
            self._sync_route_calibration_ui()
        try:
            self.refresh_tracked_routes()
        except Exception:
            pass
        if getattr(state, "batch", False):
            batch_count = len(getattr(state, "batch_route_ids", []))
            toast(self.window, strings.ROUTE_BATCH_CALIBRATION_SAVED_FMT.format(name=saved_name, count=batch_count))
        else:
            toast(self.window, strings.ROUTE_CALIBRATION_SAVED_FMT.format(name=saved_name))
        return True

    def discard_route_calibration(self) -> None:
        state = getattr(self.window, "route_calibration_state", None)
        restore_settings = bool(state is not None and getattr(state, "target_type", "route") == "annotation")
        if state is not None:
            state.reset()
        self._sync_route_calibration_ui()
        if restore_settings:
            self._restore_route_calibration_settings_dialog(refresh=True)

    def _restore_route_calibration_settings_dialog(self, *, refresh: bool = False) -> None:
        dialog = getattr(self.window, "route_calibration_settings_dialog", None)
        if dialog is None:
            return
        self.window.route_calibration_settings_dialog = None
        if refresh:
            reloader = getattr(dialog, "_reload_annotation_coord_editors", None)
            if callable(reloader):
                try:
                    reloader()
                except RuntimeError:
                    return
        try:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except RuntimeError:
            return

    def confirm_exit_route_calibration(self) -> bool:
        state = getattr(self.window, "route_calibration_state", None)
        if state is None or not state.active:
            return True
        self._mark_calibration_dirty()
        if not state.dirty:
            self.discard_route_calibration()
            return True
        choice = self._prompt_calibration_save_discard_cancel()
        if choice == "cancel":
            return False
        if choice == "save" and not self.save_route_calibration():
            return False
        self.discard_route_calibration()
        return True

    def _prompt_calibration_save_discard_cancel(self) -> str:
        dialog = StyledDialogBase(self.window, strings.ROUTE_CALIBRATION_EXIT_TITLE, min_width=380, max_width=420)
        body = QLabel(strings.ROUTE_CALIBRATION_EXIT_UNSAVED_BODY)
        body.setObjectName("BodyLabel")
        body.setWordWrap(True)
        dialog.shell_layout.addWidget(body)

        button_row = QHBoxLayout()
        button_row.addStretch()
        result = {"value": "cancel"}
        for value, text in (
            ("discard", strings.ROUTE_CALIBRATION_EXIT_DISCARD),
            ("cancel", strings.ROUTE_CALIBRATION_EXIT_CANCEL),
            ("save", strings.ROUTE_CALIBRATION_EXIT_SAVE),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, v=value: (result.__setitem__("value", v), dialog.accept()))
            button_row.addWidget(button)
        dialog.shell_layout.addLayout(button_row)
        center_dialog(dialog, self.window)
        dialog.exec()
        return result["value"]

    def _prompt_save_discard_cancel(self) -> str:
        dialog = StyledDialogBase(self.window, strings.ROUTE_DRAWING_EXIT_TITLE, min_width=380, max_width=420)
        body = QLabel(strings.ROUTE_DRAWING_EXIT_UNSAVED_BODY)
        body.setObjectName("BodyLabel")
        body.setWordWrap(True)
        dialog.shell_layout.addWidget(body)

        button_row = QHBoxLayout()
        button_row.addStretch()
        result = {"value": "cancel"}
        for value, text in (
            ("discard", strings.ROUTE_DRAWING_EXIT_DISCARD),
            ("cancel", strings.ROUTE_DRAWING_EXIT_CANCEL),
            ("save", strings.ROUTE_DRAWING_EXIT_SAVE),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, v=value: (result.__setitem__("value", v), dialog.accept()))
            button_row.addWidget(button)
        dialog.shell_layout.addLayout(button_row)
        dialog.adjustSize()
        center_dialog(dialog, self.window)
        if dialog.exec() != QDialog.Accepted:
            return "cancel"
        return result["value"]

    @staticmethod
    def _drawing_point_fields_from_annotation(point_fields: dict | None) -> dict:
        if not isinstance(point_fields, dict):
            return {}
        copied: dict = {}
        for key in ("label", "type", "typeId", "radius", "sourceId", "manual", "node_type"):
            if key in point_fields:
                copied[key] = point_fields[key]
        return copied

    def append_drawing_point(
        self,
        x: int,
        y: int,
        index_override: int | None = None,
        point_fields: dict | None = None,
        node_type_override: str | None = None,
    ) -> None:
        state = self.window.route_drawing_state
        if not state.active or state.paused:
            return
        external_fields = self._drawing_point_fields_from_annotation(point_fields)
        annotation = external_fields if external_fields else self._drawing_annotation_for_new_point()
        if annotation is False:
            return
        x, y = self._drawing_resource_xy(x, y, route_id=state.route_id)
        point = {
            "id": self.window.route_mgr.new_route_point_id(),
            "x": int(x),
            "y": int(y),
            "node_type": node_type_override
            if node_type_override in {"collect", "teleport", "virtual"}
            else state.node_type
            if state.node_type in {"collect", "teleport", "virtual"}
            else "collect",
            "_drawing_new": True,
        }
        if isinstance(annotation, dict):
            if "typeId" in annotation:
                point["typeId"] = annotation["typeId"]
                point["type"] = annotation.get("type") or annotation["typeId"]
            if "node_type" in annotation:
                point["node_type"] = normalize_node_type(annotation.get("node_type"))
            for key in ("label", "radius", "sourceId", "manual"):
                if key in annotation:
                    point[key] = annotation[key]
        if index_override is None:
            index = self._drawing_insert_index(x, y)
        else:
            try:
                index = int(index_override)
            except (TypeError, ValueError):
                index = self._drawing_insert_index(x, y)
            index = max(0, min(len(state.draft_points), index))
        state.draft_points.insert(index, point)
        state.undo_stack.append({"op": "add", "index": index, "point": deepcopy(point)})
        state.added_count += 1
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def append_drawing_point_from_context_menu(
        self,
        x: int,
        y: int,
        point_fields: dict | None = None,
        node_type_override: str | None = None,
    ) -> None:
        state = self.window.route_drawing_state
        if not state.active or state.paused:
            return
        if state.insert_at_end:
            self.append_drawing_point(x, y, point_fields=point_fields, node_type_override=node_type_override)
            return

        suggested = self._drawing_insert_index(x, y)
        result = open_insert_point_dialog(
            self.window,
            x,
            y,
            [{
                "route_id": state.route_id,
                "display_label": state.name or state.route_id,
                "points_count": len(state.draft_points),
                "suggested_index": suggested,
            }],
        )
        if result is None:
            return

        selected_ids, overrides = result
        if state.route_id not in selected_ids:
            return
        self.append_drawing_point(
            x,
            y,
            index_override=overrides.get(state.route_id, suggested),
            point_fields=point_fields,
            node_type_override=node_type_override,
        )

    def _drawing_resource_xy(self, x: int | float, y: int | float, *, route_id: str | None = None) -> tuple[int, int]:
        try:
            adapter = None
            if route_id is not None:
                adapter = self._route_coordinate_adapter(route_id)
            if adapter is None:
                getter = getattr(getattr(self.window, "map_view", None), "coordinate_adapter", None)
                adapter = getter() if callable(getter) else None
            if adapter is None:
                return int(round(float(x))), int(round(float(y)))
            tx, ty = adapter.to_internal(float(x), float(y))
            return int(round(tx)), int(round(ty))
        except Exception:
            return int(x), int(y)

    def _drawing_insert_index(self, x: int, y: int) -> int:
        state = self.window.route_drawing_state
        points = state.draft_points
        if state.insert_at_end or not points:
            return len(points)

        best: tuple[float, int] | None = None
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                continue
            try:
                dx = float(point["x"]) - float(x)
                dy = float(point["y"]) - float(y)
            except (KeyError, TypeError, ValueError):
                continue
            dist_sq = dx * dx + dy * dy
            if best is None or dist_sq < best[0]:
                best = (dist_sq, index)
        if best is None:
            return len(points)
        return min(len(points), best[1] + 1)

    def _drawing_annotation_for_new_point(self) -> dict | bool | None:
        state = self.window.route_drawing_state
        if not state.add_node_annotation:
            return None
        if state.same_annotation_type:
            if not state.annotation_type_id:
                styled_info(
                    self.window,
                    strings.ANNOTATION_TYPE_PICKER_TITLE,
                    strings.ROUTE_DRAWING_SELECT_ANNOTATION_FIRST,
                )
                return False
            return {"typeId": state.annotation_type_id, "type": state.annotation_type or state.annotation_type_id}

        selected = self._pick_route_node_annotation(state.annotation_type_id)
        if selected is None:
            return False
        return selected

    def _pick_route_node_annotation(self, current_type_id: str = "") -> dict | None:
        items = self.window.route_mgr.annotation_type_items()
        if not items:
            styled_info(self.window, strings.ANNOTATION_TYPE_PICKER_TITLE, strings.ANNOTATION_TYPE_PICKER_EMPTY)
            return None
        selected = open_annotation_type_picker(self.window, items, current_type_id)
        if selected is None:
            return None
        type_id = str(selected.get("typeId") or "").strip()
        if not type_id:
            return None
        return {"typeId": type_id, "type": str(selected.get("type") or type_id).strip() or type_id}

    def delete_drawing_point(self, index: int) -> None:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= index < len(state.draft_points)):
            return
        point = state.draft_points.pop(index)
        state.undo_stack.append({"op": "delete", "index": index, "point": deepcopy(point)})
        if point.get("_drawing_new"):
            state.added_count = max(0, state.added_count - 1)
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def undo_route_drawing(self) -> None:
        state = self.window.route_drawing_state
        if not state.active or not state.undo_stack:
            return
        action = state.undo_stack.pop()
        op = action.get("op")
        if op == "add":
            index = int(action.get("index", -1))
            if 0 <= index < len(state.draft_points):
                point = state.draft_points.pop(index)
                if point.get("_drawing_new"):
                    state.added_count = max(0, state.added_count - 1)
        elif op == "delete":
            index = max(0, min(len(state.draft_points), int(action.get("index", len(state.draft_points)))))
            point = deepcopy(action.get("point") or {})
            state.draft_points.insert(index, point)
            if point.get("_drawing_new"):
                state.added_count += 1
        elif op == "clear":
            index = int(action.get("index", len(state.draft_points)))
            points = [deepcopy(point) for point in action.get("points", []) if isinstance(point, dict)]
            for offset, point in enumerate(points):
                state.draft_points.insert(index + offset, point)
                if point.get("_drawing_new"):
                    state.added_count += 1
        elif op == "annotation":
            index = int(action.get("index", -1))
            before = deepcopy(action.get("before") or {})
            if 0 <= index < len(state.draft_points) and isinstance(before, dict):
                state.draft_points[index] = before
        elif op == "node_type":
            index = int(action.get("index", -1))
            before = deepcopy(action.get("before") or {})
            if 0 <= index < len(state.draft_points) and isinstance(before, dict):
                state.draft_points[index] = before
        elif op == "label":
            index = int(action.get("index", -1))
            if 0 <= index < len(state.draft_points):
                point = state.draft_points[index]
                if isinstance(point, dict):
                    before = action.get("before", None)
                    if before is None:
                        point.pop("label", None)
                    else:
                        point["label"] = before
        elif op == "move":
            index = int(action.get("index", -1))
            before = action.get("before") or {}
            if 0 <= index < len(state.draft_points) and isinstance(before, dict):
                point = state.draft_points[index]
                if isinstance(point, dict):
                    try:
                        before_x = float(before["x"])
                        before_y = float(before["y"])
                        point["x"] = int(before_x) if before_x.is_integer() else before_x
                        point["y"] = int(before_y) if before_y.is_integer() else before_y
                    except (KeyError, TypeError, ValueError):
                        pass
        elif op == "reorder":
            try:
                from_index = int(action.get("from", -1))
                to_index = int(action.get("to", -1))
            except (TypeError, ValueError):
                from_index = -1
                to_index = -1
            if 0 <= to_index < len(state.draft_points):
                point = state.draft_points.pop(to_index)
                restore_index = max(0, min(len(state.draft_points), from_index))
                state.draft_points.insert(restore_index, point)
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def clear_route_drawing(self) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        removed: list[dict] = []
        kept: list[dict] = []
        first_removed = None
        for index, point in enumerate(state.draft_points):
            if isinstance(point, dict) and point.get("_drawing_new"):
                if first_removed is None:
                    first_removed = index
                removed.append(deepcopy(point))
            else:
                kept.append(point)
        if not removed:
            return
        state.draft_points = kept
        state.undo_stack.append({"op": "clear", "index": first_removed or len(kept), "points": removed})
        state.added_count = 0
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def set_route_drawing_hide_other_routes(self, enabled: bool) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.hide_other_routes = bool(enabled)
        self._sync_route_drawing_ui()

    def set_route_drawing_loop(self, enabled: bool) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.loop = bool(enabled)
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def toggle_route_drawing_paused(self) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.paused = not state.paused
        self._sync_route_drawing_ui()

    def set_route_drawing_node_type(self, node_type: str) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.node_type = node_type if node_type in {"collect", "teleport", "virtual"} else "collect"
        self._sync_route_drawing_ui()

    def set_route_drawing_insert_at_end(self, enabled: bool) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.insert_at_end = bool(enabled)
        self._sync_route_drawing_ui()

    def move_drawing_point(self, index: int, x: int, y: int, sync: bool = True) -> bool:
        state = self.window.route_drawing_state
        if not state.active or state.paused or not (0 <= index < len(state.draft_points)):
            return False
        point = state.draft_points[index]
        if not isinstance(point, dict):
            return False
        try:
            next_x, next_y = self._drawing_resource_xy(x, y, route_id=state.route_id)
        except (TypeError, ValueError):
            return False

        current: tuple[int, int] | None
        try:
            current = (int(float(point["x"])), int(float(point["y"])))
        except (KeyError, TypeError, ValueError):
            current = None
        if current == (next_x, next_y):
            return False

        point["x"] = next_x
        point["y"] = next_y
        self._mark_drawing_dirty()
        if sync:
            self._sync_route_drawing_ui()
        return True

    def finish_move_drawing_point(
        self,
        index: int,
        before_x: int,
        before_y: int,
        after_x: int,
        after_y: int,
    ) -> bool:
        state = self.window.route_drawing_state
        if not state.active or state.paused or not (0 <= index < len(state.draft_points)):
            return False
        point = state.draft_points[index]
        if not isinstance(point, dict):
            return False
        try:
            before = self._drawing_resource_xy(before_x, before_y, route_id=state.route_id)
            after = self._drawing_resource_xy(after_x, after_y, route_id=state.route_id)
        except (TypeError, ValueError):
            return False
        if before == after:
            return False

        point["x"] = after[0]
        point["y"] = after[1]
        state.undo_stack.append({
            "op": "move",
            "index": index,
            "before": {"x": before[0], "y": before[1]},
            "after": {"x": after[0], "y": after[1]},
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()
        return True

    def reorder_drawing_point(self, from_index: int, to_index: int) -> bool:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(from_index, int) or not (0 <= from_index < len(state.draft_points)):
            return False
        try:
            target = int(to_index)
        except (TypeError, ValueError):
            return False
        target = max(0, min(len(state.draft_points) - 1, target))
        if from_index == target:
            return False

        point = state.draft_points.pop(from_index)
        state.draft_points.insert(target, point)
        state.undo_stack.append({
            "op": "reorder",
            "from": from_index,
            "to": target,
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()
        return True

    def set_drawing_point_label(self, point_index: int, label: object, *, record_undo: bool = True) -> bool:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(point_index, int) or not (0 <= point_index < len(state.draft_points)):
            return False
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return False
        before = point.get("label", None)
        text = str(label or "").strip()
        if text:
            point["label"] = text
        else:
            point.pop("label", None)
        after = point.get("label", None)
        if before == after:
            return False
        if record_undo:
            state.undo_stack.append({
                "op": "label",
                "index": point_index,
                "before": before,
                "after": after,
            })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()
        return True

    def _on_drawing_node_panel_label_changed(self, point_index: int, _before: object, after: object) -> None:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(point_index, int) or not (0 <= point_index < len(state.draft_points)):
            return
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return
        text = str(after or "").strip()
        if text:
            point["label"] = text
        else:
            point.pop("label", None)
        self._mark_drawing_dirty()
        context = {
            "active": True,
            "paused": state.paused,
            "route_id": state.route_id,
            "name": state.name,
            "points": deepcopy(state.draft_points),
            "node_type": state.node_type,
            "insert_at_end": state.insert_at_end,
            "add_node_annotation": state.add_node_annotation,
            "same_annotation_type": state.same_annotation_type,
            "annotation_type": state.annotation_type,
            "annotation_type_id": state.annotation_type_id,
            "hide_other_routes": state.hide_other_routes,
            "loop": state.loop,
        }
        try:
            self.window.map_view.set_route_drawing_context(context)
        except Exception:
            pass

    def _on_drawing_node_panel_label_committed(self, point_index: int, before: object, after: object) -> None:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(point_index, int) or not (0 <= point_index < len(state.draft_points)):
            return
        if before == after:
            return
        state.undo_stack.append({
            "op": "label",
            "index": point_index,
            "before": before,
            "after": after,
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def _on_drawing_node_panel_coord_changed(
        self,
        point_index: int,
        key: str,
        _before: object,
        after: object,
    ) -> None:
        state = self.window.route_drawing_state
        if (
            not state.active
            or key not in {"x", "y"}
            or not isinstance(point_index, int)
            or not (0 <= point_index < len(state.draft_points))
        ):
            return
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return
        if point.get(key) == after:
            return
        point[key] = after
        self._mark_drawing_dirty()
        context = {
            "active": True,
            "paused": state.paused,
            "route_id": state.route_id,
            "name": state.name,
            "points": deepcopy(state.draft_points),
            "node_type": state.node_type,
            "insert_at_end": state.insert_at_end,
            "add_node_annotation": state.add_node_annotation,
            "same_annotation_type": state.same_annotation_type,
            "annotation_type": state.annotation_type,
            "annotation_type_id": state.annotation_type_id,
            "hide_other_routes": state.hide_other_routes,
            "loop": state.loop,
        }
        try:
            self.window.map_view.set_route_drawing_context(context)
        except Exception:
            pass

    def _on_drawing_node_panel_coord_committed(
        self,
        point_index: int,
        key: str,
        before: object,
        after: object,
    ) -> None:
        state = self.window.route_drawing_state
        if (
            not state.active
            or key not in {"x", "y"}
            or before == after
            or not isinstance(point_index, int)
            or not (0 <= point_index < len(state.draft_points))
        ):
            return
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return
        before_point = dict(point)
        before_point[key] = before
        after_point = dict(point)
        after_point[key] = after
        state.undo_stack.append({
            "op": "move",
            "index": point_index,
            "before": {"x": before_point.get("x"), "y": before_point.get("y")},
            "after": {"x": after_point.get("x"), "y": after_point.get("y")},
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def _on_drawing_node_panel_annotation_changed(self, point_index: int, before: object, after: object) -> None:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(point_index, int) or not (0 <= point_index < len(state.draft_points)):
            return
        if not isinstance(after, dict):
            return
        if isinstance(before, dict) and before == after:
            return
        state.draft_points[point_index] = dict(after)
        state.undo_stack.append({
            "op": "annotation",
            "index": point_index,
            "before": deepcopy(before) if isinstance(before, dict) else before,
            "after": deepcopy(after),
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def change_drawing_point_order(self, point_index: int) -> None:
        state = self.window.route_drawing_state
        if not state.active or not isinstance(point_index, int) or not (0 <= point_index < len(state.draft_points)):
            return
        if len(state.draft_points) < 2:
            return

        target = open_point_order_dialog(
            self.window,
            state.name or state.route_id,
            point_index,
            len(state.draft_points),
        )
        if target is None:
            return
        self.reorder_drawing_point(point_index, target)

    def set_drawing_point_node_type(self, point_index: int, node_type: str) -> bool:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= point_index < len(state.draft_points)):
            return False
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return False

        normalized = normalize_node_type(node_type)
        raw_value = str(point.get("node_type") or "").strip().casefold()
        if raw_value == normalized:
            return False

        before = deepcopy(point)
        point["node_type"] = normalized
        state.undo_stack.append({
            "op": "node_type",
            "index": point_index,
            "before": before,
            "after": deepcopy(point),
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()
        return True

    def change_drawing_point_node_type(self, point_index: int, global_pos) -> None:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= point_index < len(state.draft_points)):
            return
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return

        current = normalize_node_type(point.get("node_type"))
        self.set_drawing_point_node_type(point_index, current)

        def apply_node_type(node_type: str) -> None:
            self.set_drawing_point_node_type(point_index, node_type)

        self.window._node_type_popup = show_node_type_popup(
            self.window.map_view,
            global_pos,
            current,
            apply_node_type,
        )

    def set_route_drawing_add_annotation(self, enabled: bool) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.add_node_annotation = bool(enabled)
        if not state.add_node_annotation:
            state.same_annotation_type = False
            state.annotation_type = ""
            state.annotation_type_id = ""
        self._sync_route_drawing_ui()

    def set_route_drawing_same_annotation(self, enabled: bool) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        state.same_annotation_type = bool(enabled)
        if not state.same_annotation_type:
            state.annotation_type = ""
            state.annotation_type_id = ""
        self._sync_route_drawing_ui()

    def select_route_drawing_annotation_type(self) -> None:
        state = self.window.route_drawing_state
        if not state.active:
            return
        selected = self._pick_route_node_annotation(state.annotation_type_id)
        if selected is None:
            return
        state.annotation_type_id = selected["typeId"]
        state.annotation_type = selected["type"]
        self._sync_route_drawing_ui()

    def drawing_point_annotation_type_id(self, point_index: int) -> str:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= point_index < len(state.draft_points)):
            return ""
        point = state.draft_points[point_index]
        return str(point.get("typeId") or "") if isinstance(point, dict) else ""

    def change_drawing_point_annotation(self, point_index: int, node_type_resolver=None) -> None:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= point_index < len(state.draft_points)):
            return
        current_type_id = self.drawing_point_annotation_type_id(point_index)
        selected = self._pick_route_node_annotation(current_type_id)
        if selected is None:
            return
        before = deepcopy(state.draft_points[point_index])
        state.draft_points[point_index]["typeId"] = selected["typeId"]
        state.draft_points[point_index]["type"] = selected["type"]
        if callable(node_type_resolver):
            state.draft_points[point_index]["node_type"] = normalize_node_type(node_type_resolver(selected["typeId"]))
        state.undo_stack.append({
            "op": "annotation",
            "index": point_index,
            "before": before,
            "after": deepcopy(state.draft_points[point_index]),
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def clear_drawing_point_annotation(self, point_index: int) -> None:
        state = self.window.route_drawing_state
        if not state.active or not (0 <= point_index < len(state.draft_points)):
            return
        point = state.draft_points[point_index]
        if not isinstance(point, dict):
            return
        if not (str(point.get("typeId") or "").strip() or str(point.get("type") or "").strip()):
            return
        before = deepcopy(point)
        point.pop("typeId", None)
        point.pop("type", None)
        state.undo_stack.append({
            "op": "annotation",
            "index": point_index,
            "before": before,
            "after": deepcopy(point),
        })
        self._mark_drawing_dirty()
        self._sync_route_drawing_ui()

    def show_route_drawing_help(self) -> None:
        styled_info(
            self.window,
            strings.ROUTE_DRAWING_HELP_TITLE,
            strings.ROUTE_DRAWING_HELP_BODY,
        )

    def show_add_category_row(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = True
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText(strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        self.window._add_category_row.show()
        self.window._add_category_input.setFocus()
        self.window.window_mode_controller.schedule_layout_refresh()

    def cancel_add_category(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = False
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText(strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        self.window._add_category_row.hide()
        self.window.window_mode_controller.schedule_layout_refresh()

    def confirm_add_category(self) -> None:
        if not self.confirm_exit_route_drawing():
            return
        if self.window._add_category_input is None:
            return
        name = self.window._add_category_input.text().strip()
        if not name:
            self.window._add_category_input.clear()
            self.window._add_category_input.setPlaceholderText(strings.ROUTE_CATEGORY_EMPTY)
            self.window._add_category_input.setFocus()
            return
        if not self.window.route_mgr.create_category(name):
            self.window._add_category_input.selectAll()
            self.window._add_category_input.setPlaceholderText(strings.ROUTE_CATEGORY_INVALID)
            self.window._add_category_input.setFocus()
            return
        self.cancel_add_category()
        self.reload_route_list()

    def show_add_route_row(self, category: str) -> None:
        section = self.window._route_sections.get(category)
        if section is None:
            return
        for cat, other in self.window._route_sections.items():
            if cat != category and other.is_adding_route():
                other.hide_add_route_row()
        section.show_add_route_row()
        self.window.window_mode_controller.schedule_layout_refresh()

    def cancel_add_route(self, category: str) -> None:
        section = self.window._route_sections.get(category)
        if section is None:
            return
        section.hide_add_route_row()
        self.window.window_mode_controller.schedule_layout_refresh()

    def confirm_add_route(self, category: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        section = self.window._route_sections.get(category)
        if section is None:
            return
        name = section.current_add_route_name()
        if not name:
            section.show_add_route_error(strings.ROUTE_RENAME_EMPTY)
            return
        if not self.window.route_mgr.create_route(category, name):
            section.show_add_route_error(strings.ROUTE_RENAME_INVALID)
            return
        section.hide_add_route_row()
        self.reload_route_list()

    def queue_cancel_add_category_if_needed(self) -> None:
        QTimer.singleShot(0, self.cancel_add_category_if_focus_left)

    def cancel_add_category_if_focus_left(self) -> None:
        if not self.window._adding_category:
            return
        app = QApplication.instance()
        focus_widget = app.focusWidget() if app is not None else None
        if self.is_add_category_widget(focus_widget):
            return
        self.cancel_add_category()

    def is_add_category_widget(self, widget: QWidget | None) -> bool:
        current = widget
        while current is not None:
            if current is self.window._add_category_row:
                return True
            current = current.parentWidget()
        return False

    def create_route_checkbox(self, route_id: str, route_name: str) -> QCheckBox:
        checkbox = ElidedCheckBox(route_name)
        checkbox.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
        checkbox.setProperty("routeId", route_id)
        checkbox.setChecked(self.window.route_mgr.visibility.get(route_id, False))
        self.apply_route_checkbox_color(checkbox, route_id)
        checkbox.toggled.connect(
            lambda enabled, known_route_id=route_id, source=checkbox: self.toggle_route(known_route_id, enabled, source)
        )
        self.window._route_checkboxes.setdefault(route_id, []).append(checkbox)
        return checkbox

    @staticmethod
    def route_checkbox_name(checkbox: QCheckBox) -> str:
        route_id = checkbox.property("routeId")
        if isinstance(route_id, str) and route_id:
            return route_id
        if isinstance(checkbox, ElidedCheckBox):
            return checkbox.full_text()
        return checkbox.text()

    def begin_route_rename(self, route_item: RouteListItem) -> None:
        if self.window._active_route_rename_item is not None and self.window._active_route_rename_item is not route_item:
            self.window._active_route_rename_item.cancel_rename()
        self.window._active_route_rename_item = route_item
        route_item.start_rename()

    def cancel_active_route_rename(self) -> None:
        if self.window._active_route_rename_item is None:
            return
        self.window._active_route_rename_item.cancel_rename()
        self.window._active_route_rename_item = None

    def confirm_route_rename(self, route_item: RouteListItem) -> None:
        new_name = route_item.current_rename_value()
        if not new_name:
            route_item.show_rename_error(strings.ROUTE_RENAME_EMPTY)
            return
        if not self.confirm_exit_route_drawing():
            return
        if not self.window.route_mgr.rename_route(route_item.category, route_item.route_name, new_name):
            route_item.show_rename_error(strings.ROUTE_RENAME_INVALID)
            return
        self.window._active_route_rename_item = None
        self.reload_route_list()

    def rename_category(self, category: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        accepted, new_name = prompt_text_input(
            self.window,
            title=strings.ROUTE_CATEGORY_RENAME_TITLE,
            label=f"当前分类：{category}",
            value=category,
            placeholder=strings.ROUTE_CATEGORY_RENAME_PLACEHOLDER,
            confirm_text=strings.ROUTE_CATEGORY_RENAME_CONFIRM,
            cancel_text=strings.ROUTE_CATEGORY_RENAME_CANCEL,
        )
        if not accepted:
            return
        if not new_name:
            styled_info(self.window, strings.ROUTE_CATEGORY_RENAME_TITLE, strings.ROUTE_CATEGORY_RENAME_EMPTY)
            return
        if not self.window.route_mgr.rename_category(category, new_name):
            styled_info(self.window, strings.ROUTE_CATEGORY_RENAME_TITLE, strings.ROUTE_CATEGORY_RENAME_INVALID)
            return

        self.window._route_section_expanded[new_name] = self.window._route_section_expanded.pop(
            category,
            self.resolve_route_section_expanded(category),
        )
        self.reload_route_list()

    def show_route_notes_dialog(self, category: str, name: str) -> None:
        route = next(
            (
                route
                for known_category, route in self.window.route_mgr.iter_routes()
                if known_category == category and route.get("display_name") == name
            ),
            None,
        )
        route_id = self.window.route_mgr.route_id(route) if route is not None else ""
        if route is None or not route_id:
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            return
        current_notes = self.window.route_mgr.get_route_notes(category, name)
        current_color = self.window.route_mgr.route_color_override(route_id) or None
        route_color = self.window.route_mgr.color_for(route_id) if route_id else (255, 209, 26)
        nodes = self._route_notes_nodes(route)
        current_enable_versions = self.window.route_mgr.route_enable_versions(route_id)
        enable_version_options = resource_metadata.route_enable_version_options(current_enable_versions or [])
        coord_getter = getattr(self.window.route_mgr, "route_coord_transform", None)
        current_coord_transform = coord_getter(route_id) if callable(coord_getter) else None
        if not isinstance(self.window, QWidget):
            result = edit_route_notes(
                None,
                name,
                current_notes,
                route_color,
                current_color,
                nodes,
                current_enable_versions,
                enable_version_options,
                coord_transform=current_coord_transform,
            )
            accepted, notes, color = result[:3]
            nodes_changed = bool(result[3]) if len(result) > 3 else False
            edited_nodes = result[4] if len(result) > 4 else nodes
            enable_versions_changed = bool(result[5]) if len(result) > 5 else False
            edited_enable_versions = result[6] if len(result) > 6 else current_enable_versions
            coord_changed = bool(result[7]) if len(result) > 7 else False
            edited_coord_transform = result[8] if len(result) > 8 else current_coord_transform
            notes_changed = notes != current_notes or color != current_color
            if not accepted or (not notes_changed and not nodes_changed and not enable_versions_changed and not coord_changed):
                return
            if notes_changed and not self.window.route_mgr.update_route_notes_and_color(category, name, notes, color):
                styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
                return
            if nodes_changed and not self.window.route_mgr.save_route_points(route_id, edited_nodes):
                styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
                return
            if enable_versions_changed and not self.window.route_mgr.update_route_enable_versions(
                route_id,
                edited_enable_versions or [],
            ):
                styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
                return
            coord_writer = getattr(self.window.route_mgr, "update_route_coord_transform", None)
            if coord_changed and callable(coord_writer) and not coord_writer(route_id, edited_coord_transform):
                styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
                return
            self._route_notes_refresh_preview()
            toast(self.window, strings.ROUTE_NOTES_SAVED.format(name=name))
            return

        session = getattr(self, "_route_notes_session", None)
        if isinstance(session, dict):
            dialog = session.get("dialog")
            if session.get("route_id") == route_id and dialog is not None:
                try:
                    dialog.show()
                    dialog.raise_()
                    dialog.activateWindow()
                except Exception:
                    pass
                return
            if not self._discard_route_notes_session(prompt=True):
                return
        dialog_parent = self.window if isinstance(self.window, QWidget) else None
        dialog = RouteNotesDialog(
            dialog_parent,
            name,
            current_notes,
            route_color,
            current_color,
            nodes,
            enable_versions=current_enable_versions,
            enable_version_options=enable_version_options,
            coord_transform=current_coord_transform,
            modal=False,
        )
        center_dialog(dialog, self.window)
        self._route_notes_session = {
            "route_id": route_id,
            "category": category,
            "name": name,
            "route": route,
            "dialog": dialog,
            "original_notes": current_notes,
            "original_color": current_color,
            "original_had_color": "color" in route,
            "original_color_value": route.get("color"),
            "original_had_notes": "notes" in route,
            "original_notes_value": route.get("notes"),
            "original_points": deepcopy(route.get("points", []) or []),
            "original_draft_nodes": dialog.draft_nodes(),
            "original_enable_versions": current_enable_versions,
            "original_had_enable_versions": "enable_versions" in route,
            "original_enable_versions_value": deepcopy(route.get("enable_versions")),
            "original_coord_transform": current_coord_transform,
        }
        dialog.nodes_changed_signal.connect(lambda rid=route_id: self._on_route_notes_nodes_changed(rid))
        dialog.color_preview_changed.connect(lambda _color, rid=route_id: self._on_route_notes_color_changed(rid))
        dialog.confirm_requested.connect(self._confirm_route_notes_session)
        dialog.cancel_requested.connect(lambda: self._discard_route_notes_session(prompt=True))
        dialog.show()
        dialog.raise_()

    def _route_notes_refresh_preview(self) -> None:
        self.refresh_route_checkbox_colors()
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.refresh_tracked_routes()
        except Exception:
            pass

    def _route_notes_session_dirty(self, session: dict | None = None) -> bool:
        session = session if isinstance(session, dict) else getattr(self, "_route_notes_session", None)
        if not isinstance(session, dict):
            return False
        dialog = session.get("dialog")
        if dialog is None:
            return False
        return (
            dialog.notes_text() != session.get("original_notes", "")
            or dialog.color_override() != session.get("original_color")
            or dialog.draft_nodes() != session.get("original_draft_nodes", [])
            or dialog.enable_versions() != session.get("original_enable_versions")
            or (
                hasattr(dialog, "coord_transform_changed")
                and dialog.coord_transform_changed()
            )
        )

    def _route_notes_nodes_changed_for_save(self, session: dict) -> bool:
        dialog = session.get("dialog")
        if dialog is None:
            return False
        return dialog.nodes() != session.get("original_points", [])

    def _apply_route_notes_preview(self, *, nodes: list[dict] | None = None, color: str | None | object = ...) -> None:
        session = getattr(self, "_route_notes_session", None)
        if not isinstance(session, dict):
            return
        route = self.window.route_mgr.route_for_id(str(session.get("route_id") or ""))
        if route is None:
            return
        dialog = session.get("dialog")
        if nodes is None and dialog is not None:
            nodes = dialog.draft_nodes()
        if nodes is not None:
            route["points"] = [dict(point) for point in nodes if isinstance(point, dict)]
        if color is ... and dialog is not None:
            color = dialog.color_override()
        if color is not ...:
            if color is None:
                route.pop("color", None)
            else:
                route["color"] = color
        self._route_notes_refresh_preview()

    def _on_route_notes_nodes_changed(self, route_id: str) -> None:
        if not self.has_active_route_notes_draft(route_id):
            return
        self._apply_route_notes_preview()

    def _on_route_notes_color_changed(self, route_id: str) -> None:
        if not self.has_active_route_notes_draft(route_id):
            return
        self._apply_route_notes_preview()

    def _restore_route_notes_session(self, session: dict | None = None) -> None:
        session = session if isinstance(session, dict) else getattr(self, "_route_notes_session", None)
        if not isinstance(session, dict):
            return
        route = self.window.route_mgr.route_for_id(str(session.get("route_id") or ""))
        if route is None:
            return
        route["points"] = deepcopy(session.get("original_points", []))
        if session.get("original_had_color"):
            route["color"] = session.get("original_color_value")
        else:
            route.pop("color", None)
        if session.get("original_had_notes"):
            route["notes"] = session.get("original_notes_value")
        else:
            route.pop("notes", None)
        if session.get("original_had_enable_versions"):
            route["enable_versions"] = deepcopy(session.get("original_enable_versions_value"))
        else:
            route.pop("enable_versions", None)
        self._route_notes_refresh_preview()

    def _discard_route_notes_session(self, *, prompt: bool) -> bool:
        session = getattr(self, "_route_notes_session", None)
        if not isinstance(session, dict):
            return True
        if prompt and self._route_notes_session_dirty(session):
            confirmed = styled_confirm(
                self.window,
                getattr(strings, "ROUTE_NOTES_DISCARD_TITLE", strings.ROUTE_NOTES_TITLE),
                getattr(strings, "ROUTE_NOTES_DISCARD_BODY", "Discard route detail changes?"),
                confirm_text=getattr(strings, "ROUTE_NOTES_DISCARD_CONFIRM", strings.ROUTE_DRAWING_EXIT_DISCARD),
                cancel_text=strings.ROUTE_DRAWING_EXIT_CANCEL,
            )
            if not confirmed:
                return False
        self._restore_route_notes_session(session)
        dialog = session.get("dialog")
        self._route_notes_session = None
        if dialog is not None:
            try:
                dialog.force_close(False)
            except Exception:
                pass
        return True

    def _confirm_route_notes_session(self) -> bool:
        session = getattr(self, "_route_notes_session", None)
        if not isinstance(session, dict):
            return True
        dialog = session.get("dialog")
        if dialog is None:
            self._route_notes_session = None
            return True

        category = str(session.get("category") or "")
        name = str(session.get("name") or "")
        route_id = str(session.get("route_id") or "")
        notes = dialog.notes_text()
        color = dialog.color_override()
        edited_nodes = dialog.nodes()
        edited_enable_versions = dialog.enable_versions()
        edited_coord_transform = (
            dialog.coord_transform_value() if hasattr(dialog, "coord_transform_value") else None
        )
        coord_changed = bool(
            hasattr(dialog, "coord_transform_changed") and dialog.coord_transform_changed()
        )
        notes_changed = notes != session.get("original_notes", "") or color != session.get("original_color")
        nodes_changed = edited_nodes != session.get("original_points", [])
        enable_versions_changed = edited_enable_versions != session.get("original_enable_versions")
        if not notes_changed and not nodes_changed and not enable_versions_changed and not coord_changed:
            self._route_notes_session = None
            dialog.force_close(True)
            return True

        if notes_changed and not self.window.route_mgr.update_route_notes_and_color(category, name, notes, color):
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            self._apply_route_notes_preview()
            return False
        if nodes_changed and not self.window.route_mgr.save_route_points(route_id, edited_nodes):
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            self._apply_route_notes_preview(nodes=edited_nodes)
            return False
        if enable_versions_changed and not self.window.route_mgr.update_route_enable_versions(
            route_id,
            edited_enable_versions or [],
        ):
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            self._apply_route_notes_preview(nodes=edited_nodes)
            return False
        coord_writer = getattr(self.window.route_mgr, "update_route_coord_transform", None)
        if coord_changed and callable(coord_writer) and not coord_writer(route_id, edited_coord_transform):
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            self._apply_route_notes_preview(nodes=edited_nodes)
            return False

        self._route_notes_session = None
        self._route_notes_refresh_preview()
        dialog.force_close(True)
        toast(self.window, strings.ROUTE_NOTES_SAVED.format(name=name))
        return True

    def has_active_route_notes_draft(self, route_id: str) -> bool:
        session = getattr(self, "_route_notes_session", None)
        return isinstance(session, dict) and str(session.get("route_id") or "") == str(route_id or "")

    def route_notes_draft_nodes(self, route_id: str) -> list[dict] | None:
        if not self.has_active_route_notes_draft(route_id):
            return None
        session = getattr(self, "_route_notes_session", None)
        dialog = session.get("dialog") if isinstance(session, dict) else None
        if dialog is None:
            return None
        return dialog.draft_nodes()

    def update_route_notes_draft_nodes(self, route_id: str, nodes: list[dict], *, refresh: bool = True) -> bool:
        if not self.has_active_route_notes_draft(route_id):
            return False
        session = getattr(self, "_route_notes_session", None)
        dialog = session.get("dialog") if isinstance(session, dict) else None
        if dialog is None:
            return False
        clean_nodes = [dict(point) for point in nodes if isinstance(point, dict)]
        dialog.set_nodes(clean_nodes, refresh=refresh)
        self._apply_route_notes_preview(nodes=clean_nodes)
        return True

    def _route_note_resource_xy(
        self,
        x: int | float,
        y: int | float,
        *,
        route_id: str | None = None,
        coord_adapter=None,
    ) -> tuple[int, int]:
        try:
            adapter = coord_adapter
            if adapter is None:
                getter = getattr(getattr(self.window, "map_view", None), "coordinate_adapter", None)
                adapter = getter() if callable(getter) else None
            if route_id:
                adapter_getter = getattr(getattr(self.window, "route_mgr", None), "route_coordinate_adapter", None)
                if callable(adapter_getter):
                    adapter = adapter_getter(route_id, adapter) or adapter
            if adapter is None:
                return int(round(float(x))), int(round(float(y)))
            tx, ty = adapter.to_internal(float(x), float(y))
            return int(round(tx)), int(round(ty))
        except Exception:
            return int(x), int(y)

    def move_route_notes_point(
        self,
        route_id: str,
        point_index: int,
        x: int | float,
        y: int | float,
        *,
        coord_adapter=None,
        refresh_panel: bool = False,
    ) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not isinstance(point_index, int) or not (0 <= point_index < len(nodes)):
            return False
        point = nodes[point_index]
        if not isinstance(point, dict):
            return False
        next_x, next_y = self._route_note_resource_xy(
            x,
            y,
            route_id=route_id,
            coord_adapter=coord_adapter,
        )
        point["x"] = next_x
        point["y"] = next_y
        return self.update_route_notes_draft_nodes(route_id, nodes, refresh=refresh_panel)

    def reorder_route_notes_point(self, route_id: str, from_index: int, to_index: int) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not isinstance(from_index, int) or not (0 <= from_index < len(nodes)):
            return False
        try:
            target = int(to_index)
        except (TypeError, ValueError):
            return False
        target = max(0, min(len(nodes) - 1, target))
        if target == from_index:
            return False
        point = nodes.pop(from_index)
        nodes.insert(target, point)
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def set_route_notes_point_node_type(self, route_id: str, point_index: int, node_type: str) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not isinstance(point_index, int) or not (0 <= point_index < len(nodes)):
            return False
        point = nodes[point_index]
        if not isinstance(point, dict):
            return False
        point["node_type"] = normalize_node_type(node_type)
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
        if nodes is None or not isinstance(point_index, int) or not (0 <= point_index < len(nodes)):
            return False
        point = nodes[point_index]
        if not isinstance(point, dict):
            return False
        type_id = str(type_id or "").strip()
        if not type_id:
            return False
        point["typeId"] = type_id
        point["type"] = str(type_name or type_id).strip() or type_id
        if node_type is not None:
            point["node_type"] = normalize_node_type(node_type)
        icon_path = self.window.route_mgr.point_icon_path_for(type_id)
        if icon_path:
            point["icon_path"] = icon_path
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def clear_route_notes_point_annotation(self, route_id: str, point_index: int) -> bool:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None or not isinstance(point_index, int) or not (0 <= point_index < len(nodes)):
            return False
        point = nodes[point_index]
        if not isinstance(point, dict):
            return False
        point.pop("typeId", None)
        point.pop("type", None)
        point.pop("icon_path", None)
        return self.update_route_notes_draft_nodes(route_id, nodes)

    def delete_route_notes_points(self, route_id: str, indexes: list[int]) -> int:
        nodes = self.route_notes_draft_nodes(route_id)
        if nodes is None:
            return 0
        cleaned = sorted({index for index in indexes if isinstance(index, int) and 0 <= index < len(nodes)}, reverse=True)
        if not cleaned:
            return 0
        for index in cleaned:
            nodes.pop(index)
        if not self.update_route_notes_draft_nodes(route_id, nodes):
            return 0
        return len(cleaned)

    def _route_notes_nodes(self, route: dict | None) -> list[dict]:
        if route is None:
            return []
        nodes: list[dict] = []
        for point in route.get("points", []) or []:
            if not isinstance(point, dict):
                continue
            copied = dict(point)
            type_id = str(copied.get("typeId") or "").strip()
            if type_id:
                copied["icon_path"] = self.window.route_mgr.point_icon_path_for(type_id)
            nodes.append(copied)
        return nodes

    def delete_route(self, category: str, name: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        confirmed = styled_confirm(
            self.window,
            strings.ROUTE_DELETE_TITLE,
            strings.ROUTE_DELETE_MESSAGE.format(name=name),
            confirm_text=strings.ROUTE_DELETE_CONFIRM,
            cancel_text=strings.ROUTE_DELETE_CANCEL,
        )
        if not confirmed:
            return
        if not self.window.route_mgr.delete_route(category, name):
            return
        self.cancel_active_route_rename()
        self.reload_route_list()

    def delete_category(self, category: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        confirmed = styled_confirm(
            self.window,
            strings.ROUTE_CATEGORY_DELETE_TITLE,
            strings.ROUTE_CATEGORY_DELETE_MESSAGE.format(name=category),
            confirm_text=strings.ROUTE_CATEGORY_DELETE_CONFIRM,
            cancel_text=strings.ROUTE_CATEGORY_DELETE_CANCEL,
        )
        if not confirmed:
            return
        if not self.window.route_mgr.delete_category(category):
            return
        self.window._route_section_expanded.pop(category, None)
        self.cancel_active_route_rename()
        self.reload_route_list()

    def mark_category_routes_compatible(self, category: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        route_widgets = self.window._route_widgets_by_category.get(category, [])
        current_version = resource_metadata.APP_FORMAT_VERSION
        changed_count = 0
        failed_count = 0

        for route_id, _route_name, _route_item in route_widgets:
            if not route_id:
                continue
            route = self.window.route_mgr.route_for_id(route_id)
            enable_versions = resource_metadata.normalize_enable_versions(
                route.get("enable_versions") if isinstance(route, dict) else []
            )
            if current_version in enable_versions:
                continue
            if self.window.route_mgr.add_current_route_enable_version(route_id):
                changed_count += 1
            else:
                failed_count += 1

        if failed_count:
            styled_info(
                self.window,
                strings.ROUTE_CATEGORY_MARK_COMPATIBLE_FAILED_TITLE,
                strings.ROUTE_CATEGORY_MARK_COMPATIBLE_FAILED_BODY_FMT.format(count=failed_count),
            )
        if changed_count:
            toast(
                self.window,
                strings.ROUTE_CATEGORY_MARK_COMPATIBLE_SUCCESS_FMT.format(name=category, count=changed_count),
            )
            return
        if not failed_count:
            toast(
                self.window,
                strings.ROUTE_CATEGORY_MARK_COMPATIBLE_NOOP_FMT.format(name=category),
            )

    def open_route_file_location(self, category: str, name: str) -> None:
        path = self.window.route_mgr.route_file_path(category, name)
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(path)
            if sys.platform.startswith("win"):
                try:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                except OSError:
                    os.startfile(os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))):
                    raise OSError(path)
        except Exception:
            styled_info(
                self.window,
                strings.ROUTE_OPEN_FILE_LOCATION,
                strings.ROUTE_OPEN_FILE_LOCATION_FAILED.format(name=name),
            )

    def open_category_file_location(self, category: str) -> None:
        path = self.window.route_mgr.category_path(category)
        try:
            if not os.path.isdir(path):
                raise FileNotFoundError(path)
            if sys.platform.startswith("win"):
                os.startfile(path)
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                    raise OSError(path)
        except Exception:
            styled_info(
                self.window,
                strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION,
                strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION_FAILED.format(name=category),
            )

    def remove_tracked_route_widgets(self) -> None:
        while self.window.tracked_routes_grid.count():
            item = self.window.tracked_routes_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            checkbox = self.tracked_widget_checkbox(widget)
            if checkbox is not None:
                self.unregister_route_checkbox(self.route_checkbox_name(checkbox), checkbox)
            widget.deleteLater()

    def unregister_route_checkbox(self, route_id: str, checkbox: QCheckBox) -> None:
        widgets = self.window._route_checkboxes.get(route_id)
        if not widgets:
            return
        if checkbox in widgets:
            widgets.remove(checkbox)
        if not widgets:
            self.window._route_checkboxes.pop(route_id, None)

    def toggle_route(self, route_id: str, enabled: bool, source: QCheckBox) -> None:
        self.window.route_mgr.visibility[route_id] = enabled
        self.window.route_mgr.save_visibility()
        self.sync_route_checkboxes(route_id, enabled, source)
        self.refresh_tracked_routes()
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def set_category_routes_visibility(self, category: str, mode: str) -> None:
        route_widgets = self.window._route_widgets_by_category.get(category, [])
        changed_route_ids: list[str] = []

        for route_id, _route_name, _route_item in route_widgets:
            if not route_id:
                continue
            current = bool(self.window.route_mgr.visibility.get(route_id, False))
            if mode == "select_all":
                enabled = True
            elif mode == "invert":
                enabled = not current
            else:
                return
            if enabled == current:
                continue
            self.window.route_mgr.visibility[route_id] = enabled
            changed_route_ids.append(route_id)

        if not changed_route_ids:
            return

        self.window.route_mgr.save_visibility()
        for route_id in changed_route_ids:
            self.sync_route_checkboxes(
                route_id,
                bool(self.window.route_mgr.visibility.get(route_id, False)),
                None,
            )
        self.refresh_tracked_routes()
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def sync_route_checkboxes(self, route_id: str, enabled: bool, source: QCheckBox | None) -> None:
        for checkbox in list(self.window._route_checkboxes.get(route_id, [])):
            if checkbox is source:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
            checkbox.blockSignals(False)

    def refresh_tracked_routes(self) -> None:
        visible_routes = self.window.route_mgr.visible_routes()
        self.window.tracked_routes_title.setText(f"{strings.ROUTE_TRACKED_TITLE} ({len(visible_routes)})")
        self.remove_tracked_route_widgets()
        tracked_route_ids = [self.window.route_mgr.route_id(route) for route in visible_routes]
        has_any_progress = False

        if visible_routes:
            for index, route in enumerate(visible_routes):
                route_id = self.window.route_mgr.route_id(route)
                route_name = route.get("display_name", "")
                has_progress = self.window.route_mgr.has_progress(route_id)
                has_any_progress = has_any_progress or has_progress
                route_item = TrackedRouteItem(
                    route_id,
                    route_name,
                    self.window.route_mgr.visibility.get(route_id, False),
                    has_progress,
                )
                self.apply_route_checkbox_color(route_item.checkbox, route_id)
                route_item.checkbox.toggled.connect(
                    lambda enabled, known_route_id=route_id, source=route_item.checkbox: self.toggle_route(known_route_id, enabled, source)
                )
                route_item.reset_btn.clicked.connect(
                    lambda _checked=False, known_route_id=route_id: self.reset_route_progress(known_route_id)
                )
                route_item.jump_node_btn.clicked.connect(
                    lambda _checked=False, known_route_id=route_id: self.jump_to_route_node(known_route_id)
                )
                route_item.add_point_btn.clicked.connect(
                    lambda _checked=False, known_route_id=route_id, anchor=route_item.add_point_btn: (
                        self.show_current_position_add_menu(known_route_id, anchor)
                    )
                )
                self.window._route_checkboxes.setdefault(route_id, []).append(route_item.checkbox)
                row = index // 2
                column = index % 2
                self.window.tracked_routes_grid.addWidget(route_item, row, column)
        else:
            empty_label = QLabel(strings.ROUTE_EMPTY_TRACKED)
            empty_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            empty_label.setStyleSheet(f"font-size: 12px; color: {theme.FG_DIM};")
            self.window.tracked_routes_grid.addWidget(empty_label, 0, 0, 1, 2)

        clear_btn = getattr(self.window, "tracked_routes_clear_progress_btn", None)
        if clear_btn is not None:
            clear_btn.setVisible(has_any_progress)
        self.window._tracked_route_progress_signature = self.build_tracked_route_progress_signature(tracked_route_ids)
        self.window.tracked_routes_inner.adjustSize()
        self.sync_tracked_routes_height(len(visible_routes))
        self.window.window_mode_controller.schedule_layout_refresh()

    @staticmethod
    def tracked_widget_checkbox(widget: QWidget) -> QCheckBox | None:
        if isinstance(widget, QCheckBox):
            return widget
        checkbox = getattr(widget, "checkbox", None)
        return checkbox if isinstance(checkbox, QCheckBox) else None

    def build_tracked_route_progress_signature(
        self,
        route_ids: list[str] | None = None,
    ) -> tuple[tuple[str, bool], ...]:
        ids = route_ids if route_ids is not None else self.window.route_mgr.visible_route_ids()
        return tuple((route_id, self.window.route_mgr.has_progress(route_id)) for route_id in ids)

    def reset_route_progress(self, route_id: str) -> None:
        self.window.route_mgr.reset_progress(route_id)
        self.window.map_view._refresh_from_last_frame()
        self.refresh_tracked_routes()
        route_name = self.window.route_mgr.route_name_for_id(route_id) or route_id
        toast(self.window, f"已重置路线“{route_name}”进度")

    def reset_tracked_routes_progress(self) -> None:
        route_ids = self.window.route_mgr.visible_route_ids()
        if not route_ids:
            toast(self.window, strings.ROUTE_EMPTY_TRACKED)
            return

        reset_count = 0
        for route_id in route_ids:
            route = self.window.route_mgr.route_for_id(route_id)
            if route is None:
                continue
            changed = False
            for point in route.get("points", []):
                if point.get("visited", False):
                    point["visited"] = False
                    changed = True
            if changed:
                reset_count += 1

        if reset_count <= 0:
            toast(self.window, "当前追踪路线没有可重置的进度")
            return

        self.window.route_mgr.save_progress()
        self.window.map_view._refresh_from_last_frame()
        self.refresh_tracked_routes()
        toast(self.window, f"已重置 {reset_count} 条追踪路线的进度")

    @staticmethod
    def _route_point_xy(point: object) -> tuple[int, int] | None:
        if not isinstance(point, dict):
            return None
        try:
            return int(round(float(point["x"]))), int(round(float(point["y"])))
        except (KeyError, TypeError, ValueError):
            return None

    def _route_jump_target(self, route: dict, *, paused: bool, route_adapter=None) -> tuple[int, int, int, bool] | None:
        valid_points: list[tuple[int, int, int, dict]] = []
        for index, point in enumerate(route.get("points") or []):
            xy = self._route_point_xy(point)
            if xy is None:
                continue
            raw_x, raw_y = xy
            if route_adapter is not None:
                cx, cy = route_adapter.to_current(float(raw_x), float(raw_y))
                x, y = int(round(cx)), int(round(cy))
            else:
                x, y = raw_x, raw_y
            valid_points.append((index, x, y, point))
        if not valid_points:
            return None

        if paused:
            index, x, y, _point = valid_points[0]
            return index, x, y, False

        for index, x, y, point in valid_points:
            if not bool(point.get("visited", False)):
                return index, x, y, False

        index, x, y, _point = valid_points[0]
        return index, x, y, True

    def _is_paused_route_jump_mode(self) -> bool:
        mode = getattr(self.window, "_mode", None)
        mode_name = str(getattr(mode, "name", "") or "")
        mode_value = str(getattr(mode, "value", "") or "")
        return mode_name in {"PAUSED", "MAXIMIZED"} or mode_value in {"paused", "maximized"}

    def jump_to_route_node(self, route_id: str) -> None:
        if not self.confirm_exit_route_drawing():
            return
        route = self.window.route_mgr.route_for_id(route_id)
        if route is None:
            styled_info(
                self.window,
                strings.ROUTE_TRACKED_JUMP_EMPTY_TITLE,
                strings.ROUTE_TRACKED_JUMP_EMPTY_BODY,
            )
            return

        paused = self._is_paused_route_jump_mode()
        route_adapter = self._route_coordinate_adapter(route_id)
        target = self._route_jump_target(route, paused=paused, route_adapter=route_adapter)
        if target is None:
            styled_info(
                self.window,
                strings.ROUTE_TRACKED_JUMP_EMPTY_TITLE,
                strings.ROUTE_TRACKED_JUMP_EMPTY_BODY,
            )
            return

        point_index, display_x, display_y, completed = target

        if paused:
            raw_target = self._route_jump_target(route, paused=paused, route_adapter=None)
            if raw_target is not None:
                _raw_idx, raw_x, raw_y, _raw_completed = raw_target
                self.window.tracker.set_anchor(raw_x, raw_y)
                self.window._last_player_xy = (raw_x, raw_y)
                self.window.coord_label.setText(f"{raw_x} , {raw_y}")
                self.window.tracking_state.display_stable_xy = (raw_x, raw_y)
                self.window.tracking_state.display_pending_locked_xy = None
                self.window.tracking_state.display_pending_locked_count = 0
                self.window.tracking_state.display_needs_lock_confirmation = False
            from ui_island.state.tracking import TrackState
            self.window.map_view.preview_relocate(display_x, display_y, TrackState.SEARCHING)
        else:
            global_adapter = getattr(self.window.map_view, "coordinate_adapter", None)
            if callable(global_adapter):
                global_adapter = global_adapter()
            if global_adapter is not None:
                ix, iy = global_adapter.to_internal(float(display_x), float(display_y))
            else:
                ix, iy = float(display_x), float(display_y)
            self.window.map_view.focus_map_position(int(round(ix)), int(round(iy)))

        message = (
            strings.ROUTE_TRACKED_JUMP_COMPLETED_FMT
            if completed
            else strings.ROUTE_TRACKED_JUMP_TO_NODE_FMT
        )
        toast(self.window, message.format(index=point_index + 1))

    def current_route_id_by_player_position(self) -> str | None:
        player_xy = self._current_player_xy_or_warn(
            title="无法确定当前路线",
            body="当前没有可用定位，请等待定位稳定后再使用当前路线快捷键。",
        )
        if player_xy is None:
            return None

        paused = self._is_paused_route_jump_mode()
        best: tuple[float, str] | None = None
        for route in self.window.route_mgr.visible_routes():
            route_id = self.window.route_mgr.route_id(route)
            if not route_id:
                continue
            route_adapter = self._route_coordinate_adapter(route_id)
            target = self._route_jump_target(route, paused=paused, route_adapter=route_adapter)
            if target is None:
                continue
            _point_index, x, y, _completed = target
            distance = math.hypot(float(x) - float(player_xy[0]), float(y) - float(player_xy[1]))
            if best is None or distance < best[0]:
                best = (distance, route_id)

        if best is None:
            styled_info(
                self.window,
                strings.ROUTE_TRACKED_JUMP_EMPTY_TITLE,
                strings.ROUTE_TRACKED_JUMP_EMPTY_BODY,
            )
            return None
        return best[1]

    def jump_to_current_route_node(self) -> None:
        route_id = self.current_route_id_by_player_position()
        if route_id is not None:
            self.jump_to_route_node(route_id)

    def _current_player_xy_or_warn(
        self,
        *,
        title: str = "无法添加节点",
        body: str = "当前没有可用定位，请等待定位稳定后再添加。",
    ) -> tuple[int, int] | None:
        player_xy = getattr(self.window, "_last_player_xy", None)
        if player_xy is None:
            styled_info(
                self.window,
                title,
                body,
            )
            return

        try:
            x, y = int(player_xy[0]), int(player_xy[1])
        except (TypeError, ValueError, IndexError):
            styled_info(
                self.window,
                title,
                "当前定位坐标无效，请等待定位稳定后再使用。",
            )
            return

        return x, y

    def _current_position_add_menu_items(
        self,
        route_id: str,
        *,
        include_annotated: bool,
        show_shortcuts: bool,
    ) -> list[ContextMenuItem]:
        def label(text: str, shortcut: str) -> str:
            return f"{text} (按{shortcut})" if show_shortcuts else text

        items = [
            ContextMenuItem(
                label(strings.MAP_ADD_COLLECT_POINT_MENU_LABEL, "1"),
                lambda known_route_id=route_id: self.add_current_position_to_route(
                    known_route_id,
                    NODE_TYPE_COLLECT,
                ),
                shortcut="1" if show_shortcuts else "",
            ),
            ContextMenuItem(
                label(strings.MAP_ADD_TELEPORT_POINT_MENU_LABEL, "2"),
                lambda known_route_id=route_id: self.add_current_position_to_route(
                    known_route_id,
                    NODE_TYPE_TELEPORT,
                ),
                shortcut="2" if show_shortcuts else "",
            ),
            ContextMenuItem(
                label(strings.MAP_ADD_GUIDE_POINT_MENU_LABEL, "3"),
                lambda known_route_id=route_id: self.add_current_position_to_route(
                    known_route_id,
                    NODE_TYPE_VIRTUAL,
                ),
                shortcut="3" if show_shortcuts else "",
            ),
        ]
        if include_annotated:
            items.append(
                ContextMenuItem(
                    strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL,
                    lambda known_route_id=route_id: self.add_current_position_to_route(
                        known_route_id,
                        annotated=True,
                    ),
                )
            )
        return items

    def _show_current_position_add_menu_at(
        self,
        route_id: str,
        global_pos: QPoint,
        *,
        include_annotated: bool,
        show_shortcuts: bool,
    ) -> None:
        show_context_menu(
            self.window,
            global_pos,
            self._current_position_add_menu_items(
                route_id,
                include_annotated=include_annotated,
                show_shortcuts=show_shortcuts,
            ),
            object_name="RouteListContextMenu",
        )

    def show_current_position_add_menu(self, route_id: str, anchor: QWidget) -> None:
        if not self.confirm_exit_route_drawing():
            return
        try:
            global_pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        except Exception:
            global_pos = QPoint(0, 0)
        self._show_current_position_add_menu_at(
            route_id,
            global_pos,
            include_annotated=True,
            show_shortcuts=False,
        )

    def show_current_position_add_menu_for_current_route(self) -> None:
        if not self.confirm_exit_route_drawing():
            return
        route_id = self.current_route_id_by_player_position()
        if route_id is None:
            return
        self._show_current_position_add_menu_at(
            route_id,
            QCursor.pos(),
            include_annotated=False,
            show_shortcuts=True,
        )

    def add_current_position_to_route(
        self,
        route_id: str,
        node_type: object | None = None,
        *,
        annotated: bool = False,
    ) -> None:
        player_xy = self._current_player_xy_or_warn()
        if player_xy is None:
            return
        x, y = player_xy

        if annotated:
            self.window.map_interaction_controller.add_annotated_point_to_routes(
                x,
                y,
                route_ids=[route_id],
                show_dialog=False,
            )
            return

        if node_type is not None:
            self.window.map_interaction_controller.add_route_node_from_context_menu(
                x,
                y,
                node_type,
                route_ids=[route_id],
                show_dialog=False,
            )
            return

        self.window.map_interaction_controller.add_point_to_routes(
            x,
            y,
            route_ids=[route_id],
            show_dialog=False,
        )

    def toggle_tracked_routes_collapsed(self, _checked: bool = False) -> None:
        self.set_tracked_routes_collapsed(not bool(getattr(self.window, "tracked_routes_collapsed", False)))

    def set_tracked_routes_collapsed(self, collapsed: bool) -> None:
        self.window.tracked_routes_collapsed = bool(collapsed)
        button = getattr(self.window, "tracked_routes_toggle_btn", None)
        if button is not None:
            if collapsed:
                button.setText("▸")
                button.setToolTip("展开当前追踪路线")
            else:
                button.setText("▾")
                button.setToolTip("收起当前追踪路线")
        self.sync_tracked_routes_height(len(self.window.route_mgr.visible_routes()))
        self.window.window_mode_controller.schedule_layout_refresh()

    def sync_tracked_routes_height(self, item_count: int) -> None:
        fit_hint = getattr(self.window, "_fit_route_guide_hint_width", None)
        if callable(fit_hint):
            fit_hint()
        collapsed = bool(getattr(self.window, "tracked_routes_collapsed", False))
        if collapsed:
            self.window.tracked_routes_scroll.hide()
            self.window.tracked_routes_scroll.setFixedHeight(0)
            target_height = 0
        else:
            self.window.tracked_routes_scroll.show()
            rows = max(1, (max(1, item_count) + 1) // 2)
            spacing = self.window.tracked_routes_grid.verticalSpacing()
            content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
            target_height = min(theme.TRACKED_ROUTES_MAX_HEIGHT, content_height)
            self.window.tracked_routes_scroll.setFixedHeight(target_height)
        margins = self.window.tracked_routes_layout.contentsMargins()
        card_height = (
            margins.top()
            + self.window.tracked_routes_header.sizeHint().height()
            + (0 if collapsed else self.window.tracked_routes_layout.spacing())
            + target_height
            + margins.bottom()
        )
        self.window.tracked_routes_card.setMinimumHeight(card_height)
        self.window.tracked_routes_card.setMaximumHeight(card_height)

    def apply_route_filter(self) -> None:
        term = self.window.search_input.text().strip().casefold()
        has_search = bool(term)
        for category, section in self.window._route_sections.items():
            visible_count = 0
            for _route_id, route_name, route_item in self.window._route_widgets_by_category[category]:
                visible = self.matches_route(route_name, term)
                route_item.setVisible(visible)
                if visible:
                    visible_count += 1
            section.setVisible((not has_search) or visible_count > 0)
            section.set_force_open(has_search and visible_count > 0)

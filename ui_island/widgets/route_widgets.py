"""Reusable widgets for route list and status display."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from base import TrackState

from ..design import strings, tokens
from .factory import make_route_panel_icon_button, make_route_panel_line_edit


class StatusDot(QWidget):
    COLORS = {
        TrackState.LOCKED: tokens.DOT_LOCKED,
        TrackState.INERTIAL: tokens.DOT_INERTIAL,
        TrackState.LOST: tokens.DOT_LOST,
        TrackState.SEARCHING: tokens.DOT_SEARCHING,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = tokens.DOT_SEARCHING
        self.setFixedSize(10, 10)

    def set_state(self, state: TrackState) -> None:
        new_color = self.COLORS.get(state, tokens.DOT_SEARCHING)
        if new_color != self._color:
            self._color = new_color
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self._color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())


class RouteSection(QWidget):
    context_menu_requested = Signal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = False
        self._force_open = False
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QPushButton(self)
        self.header.setObjectName("SectionHeader")
        self.header.setProperty("compact", True)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.toggled.connect(self.set_expanded)
        header_button_layout = QHBoxLayout(self.header)
        header_button_layout.setContentsMargins(10, 0, 0, 0)
        header_button_layout.setSpacing(0)

        self.header_label = QLabel(self.header)
        self.header_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.header_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_button_layout.addWidget(self.header_label, stretch=1)

        self.select_all_btn = QPushButton("全选", self.header)
        self.select_all_btn.setObjectName("SectionHeaderBatchButton")
        self.select_all_btn.setProperty("compact", True)
        self.select_all_btn.setToolTip("选中当前分类所有路线")
        self.select_all_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.select_all_btn.setFixedWidth(42)
        header_button_layout.addWidget(self.select_all_btn)

        self.invert_select_btn = QPushButton("反选", self.header)
        self.invert_select_btn.setObjectName("SectionHeaderBatchButton")
        self.invert_select_btn.setProperty("compact", True)
        self.invert_select_btn.setToolTip("反转当前分类路线选中状态")
        self.invert_select_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.invert_select_btn.setFixedWidth(42)
        header_button_layout.addWidget(self.invert_select_btn)

        self.add_route_btn = QPushButton("+", self.header)
        self.add_route_btn.setObjectName("SectionHeaderAddButton")
        self.add_route_btn.setProperty("compact", True)
        self.add_route_btn.setProperty("iconRole", "add")
        self.add_route_btn.setToolTip("新建路线")
        self.add_route_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.add_route_btn.setFixedWidth(30)
        header_button_layout.addWidget(self.add_route_btn)

        layout.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("RouteSectionBody")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 0, 4)
        self.body_layout.setSpacing(4)
        self.body_layout.setSizeConstraint(QVBoxLayout.SetMinAndMaxSize)

        self.add_route_row = QWidget(self.body)
        self.add_route_row.setAttribute(Qt.WA_StyledBackground, True)
        self.add_route_row.hide()
        add_row_layout = QHBoxLayout(self.add_route_row)
        add_row_layout.setContentsMargins(0, 0, 0, 0)
        add_row_layout.setSpacing(6)

        self.add_route_input = make_route_panel_line_edit(
            placeholder="输入路线名称...",
            parent=self.add_route_row,
        )
        add_row_layout.addWidget(self.add_route_input, stretch=1)

        self.add_route_confirm_btn = make_route_panel_icon_button(
            "✓",
            role="confirm",
            tooltip="确认创建路线",
            parent=self.add_route_row,
        )
        add_row_layout.addWidget(self.add_route_confirm_btn)

        self.add_route_cancel_btn = make_route_panel_icon_button(
            "×",
            role="close",
            tooltip="取消新建路线",
            parent=self.add_route_row,
        )
        add_row_layout.addWidget(self.add_route_cancel_btn)

        self.body_layout.addWidget(self.add_route_row)

        layout.addWidget(self.body)
        for widget in (self.header, self.select_all_btn, self.invert_select_btn, self.add_route_btn):
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda pos, source=widget: self.context_menu_requested.emit(source.mapToGlobal(pos))
            )
        self._sync_state()

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._sync_state()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_force_open(self, force_open: bool) -> None:
        self._force_open = force_open
        self._sync_state()

    def is_force_open(self) -> bool:
        return self._force_open

    def show_add_route_row(self) -> None:
        if not self._expanded:
            self._expanded = True
        self.add_route_input.clear()
        self.add_route_input.setPlaceholderText("输入路线名称...")
        self.add_route_row.show()
        self._sync_state()
        self.add_route_input.setFocus()

    def hide_add_route_row(self) -> None:
        self.add_route_input.clear()
        self.add_route_input.setPlaceholderText("输入路线名称...")
        self.add_route_row.hide()

    def is_adding_route(self) -> bool:
        return self.add_route_row.isVisible()

    def current_add_route_name(self) -> str:
        return self.add_route_input.text().strip()

    def show_add_route_error(self, message: str) -> None:
        self.add_route_input.clear()
        self.add_route_input.setPlaceholderText(message)
        self.add_route_input.setFocus()

    def _sync_state(self) -> None:
        visible = self._expanded or self._force_open
        self.body.setVisible(visible)
        self.header.blockSignals(True)
        self.header.setChecked(self._expanded)
        self.header.setText("")
        self.header_label.setText(f"{'▾' if visible else '▸'} {self._title}")
        self.header.blockSignals(False)


class ElidedCheckBox(QCheckBox):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setToolTip(text)
        self._refresh_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elided_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elided_text()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _refresh_elided_text(self) -> None:
        metrics = QFontMetrics(self.font())
        available_width = max(60, self.width() - 24)
        super().setText(metrics.elidedText(self._full_text, Qt.ElideRight, available_width))


class RouteListItem(QWidget):
    context_menu_requested = Signal(object)

    def __init__(self, category: str, route_id: str, route_name: str, checked: bool, parent=None):
        super().__init__(parent)
        self.category = category
        self.route_id = route_id
        self.route_name = route_name
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_row = QWidget(self)
        self.display_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.display_row.setMinimumWidth(0)
        display_layout = QHBoxLayout(self.display_row)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(6)

        self.checkbox = QCheckBox(route_name, self.display_row)
        self.checkbox.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
        self.checkbox.setChecked(checked)
        self.checkbox.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.checkbox.setMinimumWidth(0)
        self.checkbox.setProperty("routeId", route_id)
        self.checkbox.setToolTip(route_name)
        display_layout.addWidget(self.checkbox, stretch=1)

        self.edit_row = QWidget(self)
        self.edit_row.hide()
        self.edit_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.edit_row.setMinimumWidth(0)
        edit_layout = QHBoxLayout(self.edit_row)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(6)

        self.rename_input = make_route_panel_line_edit(
            placeholder=strings.ROUTE_RENAME_PLACEHOLDER,
            parent=self.edit_row,
            size_policy=(QSizePolicy.Ignored, QSizePolicy.Fixed),
        )
        self.rename_input.setMinimumWidth(0)
        edit_layout.addWidget(self.rename_input, stretch=1)

        self.rename_confirm_btn = make_route_panel_icon_button(
            "✓",
            role="confirm",
            tooltip=strings.ROUTE_RENAME_CONFIRM,
            parent=self.edit_row,
        )
        edit_layout.addWidget(self.rename_confirm_btn)

        self.rename_cancel_btn = make_route_panel_icon_button(
            "×",
            role="close",
            tooltip=strings.ROUTE_RENAME_CANCEL,
            parent=self.edit_row,
        )
        edit_layout.addWidget(self.rename_cancel_btn)

        layout.addWidget(self.display_row)
        layout.addWidget(self.edit_row)

        for widget in (self, self.display_row, self.checkbox):
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda pos, source=widget: self.context_menu_requested.emit(source.mapToGlobal(pos))
            )

    def start_rename(self) -> None:
        self.display_row.hide()
        self.edit_row.show()
        self.rename_input.setText(self.route_name)
        self.rename_input.selectAll()
        self.rename_input.setFocus()

    def cancel_rename(self) -> None:
        self.edit_row.hide()
        self.display_row.show()
        self.rename_input.clear()
        self.rename_input.setPlaceholderText(strings.ROUTE_RENAME_PLACEHOLDER)

    def is_renaming(self) -> bool:
        return self.edit_row.isVisible()

    def current_rename_value(self) -> str:
        return self.rename_input.text().strip()

    def show_rename_error(self, message: str) -> None:
        self.rename_input.clear()
        self.rename_input.setPlaceholderText(message)
        self.rename_input.setFocus()

    def update_route_name(self, route_name: str) -> None:
        self.route_name = route_name
        self.rename_input.setText(route_name)
        self._refresh_display_name()
        self.setToolTip(self.route_name)
        self.display_row.setToolTip(self.route_name)
        self.checkbox.setToolTip(self.route_name)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_display_name()

    def _refresh_display_name(self) -> None:
        metrics = QFontMetrics(self.checkbox.font())
        available_width = max(60, self.checkbox.width() - 28)
        display_name = metrics.elidedText(self.route_name, Qt.ElideRight, available_width)
        self.checkbox.setText(display_name)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class TrackedRouteItem(QWidget):
    def __init__(self, route_id: str, route_name: str, checked: bool, has_progress: bool, parent=None):
        super().__init__(parent)
        self.route_id = route_id
        self.route_name = route_name
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("trackedRouteItem", True)
        self.setProperty("checked", checked)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.checkbox = ElidedCheckBox(route_name, self)
        self.checkbox.setMinimumHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
        self.checkbox.setChecked(checked)
        self.checkbox.setProperty("routeId", route_id)
        self.checkbox.toggled.connect(self._sync_checked_state)
        layout.addWidget(self.checkbox, stretch=1)

        self.reset_btn = QPushButton("重置进度", self)
        self.reset_btn.setObjectName("TrackedRoutesToggleButton")
        self.reset_btn.setToolTip("从第一个节点重新开始当前路线")
        self.reset_btn.setVisible(has_progress)
        layout.addWidget(self.reset_btn, alignment=Qt.AlignVCenter)

        self.jump_node_btn = QPushButton("🚩", self)
        self.jump_node_btn.setProperty("trackedRouteAddButton", True)
        self.jump_node_btn.setToolTip(strings.ROUTE_TRACKED_JUMP_NODE_TOOLTIP)
        self.jump_node_btn.setFixedWidth(26)
        layout.addWidget(self.jump_node_btn, alignment=Qt.AlignVCenter)

        self.add_point_btn = QPushButton("⨁", self)
        self.add_point_btn.setProperty("trackedRouteAddButton", True)
        self.add_point_btn.setToolTip("将当前位置加入此路线")
        self.add_point_btn.setFixedWidth(26)
        layout.addWidget(self.add_point_btn, alignment=Qt.AlignVCenter)

    def _sync_checked_state(self, checked: bool) -> None:
        self.setProperty("checked", checked)
        self.style().unpolish(self)
        self.style().polish(self)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

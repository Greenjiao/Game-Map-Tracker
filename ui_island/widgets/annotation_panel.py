"""Popup panel for selecting 17173 annotation types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..design import strings, theme
from ..services.annotation_preferences import normalize_type_ids
from .annotation_type_widgets import AnnotationGroupSection, build_annotation_type_button, group_annotation_types
from .context_menu import ContextMenuItem, show_context_menu
from .factory import make_scroll_area


class AnnotationPanel(QFrame):
    selection_changed = Signal(list)
    plan_route_requested = Signal(str, str)
    panel_hidden = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AnnotationPanel")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(theme.ISLAND_QSS)
        self._types: list[dict] = []
        self._selected_type_ids: list[str] = []
        self._group_expanded: dict[str, bool] = {}
        self._group_expanded_changed: Callable[[dict[str, bool]], None] | None = None
        self._dragging = False
        self._drag_offset = None
        self._drag_handles: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._surface = QFrame()
        self._surface.setObjectName("AnnotationPanelSurface")
        outer.addWidget(self._surface)

        root = QVBoxLayout(self._surface)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        self._header = QWidget()
        self._header.setObjectName("AnnotationPanelHeader")
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("标注")
        self._title.setObjectName("AnnotationPanelTitle")
        header.addWidget(self._title)
        self._hint = QLabel()
        self._hint.setObjectName("AnnotationPanelHint")
        self._hint.setWordWrap(True)
        self._hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._set_hint_compact(False)
        header.addWidget(self._hint, stretch=1)
        self._show_all_btn = QPushButton("全显")
        self._show_all_btn.setObjectName("AnnotationPanelBulkButton")
        self._show_all_btn.clicked.connect(self._select_all_types)
        header.addWidget(self._show_all_btn)
        self._hide_all_btn = QPushButton("全隐")
        self._hide_all_btn.setObjectName("AnnotationPanelBulkButton")
        self._hide_all_btn.clicked.connect(self._clear_all_types)
        header.addWidget(self._hide_all_btn)
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("AnnotationPanelClose")
        self._close_btn.setToolTip("关闭")
        self._close_btn.clicked.connect(self.hide)
        header.addWidget(self._close_btn)
        root.addWidget(self._header)
        self._install_drag_handle(self._header)
        self._install_drag_handle(self._title)

        self._message = QLabel("")
        self._message.setObjectName("AnnotationPanelMessage")
        self._message.setWordWrap(True)
        root.addWidget(self._message)

        self._scroll = make_scroll_area(
            object_name="AnnotationPanelScroll",
            max_height=theme.ANNOTATION_PANEL_SCROLL_HEIGHT,
        )
        self._inner = QWidget()
        self._inner.setObjectName("AnnotationPanelInner")
        self._list_layout = QVBoxLayout(self._inner)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll)

    def load_index(self, path: str | Path) -> None:
        index_path = Path(path)
        if not index_path.exists():
            self._types = []
            self._message.setText("未找到点位索引，请先运行 python tools/fetch_17173_all_points.py")
            self._render()
            return
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            self._types = []
            self._message.setText("点位索引读取失败，请重新生成 tools/points_all/points.json")
            self._render()
            return
        types = payload.get("types") if isinstance(payload, dict) else None
        self._types = types if isinstance(types, list) else []
        self._message.setText("")
        self._render()

    def set_preferences(self, selected_type_ids: list[str]) -> None:
        self._selected_type_ids = normalize_type_ids(selected_type_ids)
        self._render()

    def set_group_expanded_state(
        self,
        group_expanded: dict[str, bool],
        on_changed: Callable[[dict[str, bool]], None] | None = None,
    ) -> None:
        self._group_expanded = group_expanded if isinstance(group_expanded, dict) else {}
        self._group_expanded_changed = on_changed
        self._render()

    def sync_group_expanded_state(
        self,
        group_expanded: dict[str, bool],
        on_changed: Callable[[dict[str, bool]], None] | None = None,
    ) -> None:
        self._group_expanded = group_expanded if isinstance(group_expanded, dict) else {}
        self._group_expanded_changed = on_changed
        self._sync_group_expanded_sections()

    def _render(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._title.setText("标注")
        self._show_all_btn.setVisible(bool(self._types))
        self._hide_all_btn.setVisible(bool(self._types))
        self._scroll.setVisible(bool(self._types))
        if not self._types:
            self._message.setVisible(True)
            return
        self._message.setVisible(False)
        selected = set(self._selected_type_ids)
        self._render_layered_types(selected)
        self._list_layout.addStretch(1)
        self._fit_scroll_height_to_content()

    def _visible_types(self) -> list[dict]:
        return sorted(self._types, key=lambda item: str(item.get("type") or item.get("typeId") or ""))

    def _render_layered_types(self, selected: set[str]) -> None:
        pulled_section = AnnotationGroupSection(
            "标注",
            self._group_expanded.get("标注", True),
            columns=1,
            annotation_layer="pulled",
            parent=self._inner,
        )
        pulled_section.expanded_changed.connect(self._set_group_expanded)
        self._add_grouped_type_sections(pulled_section, selected)
        self._list_layout.addWidget(pulled_section)

        custom_section = AnnotationGroupSection(
            "标注方案预设",
            self._group_expanded.get("标注方案预设", True),
            columns=1,
            annotation_layer="custom",
            parent=self._inner,
        )
        custom_section.expanded_changed.connect(self._set_group_expanded)
        self._list_layout.addWidget(custom_section)

    def _add_grouped_type_sections(self, parent_section: AnnotationGroupSection, selected: set[str]) -> None:
        for index, (group_name, group_items) in enumerate(group_annotation_types(self._visible_types())):
            section = self._build_group_section(group_name, group_items, selected, parent_section.body)
            parent_section.add_row(section, index)

    def _build_group_section(
        self,
        group_name: str,
        group_items: list[dict],
        selected: set[str],
        parent: QWidget,
    ) -> AnnotationGroupSection:
        section = AnnotationGroupSection(group_name, self._group_expanded.get(group_name, True), parent=parent)
        section.expanded_changed.connect(self._set_group_expanded)
        for index, item in enumerate(group_items):
            row = self._build_row(item, selected)
            if row is not None:
                section.add_row(row, index)
        return section

    def _set_group_expanded(self, group_name: str, expanded: bool) -> None:
        self._group_expanded[group_name] = bool(expanded)
        self._sync_group_expanded_sections(group_name)
        if self._group_expanded_changed is not None:
            self._group_expanded_changed(self._group_expanded)

    def _sync_group_expanded_sections(self, group_name: str | None = None) -> None:
        for section in self.findChildren(AnnotationGroupSection):
            if group_name is not None and section.group_name != group_name:
                continue
            expanded = self._group_expanded.get(section.group_name, True)
            if section.is_expanded() != bool(expanded):
                section.blockSignals(True)
                section.set_expanded(expanded)
                section.blockSignals(False)
        self._fit_scroll_height_to_content()

    def _fit_scroll_height_to_content(self) -> None:
        if self._scroll.isHidden():
            return
        self._list_layout.activate()
        self._inner.updateGeometry()
        content_height = max(1, self._inner.sizeHint().height())
        target_height = min(content_height, theme.ANNOTATION_PANEL_SCROLL_HEIGHT)
        self._scroll.setMinimumHeight(target_height)
        self._scroll.setMaximumHeight(theme.ANNOTATION_PANEL_SCROLL_HEIGHT)
        self._scroll.updateGeometry()
        if self.isVisible():
            self.adjustSize()

    def _build_row(self, item: dict, selected: set[str]) -> QPushButton | None:
        type_id = str(item.get("typeId") or "")
        if not type_id:
            return None
        type_name = str(item.get("type") or type_id)
        row = build_annotation_type_button(
            item,
            selected=type_id in selected,
            fade_icon=True,
            strike_out=True,
            icon_size=None,
        )
        row.clicked.connect(lambda _checked=False, tid=type_id: self._toggle_type(tid))
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, source=row, tid=type_id, name=type_name: self._show_type_context_menu(
                tid,
                name,
                source.mapToGlobal(pos),
            )
        )
        return row

    def _show_type_context_menu(self, type_id: str, type_name: str, global_pos) -> None:
        show_context_menu(
            self,
            global_pos,
            [
                ContextMenuItem(
                    strings.ANNOTATION_PLAN_ROUTE,
                    lambda: self.plan_route_requested.emit(type_id, type_name),
                )
            ],
            object_name="AnnotationContextMenu",
        )

    def _toggle_type(self, type_id: str) -> None:
        selected = normalize_type_ids(self._selected_type_ids)
        if type_id in selected:
            selected = [item for item in selected if item != type_id]
        else:
            selected.append(type_id)
        self._selected_type_ids = selected
        self._render()
        self.selection_changed.emit(selected)

    def _select_all_types(self) -> None:
        self._selected_type_ids = normalize_type_ids([item.get("typeId") for item in self._types])
        self._render()
        self.selection_changed.emit(self._selected_type_ids)

    def _clear_all_types(self) -> None:
        self._selected_type_ids = []
        self._render()
        self.selection_changed.emit(self._selected_type_ids)

    def set_compact_hint(self, compact: bool) -> None:
        self._set_hint_compact(compact)

    def _set_hint_compact(self, compact: bool) -> None:
        if compact:
            self._hint.setTextFormat(Qt.PlainText)
            self._hint.setOpenExternalLinks(False)
            self._hint.setTextInteractionFlags(Qt.NoTextInteraction)
            self._hint.setText(strings.ANNOTATION_ROUTE_HINT_COMPACT)
        else:
            self._hint.setTextFormat(Qt.RichText)
            self._hint.setOpenExternalLinks(True)
            self._hint.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
            self._hint.setText(strings.annotation_route_hint_html())
        self._hint.setToolTip(strings.ANNOTATION_ROUTE_HINT)

    def _install_drag_handle(self, widget: QWidget) -> None:
        self._drag_handles.append(widget)
        widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drag_handles:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
                return True
            if event.type() == QEvent.MouseMove and self._dragging and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._dragging = False
                self._drag_offset = None
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def hideEvent(self, event) -> None:
        self._dragging = False
        self._drag_offset = None
        self.panel_hidden.emit()
        super().hideEvent(event)

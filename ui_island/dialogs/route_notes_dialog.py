"""Dialog for viewing and editing route notes, color, and node summary."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QGraphicsOpacityEffect,
    QSlider,
    QSizeGrip,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import config
from ui_island.services import resource_metadata
from ui_island.services.route_manager import (
    NODE_TYPE_COLLECT,
    NODE_TYPE_TELEPORT,
    NODE_TYPE_VIRTUAL,
    NODE_TYPES,
    apply_route_node_auto_labels as apply_service_route_node_auto_labels,
    is_auto_route_node_label as service_is_auto_route_node_label,
    route_node_auto_label as service_route_node_auto_label,
)

from .base import StyledDialogBase, center_dialog
from .color_picker import open_styled_color_picker
from .annotation_type_picker import open_annotation_type_picker
from ..design import strings
from ..widgets.context_menu import ContextMenuItem, show_context_menu
from ..widgets.annotation_type_widgets import annotation_icon_path
from ..widgets.factory import make_compact_slider, make_route_panel_line_edit, make_scroll_area

_NODE_ICON_SIZE = 22
_NODE_NAME_MIN_WIDTH = 80
_NODE_DRAG_PREVIEW_MIN_WIDTH = 200
_STAT_COLUMNS = 3
_TITLE_ROW_HEIGHT = 26
_NODE_PANEL_SPACING = 8
_NODE_SCROLL_MIN_HEIGHT = 220
_STATS_SCROLL_DEFAULT_HEIGHT = 72
_STATS_SCROLL_MAX_HEIGHT = 150
_ROUTE_NOTES_DIALOG_MIN_WIDTH = 640
_ROUTE_NOTES_DIALOG_MAX_WIDTH = 1280
_ROUTE_NOTES_DIALOG_INITIAL_WIDTH = 680
_ROUTE_NOTES_DIALOG_INITIAL_HEIGHT = 460
_ROUTE_NOTES_LEFT_MIN_WIDTH = 300
_ROUTE_NOTES_RIGHT_MIN_WIDTH = 200
_ROUTE_NOTES_NODE_PANEL_MAX_WIDTH = _ROUTE_NOTES_DIALOG_MAX_WIDTH - _ROUTE_NOTES_LEFT_MIN_WIDTH
_ROUTE_NOTES_MIN_OPACITY_PERCENT = 35
_ROUTE_NOTES_DEFAULT_OPACITY_PERCENT = 100
_ROUTE_NOTES_OPACITY_SLIDER_MIN_WIDTH = 88
_ROUTE_NOTES_OPACITY_SLIDER_MAX_WIDTH = 112
_ROUTE_NOTES_LAYOUT_SAVE_DELAY_MS = 300
_COLOR_BUTTON_TEXT = "当前路线颜色"
_COLOR_BUTTON_WIDTH = 96


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _route_notes_config_int(key: str, default: int, minimum: int, maximum: int) -> int:
    value = getattr(config, key, None)
    if value is None:
        value = getattr(config, "settings", {}).get(key, default)
    return _clamp_int(value, default, minimum, maximum)


def normalize_color_hex(value: object) -> str | None:
    color = QColor(str(value or "").strip())
    if not color.isValid():
        return None
    return color.name(QColor.HexRgb)


def route_color_to_hex(route_color: tuple[int, int, int]) -> str:
    try:
        b, g, r = [max(0, min(255, int(channel))) for channel in route_color]
    except (TypeError, ValueError):
        return "#1ad1ff"
    return QColor(r, g, b).name(QColor.HexRgb)


def route_node_display_name(point: dict, index: int) -> str:
    label = str(point.get("label") or "").strip() if isinstance(point, dict) else ""
    return label or route_node_auto_label(point, index)


def route_node_display_names(points: list[dict]) -> list[str]:
    labeled = apply_route_node_auto_labels(points)
    return [route_node_display_name(point, index) for index, point in enumerate(labeled)]


def normalize_route_node_type(point: dict) -> str:
    value = str(point.get("node_type") or NODE_TYPE_COLLECT).strip().casefold() if isinstance(point, dict) else ""
    return value if value in NODE_TYPES else NODE_TYPE_COLLECT


def route_node_annotation(point: dict) -> tuple[str, str] | None:
    if not isinstance(point, dict):
        return None
    type_id = str(point.get("typeId") or "").strip()
    type_name = str(point.get("type") or "").strip()
    if not type_id and not type_name:
        return None
    return type_id or type_name, type_name or type_id


def route_node_auto_label(point: dict, fallback_index: int, type_counts: dict[str, int] | None = None) -> str:
    return service_route_node_auto_label(point, fallback_index, type_counts)


def is_auto_route_node_label(value: object) -> bool:
    return service_is_auto_route_node_label(value)


def apply_route_node_auto_labels(points: list[dict]) -> list[dict]:
    return apply_service_route_node_auto_labels(points, copy=True)


def summarize_route_nodes(points: list[dict]) -> dict:
    node_counts = {
        NODE_TYPE_COLLECT: 0,
        NODE_TYPE_TELEPORT: 0,
        NODE_TYPE_VIRTUAL: 0,
    }
    annotations: list[dict] = []
    annotation_indexes: dict[str, int] = {}

    for point in points:
        node_type = normalize_route_node_type(point)
        node_counts[node_type] = node_counts.get(node_type, 0) + 1

        annotation = route_node_annotation(point)
        if annotation is None:
            continue
        annotation_key, annotation_label = annotation
        if annotation_key not in annotation_indexes:
            annotation_indexes[annotation_key] = len(annotations)
            annotations.append({
                "key": annotation_key,
                "label": annotation_label,
                "count": 0,
            })
        annotations[annotation_indexes[annotation_key]]["count"] += 1

    return {
        "node_counts": node_counts,
        "annotations": annotations,
    }


def route_node_icon_pixmap(point: dict, route_color_hex: str, size: int = _NODE_ICON_SIZE) -> tuple[QPixmap, bool]:
    icon_path = str(point.get("icon_path") or "").strip() if isinstance(point, dict) else ""
    if icon_path and Path(icon_path).exists():
        icon = QIcon(icon_path)
        pixmap = icon.pixmap(size, size)
        if not pixmap.isNull():
            return pixmap, False

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor(route_color_hex)
    painter.setBrush(color)
    painter.setPen(QPen(QColor(255, 255, 255, 190), 1))
    margin = 3
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.end()
    return pixmap, True


def _persistable_route_node(point: dict) -> dict:
    copied = dict(point)
    copied.pop("icon_path", None)
    return copied


class RouteEnableVersionsDialog(StyledDialogBase):
    def __init__(
        self,
        parent,
        options: list[str],
        selected_versions: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> None:
        super().__init__(parent, "兼容版本", min_width=420, max_width=520)
        self._selected: list[str] | None = None
        self._checkboxes: list[QCheckBox] = []
        selected = set(resource_metadata.normalize_enable_versions(selected_versions))
        clean_options = resource_metadata.normalize_enable_versions(options)

        if not clean_options:
            empty = QLabel("暂无可用兼容版本")
            empty.setObjectName("DimLabel")
            empty.setWordWrap(True)
            self.shell_layout.addWidget(empty)
        else:
            scroll = make_scroll_area(
                object_name="RouteEnableVersionsScroll",
                horizontal_policy=Qt.ScrollBarAlwaysOff,
                min_height=120,
                max_height=260,
            )
            host = QWidget()
            host.setObjectName("AnnotationPanelInner")
            layout = QVBoxLayout(host)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(6)
            for version in clean_options:
                checkbox = QCheckBox(version, host)
                checkbox.setObjectName("RouteEnableVersionCheckBox")
                checkbox.setChecked(version in selected)
                checkbox.setToolTip(version)
                layout.addWidget(checkbox)
                self._checkboxes.append(checkbox)
            layout.addStretch(1)
            scroll.setWidget(host)
            self.shell_layout.addWidget(scroll, stretch=1)

        self.add_action_row(confirm_text="确定", cancel_text=strings.ROUTE_NOTES_CANCEL, on_confirm=self._save)
        self.adjustSize()

    def _save(self) -> None:
        self._selected = resource_metadata.normalize_enable_versions(
            checkbox.text() for checkbox in self._checkboxes if checkbox.isChecked()
        )
        self.accept()

    def selected_versions(self) -> list[str] | None:
        return list(self._selected) if self._selected is not None else None


def open_route_enable_versions_dialog(
    parent,
    options: list[str],
    selected_versions: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str] | None:
    dialog = RouteEnableVersionsDialog(parent, options, selected_versions)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_versions()
    return None


class RouteNodeStatsPanel(QWidget):
    def __init__(self, parent=None, *, include_title: bool = True) -> None:
        super().__init__(parent)
        self._nodes: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_NODE_PANEL_SPACING)

        if include_title:
            stats_title = QLabel(strings.ROUTE_NOTES_STATS_TITLE)
            stats_title.setObjectName("FieldLabel")
            stats_title.setFixedHeight(_TITLE_ROW_HEIGHT)
            stats_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(stats_title)

        self._stats_scroll = make_scroll_area(
            object_name="RouteNotesStatsScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            vertical_policy=Qt.ScrollBarAsNeeded,
        )
        layout.addWidget(self._stats_scroll)
        self.set_nodes([])

    def set_nodes(self, nodes: list[dict]) -> None:
        self._nodes = [dict(point) for point in nodes if isinstance(point, dict)]
        self._refresh_stats_section()

    def _refresh_stats_section(self) -> None:
        stats = QFrame(self)
        stats.setObjectName("RouteNotesStatsPanel")
        stats_layout = QGridLayout(stats)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setHorizontalSpacing(6)
        stats_layout.setVerticalSpacing(6)
        summary = summarize_route_nodes(self._nodes)
        stat_items = [
            (strings.ROUTE_NOTES_NODE_COLLECT, summary["node_counts"].get(NODE_TYPE_COLLECT, 0)),
            (strings.ROUTE_NOTES_NODE_TELEPORT, summary["node_counts"].get(NODE_TYPE_TELEPORT, 0)),
            (strings.ROUTE_NOTES_NODE_GUIDE, summary["node_counts"].get(NODE_TYPE_VIRTUAL, 0)),
        ]
        stat_items.extend((item["label"], item["count"]) for item in summary["annotations"])
        for index, (label, count) in enumerate(stat_items):
            chip = QLabel(f"{label} {count}")
            chip.setObjectName("RouteNotesStatChip")
            chip.setToolTip(f"{label}: {count}")
            stats_layout.addWidget(chip, index // _STAT_COLUMNS, index % _STAT_COLUMNS)

        scroll_height = max(_STATS_SCROLL_DEFAULT_HEIGHT, min(_STATS_SCROLL_MAX_HEIGHT, stats.sizeHint().height()))
        self._stats_scroll.setMinimumHeight(scroll_height)
        self._stats_scroll.setMaximumHeight(scroll_height)
        self._stats_scroll.setWidget(stats)


class RouteNodeEditorPanel(QWidget):
    nodes_changed = Signal()
    node_label_changed = Signal(int, object, object)
    node_label_edit_committed = Signal(int, object, object)
    node_annotation_changed = Signal(int, object, object)
    node_order_changed = Signal(int, int)

    def __init__(
        self,
        parent=None,
        *,
        route_color_hex: str = "#1ad1ff",
        annotation_items_provider=None,
        annotation_icon_path_provider=None,
        include_stats: bool = True,
        include_title: bool = True,
        annotation_picker_placement: str = "center",
        annotation_picker_anchor=None,
    ) -> None:
        super().__init__(parent)
        self._route_color_hex = normalize_color_hex(route_color_hex) or "#1ad1ff"
        self._annotation_items_provider = annotation_items_provider
        self._annotation_icon_path_provider = annotation_icon_path_provider
        self._annotation_picker_placement = str(annotation_picker_placement or "center")
        self._annotation_picker_anchor = annotation_picker_anchor
        self._nodes: list[dict] = []
        self._node_rows: list[QWidget] = []
        self._drag_candidate: dict | None = None
        self._drag_preview: QWidget | None = None
        self._drop_indicator: QFrame | None = None
        self._drop_target_index: int | None = None
        self._drag_row_effect: QGraphicsOpacityEffect | None = None
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_NODE_PANEL_SPACING)
        layout.setAlignment(Qt.AlignTop)

        self._stats_panel = None
        if include_stats:
            self._stats_panel = RouteNodeStatsPanel(self)
            layout.addWidget(self._stats_panel)

        if include_title:
            nodes_title = QLabel(strings.ROUTE_NOTES_NODE_LIST)
            nodes_title.setObjectName("FieldLabel")
            nodes_title.setFixedHeight(_TITLE_ROW_HEIGHT)
            nodes_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(nodes_title)

        self._nodes_scroll = make_scroll_area(
            object_name="RouteNotesNodeScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            min_height=_NODE_SCROLL_MIN_HEIGHT,
            size_policy=(QSizePolicy.Expanding, QSizePolicy.Expanding),
        )
        layout.addWidget(self._nodes_scroll, stretch=1)
        self._refresh_after_node_change(emit=False)

    def set_annotation_items_provider(self, provider) -> None:
        self._annotation_items_provider = provider

    def set_annotation_icon_path_provider(self, provider) -> None:
        self._annotation_icon_path_provider = provider

    def set_annotation_picker_placement(self, placement: str = "center", anchor=None) -> None:
        self._annotation_picker_placement = str(placement or "center")
        self._annotation_picker_anchor = anchor

    def set_route_color_hex(self, route_color_hex: str) -> None:
        normalized = normalize_color_hex(route_color_hex) or "#1ad1ff"
        if normalized == self._route_color_hex:
            return
        self._route_color_hex = normalized
        self._refresh_node_rows()

    def set_nodes(self, nodes: list[dict], refresh: bool = True) -> None:
        self._syncing = True
        try:
            self._nodes = [self._node_with_icon_path(point) for point in nodes if isinstance(point, dict)]
            self._cleanup_node_drag()
            if refresh:
                self._refresh_after_node_change(emit=False)
        finally:
            self._syncing = False

    def nodes(self) -> list[dict]:
        return apply_route_node_auto_labels([_persistable_route_node(point) for point in self._nodes])

    def draft_nodes(self) -> list[dict]:
        return [_persistable_route_node(point) for point in self._nodes]

    def _node_with_icon_path(self, point: dict) -> dict:
        copied = dict(point)
        type_id = str(copied.get("typeId") or "").strip()
        if not type_id or copied.get("icon_path") or not callable(self._annotation_icon_path_provider):
            return copied
        try:
            icon_path = str(self._annotation_icon_path_provider(type_id) or "").strip()
        except Exception:
            icon_path = ""
        if icon_path:
            copied["icon_path"] = icon_path
        return copied

    def _emit_nodes_changed(self) -> None:
        if not self._syncing:
            self.nodes_changed.emit()

    def _refresh_stats_section(self) -> None:
        if self._stats_panel is not None:
            self._stats_panel.set_nodes(self._nodes)

    def _refresh_node_rows(self) -> None:
        scroll_value = 0
        if hasattr(self, "_nodes_scroll"):
            scroll_value = self._nodes_scroll.verticalScrollBar().value()

        host = QWidget()
        host.setObjectName("AnnotationPanelInner")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(2, 2, 2, 2)
        host_layout.setSpacing(6)
        self._node_rows = []
        if not self._nodes:
            empty = QLabel(strings.ROUTE_NOTES_NODE_EMPTY)
            empty.setObjectName("DimLabel")
            empty.setWordWrap(True)
            host_layout.addWidget(empty)
        else:
            display_names = route_node_display_names(self._nodes)
            for index, point in enumerate(self._nodes):
                row = self._build_node_row(point, index, display_names[index])
                self._node_rows.append(row)
                host_layout.addWidget(row)
        host_layout.addStretch(1)
        self._nodes_scroll.setWidget(host)
        self._nodes_scroll.verticalScrollBar().setValue(scroll_value)
        self._drop_indicator = QFrame(host)
        self._drop_indicator.setObjectName("RouteNotesDropIndicator")
        self._drop_indicator.setFixedHeight(3)
        self._drop_indicator.hide()

    def _build_node_row(self, point: dict, index: int, display_name: str) -> QWidget:
        row = QWidget()
        row.setObjectName("RouteNotesNodeRow")
        row.setProperty("routeNotesDragIndex", index)
        row.installEventFilter(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(6)

        icon_button = QPushButton(row)
        icon_button.setObjectName("RouteNotesNodeIcon")
        icon_button.setFixedSize(26, 26)
        icon_button.setIconSize(QSize(_NODE_ICON_SIZE, _NODE_ICON_SIZE))
        pixmap, fallback = route_node_icon_pixmap(point, self._route_color_hex)
        icon_button.setIcon(QIcon(pixmap))
        icon_button.setProperty("fallbackIcon", fallback)
        icon_button.setProperty("routeNotesDragIndex", index)
        icon_button.setToolTip(self._node_annotation_tooltip(point))
        icon_button.clicked.connect(lambda _checked=False, known_index=index: self._change_node_annotation(known_index))
        icon_button.installEventFilter(self)
        row_layout.addWidget(icon_button)

        name_input = make_route_panel_line_edit(
            placeholder=display_name,
            parent=row,
            size_policy=(QSizePolicy.Ignored, QSizePolicy.Fixed),
        )
        name_input.setObjectName("RouteNotesNodeName")
        name_input.setMinimumWidth(_NODE_NAME_MIN_WIDTH)
        name_input.setProperty("routeNotesDragIndex", index)
        current_label = str(point.get("label") or "").strip()
        name_input.setText(display_name if not current_label or is_auto_route_node_label(current_label) else current_label)
        name_input.setToolTip(display_name)
        name_input.setProperty("routeNotesLabelBefore", point.get("label", None))
        name_input.setContextMenuPolicy(Qt.CustomContextMenu)
        name_input.customContextMenuRequested.connect(
            lambda pos, editor=name_input: self._show_name_context_menu(editor, pos)
        )
        name_input.textChanged.connect(lambda text, known_index=index: self._set_node_label(known_index, text))
        name_input.editingFinished.connect(
            lambda editor=name_input, known_index=index: self._commit_node_label(known_index, editor)
        )
        name_input.installEventFilter(self)
        row_layout.addWidget(name_input, stretch=1)

        order_input = QLineEdit(row)
        order_input.setObjectName("RouteNotesNodeOrderInput")
        order_input.setProperty("routePanelInput", "true")
        order_input.setAlignment(Qt.AlignCenter)
        order_input.setFixedSize(58, 26)
        order_input.setText(f"{index + 1}/{len(self._nodes)}")
        order_input.setToolTip(strings.CHANGE_POINT_ORDER_MENU_LABEL)
        order_input.setProperty("routeNotesDragIndex", index)
        order_input.setContextMenuPolicy(Qt.NoContextMenu)
        order_input.installEventFilter(self)
        order_input.editingFinished.connect(
            lambda editor=order_input, known_index=index: self._apply_order_text(known_index, editor.text())
        )
        row_layout.addWidget(order_input)
        return row

    def _show_name_context_menu(self, editor: QLineEdit, pos) -> None:
        has_selection = editor.hasSelectedText()
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text() if clipboard is not None else ""
        read_only = editor.isReadOnly()
        show_context_menu(
            editor,
            editor.mapToGlobal(pos),
            [
                ContextMenuItem("撤销", editor.undo, enabled=not read_only and editor.isUndoAvailable()),
                ContextMenuItem("重做", editor.redo, enabled=not read_only and editor.isRedoAvailable()),
                ContextMenuItem.separator_item(),
                ContextMenuItem("剪切", editor.cut, enabled=not read_only and has_selection),
                ContextMenuItem("复制", editor.copy, enabled=has_selection),
                ContextMenuItem("粘贴", editor.paste, enabled=not read_only and bool(clipboard_text)),
                ContextMenuItem("删除", lambda: editor.del_(), enabled=not read_only and has_selection),
                ContextMenuItem.separator_item(),
                ContextMenuItem("全选", editor.selectAll, enabled=bool(editor.text())),
            ],
            object_name="RouteListContextMenu",
        )

    def _node_annotation_tooltip(self, point: dict) -> str:
        annotation = route_node_annotation(point)
        if annotation is None:
            return strings.ANNOTATION_TYPE_PICKER_CLEAR
        return annotation[1]

    def _set_node_label(self, index: int, text: str) -> None:
        if self._syncing or not (0 <= index < len(self._nodes)):
            return
        before = self._nodes[index].get("label", None)
        label = str(text or "").strip()
        if label:
            self._nodes[index]["label"] = label
        else:
            self._nodes[index].pop("label", None)
        after = self._nodes[index].get("label", None)
        if before == after:
            return
        self.node_label_changed.emit(index, before, after)
        self._emit_nodes_changed()

    def _commit_node_label(self, index: int, editor: QLineEdit) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        before = editor.property("routeNotesLabelBefore")
        after = self._nodes[index].get("label", None)
        if before == after:
            return
        editor.setProperty("routeNotesLabelBefore", after)
        self.node_label_edit_committed.emit(index, before, after)

    def _apply_order_text(self, index: int, text: str) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        raw_target = str(text or "").split("/", 1)[0].strip()
        try:
            target = int(raw_target) - 1
        except (TypeError, ValueError):
            self._refresh_node_rows()
            return
        self._move_node(index, target)

    def _move_node(self, from_index: int, to_index: int) -> bool:
        if not (0 <= from_index < len(self._nodes)):
            return False
        target = max(0, min(len(self._nodes) - 1, int(to_index)))
        if target == from_index:
            self._refresh_node_rows()
            return False
        point = self._nodes.pop(from_index)
        self._nodes.insert(target, point)
        self._refresh_after_node_change()
        self.node_order_changed.emit(from_index, target)
        self._emit_nodes_changed()
        return True

    def _refresh_after_node_change(self, *, emit: bool = False) -> None:
        self._refresh_stats_section()
        self._refresh_node_rows()
        if emit:
            self._emit_nodes_changed()

    def _annotation_items(self) -> list[dict]:
        if callable(self._annotation_items_provider):
            items = self._annotation_items_provider()
            return [dict(item) for item in items or [] if isinstance(item, dict)]
        parent = self.parent()
        route_mgr = getattr(parent, "route_mgr", None)
        if route_mgr is not None and hasattr(route_mgr, "annotation_type_items"):
            return route_mgr.annotation_type_items()
        return []

    def _change_node_annotation(self, index: int) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        items = self._annotation_items()
        current_type_id = str(self._nodes[index].get("typeId") or "")
        selected = open_annotation_type_picker(
            self,
            items,
            current_type_id,
            include_clear=True,
            placement=self._annotation_picker_placement,
            anchor=self._annotation_picker_anchor or self,
        )
        if selected is None:
            return
        before = _persistable_route_node(self._nodes[index])
        if selected.get("clear"):
            self._nodes[index].pop("typeId", None)
            self._nodes[index].pop("type", None)
            self._nodes[index].pop("icon_path", None)
            after = _persistable_route_node(self._nodes[index])
            self._refresh_after_node_change()
            self.node_annotation_changed.emit(index, before, after)
            self._emit_nodes_changed()
            return

        type_id = str(selected.get("typeId") or "").strip()
        if not type_id:
            return
        type_name = str(selected.get("type") or type_id).strip() or type_id
        self._nodes[index]["typeId"] = type_id
        self._nodes[index]["type"] = type_name
        self._nodes[index]["icon_path"] = str(annotation_icon_path(selected, type_id))
        after = _persistable_route_node(self._nodes[index])
        self._refresh_after_node_change()
        self.node_annotation_changed.emit(index, before, after)
        self._emit_nodes_changed()

    def eventFilter(self, source, event) -> bool:
        index = source.property("routeNotesDragIndex") if hasattr(source, "property") else None
        if index is None:
            return super().eventFilter(source, event)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return super().eventFilter(source, event)

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_candidate = {
                "index": index,
                "start": event.globalPosition().toPoint(),
                "active": False,
                "source": source,
            }
            return False
        if event.type() == QEvent.Type.MouseMove and self._drag_candidate is not None:
            distance = (event.globalPosition().toPoint() - self._drag_candidate["start"]).manhattanLength()
            if not self._drag_candidate.get("active") and distance >= QApplication.startDragDistance():
                self._drag_candidate["active"] = True
                self._begin_node_drag(int(self._drag_candidate["index"]), event.globalPosition().toPoint())
            if self._drag_candidate.get("active"):
                self._update_node_drag(event.globalPosition().toPoint())
                return True
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and self._drag_candidate is not None:
            candidate = self._drag_candidate
            self._drag_candidate = None
            if candidate.get("active"):
                self._finish_node_drag(int(candidate["index"]), event.globalPosition().toPoint())
                return True
            return False
        return super().eventFilter(source, event)

    def _begin_node_drag(self, index: int, global_pos) -> None:
        if not (0 <= index < len(self._node_rows)):
            return
        row = self._node_rows[index]
        row.grabMouse()
        self._drag_row_effect = QGraphicsOpacityEffect(row)
        self._drag_row_effect.setOpacity(0.32)
        row.setGraphicsEffect(self._drag_row_effect)

        preview = self._build_drag_preview(index)
        preview.adjustSize()
        self._drag_preview = preview
        self._move_drag_preview(global_pos)
        preview.show()
        preview.raise_()
        self._update_drop_indicator(global_pos)

    def _build_drag_preview(self, index: int) -> QWidget:
        point = self._nodes[index]
        preview = QFrame(self, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        preview.setObjectName("RouteNotesDragPreview")
        preview.setAttribute(Qt.WA_ShowWithoutActivating, True)
        preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        preview.setStyleSheet(self.styleSheet())
        layout = QHBoxLayout(preview)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(7)

        icon = QLabel(preview)
        icon.setFixedSize(_NODE_ICON_SIZE, _NODE_ICON_SIZE)
        pixmap, _fallback = route_node_icon_pixmap(point, self._route_color_hex)
        icon.setPixmap(pixmap)
        layout.addWidget(icon)

        name = QLabel(route_node_display_name(point, index), preview)
        name.setObjectName("RouteNotesDragPreviewName")
        name.setMinimumWidth(_NODE_NAME_MIN_WIDTH)
        layout.addWidget(name, stretch=1)

        order = QLabel(f"{index + 1}/{len(self._nodes)}", preview)
        order.setObjectName("RouteNotesDragPreviewOrder")
        layout.addWidget(order)

        width = self._node_rows[index].width() if 0 <= index < len(self._node_rows) else 260
        preview.setFixedWidth(max(_NODE_DRAG_PREVIEW_MIN_WIDTH, width))
        return preview

    def _move_drag_preview(self, global_pos) -> None:
        if self._drag_preview is None:
            return
        self._drag_preview.move(global_pos + QPoint(12, 10))

    def _update_node_drag(self, global_pos) -> None:
        self._move_drag_preview(global_pos)
        self._update_drop_indicator(global_pos)

    def _finish_node_drag(self, from_index: int, global_pos) -> None:
        target = self._update_drop_indicator(global_pos)
        self._cleanup_node_drag()
        if target is None:
            return
        if target > from_index:
            target -= 1
        self._move_node(from_index, target)

    def _cleanup_node_drag(self) -> None:
        for row in self._node_rows:
            try:
                row.releaseMouse()
            except RuntimeError:
                pass
            row.setGraphicsEffect(None)
        self._drag_row_effect = None
        if self._drag_preview is not None:
            self._drag_preview.hide()
            self._drag_preview.deleteLater()
            self._drag_preview = None
        if self._drop_indicator is not None:
            self._drop_indicator.hide()
        self._drop_target_index = None

    def _update_drop_indicator(self, global_pos) -> int | None:
        host = self._nodes_scroll.widget()
        indicator = self._drop_indicator
        if host is None or indicator is None or not self._node_rows:
            return None
        local = host.mapFromGlobal(global_pos)
        target = len(self._node_rows)
        indicator_y = self._node_rows[-1].geometry().bottom() + 3
        for index, row in enumerate(self._node_rows):
            row_geo = row.geometry()
            if local.y() < row_geo.center().y():
                target = index
                indicator_y = row_geo.top() - 3
                break
        indicator.setGeometry(4, max(0, indicator_y), max(24, host.width() - 8), 3)
        indicator.show()
        indicator.raise_()
        self._drop_target_index = target
        return target


class RouteNotesDialog(StyledDialogBase):
    nodes_changed_signal = Signal()
    color_preview_changed = Signal(object)
    confirm_requested = Signal()
    cancel_requested = Signal()

    def __init__(
        self,
        parent,
        route_name: str,
        notes: str,
        route_color: tuple[int, int, int],
        color_override: str | None,
        nodes: list[dict],
        *,
        enable_versions: list[str] | None = None,
        enable_version_options: list[str] | None = None,
        modal: bool = True,
    ) -> None:
        super().__init__(
            parent,
            route_name,
            modal=modal,
            min_width=_ROUTE_NOTES_DIALOG_MIN_WIDTH,
            max_width=_ROUTE_NOTES_DIALOG_MAX_WIDTH,
        )
        self._route_name = route_name
        self._notes = notes
        self._route_color_hex = route_color_to_hex(route_color)
        self._color_override = normalize_color_hex(color_override) if color_override else None
        self._original_nodes = [_persistable_route_node(point) for point in nodes if isinstance(point, dict)]
        self._enable_versions = (
            resource_metadata.normalize_enable_versions(enable_versions)
            if isinstance(enable_versions, list)
            else None
        )
        self._original_enable_versions = (
            list(self._enable_versions) if self._enable_versions is not None else None
        )
        self._enable_version_options = resource_metadata.route_enable_version_options(
            [*(enable_version_options or []), *(self._enable_versions or [])]
        )
        self._controller_managed = not modal
        self._force_close = False
        self._initializing_layout = True
        self.setMinimumSize(_ROUTE_NOTES_DIALOG_MIN_WIDTH, _ROUTE_NOTES_DIALOG_INITIAL_HEIGHT)
        self.setMaximumWidth(_ROUTE_NOTES_DIALOG_MAX_WIDTH)
        self._initial_splitter_sizes_pending = True
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(_ROUTE_NOTES_LAYOUT_SAVE_DELAY_MS)
        self._layout_save_timer.timeout.connect(self._persist_layout_preferences)
        self.annotation_group_expanded = getattr(parent, "annotation_group_expanded", {})
        self._on_annotation_group_expanded_changed = getattr(parent, "_on_annotation_group_expanded_changed", None)
        self._preferred_dialog_width = _route_notes_config_int(
            "ROUTE_NOTES_DIALOG_WIDTH",
            _ROUTE_NOTES_DIALOG_INITIAL_WIDTH,
            _ROUTE_NOTES_DIALOG_MIN_WIDTH,
            _ROUTE_NOTES_DIALOG_MAX_WIDTH,
        )
        max_node_panel_width = max(
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            self._preferred_dialog_width - _ROUTE_NOTES_LEFT_MIN_WIDTH,
        )
        self._preferred_node_panel_width = _route_notes_config_int(
            "ROUTE_NOTES_NODE_PANEL_WIDTH",
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            min(_ROUTE_NOTES_NODE_PANEL_MAX_WIDTH, max_node_panel_width),
        )

        self._build_title_opacity_controls()

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setObjectName("RouteNotesSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        left = QWidget(self.splitter)
        left.setObjectName("RouteNotesLeftColumn")
        left.setMinimumWidth(_ROUTE_NOTES_LEFT_MIN_WIDTH)
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self._build_notes_column(left_layout)
        self.stats_panel = RouteNodeStatsPanel(left)
        self.stats_panel.set_nodes(nodes)
        left_layout.addWidget(self.stats_panel)
        self.splitter.addWidget(left)

        right = QWidget(self.splitter)
        right.setObjectName("RouteNotesRightColumn")
        right.setMinimumWidth(_ROUTE_NOTES_RIGHT_MIN_WIDTH)
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.node_panel = RouteNodeEditorPanel(
            right,
            route_color_hex=self.effective_color_hex(),
            annotation_items_provider=self._annotation_items,
            annotation_icon_path_provider=self._annotation_icon_path,
            include_stats=False,
            annotation_picker_placement="left_of",
            annotation_picker_anchor=right,
        )
        self.node_panel.set_nodes(nodes)
        self.node_panel.nodes_changed.connect(self._on_node_panel_nodes_changed)
        right_layout.addWidget(self.node_panel, stretch=1)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)

        self.shell_layout.addWidget(self.splitter, stretch=1)
        self.add_action_row(confirm_text=strings.ROUTE_NOTES_CONFIRM, cancel_text=strings.ROUTE_NOTES_CANCEL)
        self._size_grip = QSizeGrip(self.shell)
        self._size_grip.setObjectName("RouteNotesSizeGrip")
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setToolTip("拖动调整窗口大小")
        self.resize(self._preferred_dialog_width, _ROUTE_NOTES_DIALOG_INITIAL_HEIGHT)
        self._apply_initial_splitter_sizes()
        self._position_size_grip()
        self._initializing_layout = False

    def _build_title_opacity_controls(self) -> None:
        title_layout = self.title_bar.layout()
        if title_layout is None:
            return
        close_index = title_layout.indexOf(self.close_btn)
        insert_index = close_index if close_index >= 0 else title_layout.count()

        opacity_label = QLabel("透明度", self.title_bar)
        opacity_label.setObjectName("StatLabel")
        opacity_label.setToolTip("路线详情窗口透明度")
        title_layout.insertWidget(insert_index, opacity_label)
        insert_index += 1

        self.opacity_slider = make_compact_slider(
            object_name="RouteNotesOpacitySlider",
            minimum=_ROUTE_NOTES_MIN_OPACITY_PERCENT,
            maximum=100,
            value=_ROUTE_NOTES_DEFAULT_OPACITY_PERCENT,
            min_width=_ROUTE_NOTES_OPACITY_SLIDER_MIN_WIDTH,
            max_width=_ROUTE_NOTES_OPACITY_SLIDER_MAX_WIDTH,
            parent=self.title_bar,
        )
        self.opacity_slider.setToolTip("路线详情窗口透明度：100%")
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        title_layout.insertWidget(insert_index, self.opacity_slider)
        self._on_opacity_slider_changed(self.opacity_slider.value())

    def _apply_initial_splitter_sizes(self) -> None:
        if not hasattr(self, "splitter"):
            return
        max_right_width = min(
            _ROUTE_NOTES_NODE_PANEL_MAX_WIDTH,
            max(
                _ROUTE_NOTES_RIGHT_MIN_WIDTH,
                (self.width() or self._preferred_dialog_width) - _ROUTE_NOTES_LEFT_MIN_WIDTH,
            ),
        )
        right_width = _clamp_int(
            self._preferred_node_panel_width,
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            max_right_width,
        )
        left_width = max(_ROUTE_NOTES_LEFT_MIN_WIDTH, self._preferred_dialog_width - right_width - 50)
        self.splitter.setSizes([left_width, right_width])
        self._initial_splitter_sizes_pending = False

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        self._initial_splitter_sizes_pending = False
        self._schedule_layout_preferences_save()

    def _route_notes_panel_widths(self) -> tuple[int, int]:
        sizes = self.splitter.sizes() if hasattr(self, "splitter") else []
        if len(sizes) >= 2 and sum(sizes) > 0:
            return int(sizes[0]), int(sizes[1])
        return 0, int(getattr(self, "_preferred_node_panel_width", _ROUTE_NOTES_RIGHT_MIN_WIDTH))

    def _persist_layout_preferences(self) -> None:
        if getattr(self, "_initializing_layout", False):
            return
        _left_width, right_width = self._route_notes_panel_widths()
        dialog_width = _clamp_int(
            self.width(),
            _ROUTE_NOTES_DIALOG_INITIAL_WIDTH,
            _ROUTE_NOTES_DIALOG_MIN_WIDTH,
            _ROUTE_NOTES_DIALOG_MAX_WIDTH,
        )
        right_width = _clamp_int(
            right_width,
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            _ROUTE_NOTES_RIGHT_MIN_WIDTH,
            min(
                _ROUTE_NOTES_NODE_PANEL_MAX_WIDTH,
                max(_ROUTE_NOTES_RIGHT_MIN_WIDTH, dialog_width - _ROUTE_NOTES_LEFT_MIN_WIDTH),
            ),
        )
        try:
            config.save_config(
                {
                    "ROUTE_NOTES_DIALOG_WIDTH": dialog_width,
                    "ROUTE_NOTES_NODE_PANEL_WIDTH": right_width,
                }
            )
        except Exception as exc:
            print(f"Save route notes layout failed: {exc}")

    def _schedule_layout_preferences_save(self) -> None:
        if getattr(self, "_initializing_layout", False):
            return
        timer = getattr(self, "_layout_save_timer", None)
        if timer is not None:
            timer.start()

    def _flush_layout_preferences_save(self) -> None:
        timer = getattr(self, "_layout_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._persist_layout_preferences()

    def _position_size_grip(self) -> None:
        grip = getattr(self, "_size_grip", None)
        if grip is None:
            return
        grip.move(self.shell.width() - grip.width() - 3, self.shell.height() - grip.height() - 3)
        grip.raise_()

    def _build_notes_column(self, layout: QVBoxLayout) -> None:
        notes_header = QWidget(self)
        notes_header.setObjectName("RouteNotesHeaderRow")
        notes_header.setFixedHeight(_TITLE_ROW_HEIGHT)
        header_layout = QHBoxLayout(notes_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        notes_label = QLabel(strings.ROUTE_NOTES_NOTES_LABEL, notes_header)
        notes_label.setObjectName("FieldLabel")
        header_layout.addWidget(notes_label)

        self.color_button = QPushButton(self)
        self.color_button.clicked.connect(self._pick_color)
        self.color_button.setFixedHeight(26)
        self.color_button.setFixedWidth(_COLOR_BUTTON_WIDTH)
        header_layout.addWidget(self.color_button)

        self.reset_color_button = QPushButton(strings.ROUTE_NOTES_COLOR_RESET, self)
        self.reset_color_button.clicked.connect(self._reset_color)
        self.reset_color_button.setFixedHeight(26)
        header_layout.addWidget(self.reset_color_button)
        self.enable_versions_button = QPushButton("查看/修改兼容版本", self)
        self.enable_versions_button.setObjectName("RouteEnableVersionsButton")
        self.enable_versions_button.clicked.connect(self._edit_enable_versions)
        self.enable_versions_button.setFixedHeight(26)
        header_layout.addWidget(self.enable_versions_button)

        header_layout.addStretch()
        layout.addWidget(notes_header)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText(strings.ROUTE_NOTES_PLACEHOLDER)
        self.editor.setPlainText(self._notes)
        self.editor.setMinimumHeight(120)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.editor, stretch=1)
        self._sync_color_controls()
        self._sync_enable_versions_button()

    def _on_node_panel_nodes_changed(self) -> None:
        self._refresh_stats_section()
        self.nodes_changed_signal.emit()

    def _build_stats_section(self, layout: QVBoxLayout) -> None:
        stats_title = QLabel(strings.ROUTE_NOTES_STATS_TITLE)
        stats_title.setObjectName("FieldLabel")
        layout.addWidget(stats_title)

        self._stats_scroll = make_scroll_area(
            object_name="RouteNotesStatsScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            vertical_policy=Qt.ScrollBarAsNeeded,
        )
        layout.addWidget(self._stats_scroll)
        self._refresh_stats_section()

    def _refresh_stats_section(self) -> None:
        if hasattr(self, "stats_panel"):
            self.stats_panel.set_nodes(self.node_panel.draft_nodes())
        return
        stats = QFrame(self)
        stats.setObjectName("RouteNotesStatsPanel")
        stats_layout = QGridLayout(stats)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setHorizontalSpacing(6)
        stats_layout.setVerticalSpacing(6)
        summary = summarize_route_nodes(self._nodes)
        stat_items = [
            (strings.ROUTE_NOTES_NODE_COLLECT, summary["node_counts"].get(NODE_TYPE_COLLECT, 0)),
            (strings.ROUTE_NOTES_NODE_TELEPORT, summary["node_counts"].get(NODE_TYPE_TELEPORT, 0)),
            (strings.ROUTE_NOTES_NODE_GUIDE, summary["node_counts"].get(NODE_TYPE_VIRTUAL, 0)),
        ]
        stat_items.extend((item["label"], item["count"]) for item in summary["annotations"])
        for index, (label, count) in enumerate(stat_items):
            chip = QLabel(f"{label} {count}")
            chip.setObjectName("RouteNotesStatChip")
            chip.setToolTip(f"{label}：{count}")
            stats_layout.addWidget(chip, index // _STAT_COLUMNS, index % _STAT_COLUMNS)

        scroll_height = max(_STATS_SCROLL_DEFAULT_HEIGHT, min(_STATS_SCROLL_MAX_HEIGHT, stats.sizeHint().height()))
        self._stats_scroll.setMinimumHeight(scroll_height)
        self._stats_scroll.setMaximumHeight(scroll_height)
        self._stats_scroll.setWidget(stats)

    def _build_nodes_column(self, layout: QVBoxLayout) -> None:
        nodes_title = QLabel(strings.ROUTE_NOTES_NODE_LIST)
        nodes_title.setObjectName("FieldLabel")
        nodes_title.setFixedHeight(_TITLE_ROW_HEIGHT)
        nodes_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(nodes_title)

        self._nodes_scroll = make_scroll_area(
            object_name="RouteNotesNodeScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            min_height=_NODE_SCROLL_MIN_HEIGHT,
            size_policy=(QSizePolicy.Expanding, QSizePolicy.Expanding),
        )
        layout.addWidget(self._nodes_scroll, stretch=1)
        self._refresh_node_rows()

    def _refresh_node_rows(self) -> None:
        scroll_value = 0
        if hasattr(self, "_nodes_scroll"):
            scroll_value = self._nodes_scroll.verticalScrollBar().value()

        host = QWidget()
        host.setObjectName("AnnotationPanelInner")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(2, 2, 2, 2)
        host_layout.setSpacing(6)
        self._node_rows = []
        if not self._nodes:
            empty = QLabel(strings.ROUTE_NOTES_NODE_EMPTY)
            empty.setObjectName("DimLabel")
            empty.setWordWrap(True)
            host_layout.addWidget(empty)
        else:
            display_names = route_node_display_names(self._nodes)
            for index, point in enumerate(self._nodes):
                row = self._build_node_row(point, index, display_names[index])
                self._node_rows.append(row)
                host_layout.addWidget(row)
        host_layout.addStretch(1)
        self._nodes_scroll.setWidget(host)
        self._nodes_scroll.verticalScrollBar().setValue(scroll_value)
        self._drop_indicator = QFrame(host)
        self._drop_indicator.setObjectName("RouteNotesDropIndicator")
        self._drop_indicator.setFixedHeight(3)
        self._drop_indicator.hide()

    def _build_node_row(self, point: dict, index: int, display_name: str) -> QWidget:
        row = QWidget()
        row.setObjectName("RouteNotesNodeRow")
        row.setProperty("routeNotesDragIndex", index)
        row.installEventFilter(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(6)

        icon_button = QPushButton(row)
        icon_button.setObjectName("RouteNotesNodeIcon")
        icon_button.setFixedSize(26, 26)
        icon_button.setIconSize(icon_button.size())
        pixmap, fallback = route_node_icon_pixmap(point, self.effective_color_hex())
        icon_button.setIcon(QIcon(pixmap))
        icon_button.setProperty("fallbackIcon", fallback)
        icon_button.setProperty("routeNotesDragIndex", index)
        icon_button.setToolTip(self._node_annotation_tooltip(point))
        icon_button.clicked.connect(lambda _checked=False, known_index=index: self._change_node_annotation(known_index))
        icon_button.installEventFilter(self)
        row_layout.addWidget(icon_button)

        name_input = make_route_panel_line_edit(
            placeholder=display_name,
            parent=row,
            size_policy=(QSizePolicy.Ignored, QSizePolicy.Fixed),
        )
        name_input.setObjectName("RouteNotesNodeName")
        name_input.setMinimumWidth(_NODE_NAME_MIN_WIDTH)
        current_label = str(point.get("label") or "").strip()
        name_input.setText(display_name if not current_label or is_auto_route_node_label(current_label) else current_label)
        name_input.setToolTip(display_name)
        name_input.textChanged.connect(lambda text, known_index=index: self._set_node_label(known_index, text))
        row_layout.addWidget(name_input, stretch=1)

        order_input = QLineEdit(row)
        order_input.setObjectName("RouteNotesNodeOrderInput")
        order_input.setProperty("routePanelInput", "true")
        order_input.setAlignment(Qt.AlignCenter)
        order_input.setFixedSize(58, 26)
        order_input.setText(f"{index + 1}/{len(self._nodes)}")
        order_input.setToolTip(strings.CHANGE_POINT_ORDER_MENU_LABEL)
        order_input.setProperty("routeNotesDragIndex", index)
        order_input.installEventFilter(self)
        order_input.editingFinished.connect(
            lambda editor=order_input, known_index=index: self._apply_order_text(known_index, editor.text())
        )
        row_layout.addWidget(order_input)
        return row

    def _node_annotation_tooltip(self, point: dict) -> str:
        annotation = route_node_annotation(point)
        if annotation is None:
            return strings.ANNOTATION_TYPE_PICKER_CLEAR
        return annotation[1]

    def _set_node_label(self, index: int, text: str) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        label = str(text or "").strip()
        if label:
            self._nodes[index]["label"] = label
        else:
            self._nodes[index].pop("label", None)

    def _apply_order_text(self, index: int, text: str) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        raw_target = str(text or "").split("/", 1)[0].strip()
        try:
            target = int(raw_target) - 1
        except (TypeError, ValueError):
            self._refresh_node_rows()
            return
        self._move_node(index, target)

    def _move_node(self, from_index: int, to_index: int) -> bool:
        if not (0 <= from_index < len(self._nodes)):
            return False
        target = max(0, min(len(self._nodes) - 1, int(to_index)))
        if target == from_index:
            self._refresh_node_rows()
            return False
        point = self._nodes.pop(from_index)
        self._nodes.insert(target, point)
        self._refresh_after_node_change()
        return True

    def _refresh_after_node_change(self) -> None:
        self._refresh_stats_section()
        self._refresh_node_rows()

    def _change_node_annotation(self, index: int) -> None:
        if not (0 <= index < len(self._nodes)):
            return
        parent = self.parent()
        route_mgr = getattr(parent, "route_mgr", None)
        items = route_mgr.annotation_type_items() if route_mgr is not None and hasattr(route_mgr, "annotation_type_items") else []
        current_type_id = str(self._nodes[index].get("typeId") or "")
        selected = open_annotation_type_picker(self, items, current_type_id, include_clear=True)
        if selected is None:
            return
        if selected.get("clear"):
            self._nodes[index].pop("typeId", None)
            self._nodes[index].pop("type", None)
            self._nodes[index].pop("icon_path", None)
            self._refresh_after_node_change()
            return

        type_id = str(selected.get("typeId") or "").strip()
        if not type_id:
            return
        type_name = str(selected.get("type") or type_id).strip() or type_id
        self._nodes[index]["typeId"] = type_id
        self._nodes[index]["type"] = type_name
        self._nodes[index]["icon_path"] = str(annotation_icon_path(selected, type_id))
        self._refresh_after_node_change()

    def eventFilter(self, source, event) -> bool:
        index = source.property("routeNotesDragIndex") if hasattr(source, "property") else None
        if index is None:
            return super().eventFilter(source, event)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return super().eventFilter(source, event)

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_candidate = {
                "index": index,
                "start": event.globalPosition().toPoint(),
                "active": False,
                "source": source,
            }
            return False
        if event.type() == QEvent.Type.MouseMove and self._drag_candidate is not None:
            distance = (event.globalPosition().toPoint() - self._drag_candidate["start"]).manhattanLength()
            if not self._drag_candidate.get("active") and distance >= QApplication.startDragDistance():
                self._drag_candidate["active"] = True
                self._begin_node_drag(int(self._drag_candidate["index"]), event.globalPosition().toPoint())
            if self._drag_candidate.get("active"):
                self._update_node_drag(event.globalPosition().toPoint())
                return True
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and self._drag_candidate is not None:
            candidate = self._drag_candidate
            self._drag_candidate = None
            if candidate.get("active"):
                self._finish_node_drag(int(candidate["index"]), event.globalPosition().toPoint())
                return True
            return False
        return super().eventFilter(source, event)

    def _begin_node_drag(self, index: int, global_pos) -> None:
        if not (0 <= index < len(self._node_rows)):
            return
        row = self._node_rows[index]
        row.grabMouse()
        self._drag_row_effect = QGraphicsOpacityEffect(row)
        self._drag_row_effect.setOpacity(0.32)
        row.setGraphicsEffect(self._drag_row_effect)

        preview = self._build_drag_preview(index)
        preview.adjustSize()
        self._drag_preview = preview
        self._move_drag_preview(global_pos)
        preview.show()
        preview.raise_()
        self._update_drop_indicator(global_pos)

    def _build_drag_preview(self, index: int) -> QWidget:
        point = self._nodes[index]
        preview = QFrame(self, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        preview.setObjectName("RouteNotesDragPreview")
        preview.setAttribute(Qt.WA_ShowWithoutActivating, True)
        preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        preview.setStyleSheet(self.styleSheet())
        layout = QHBoxLayout(preview)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(7)

        icon = QLabel(preview)
        icon.setFixedSize(_NODE_ICON_SIZE, _NODE_ICON_SIZE)
        pixmap, _fallback = route_node_icon_pixmap(point, self.effective_color_hex())
        icon.setPixmap(pixmap)
        layout.addWidget(icon)

        name = QLabel(route_node_display_name(point, index), preview)
        name.setObjectName("RouteNotesDragPreviewName")
        name.setMinimumWidth(_NODE_NAME_MIN_WIDTH)
        layout.addWidget(name, stretch=1)

        order = QLabel(f"{index + 1}/{len(self._nodes)}", preview)
        order.setObjectName("RouteNotesDragPreviewOrder")
        layout.addWidget(order)

        width = self._node_rows[index].width() if 0 <= index < len(self._node_rows) else 260
        preview.setFixedWidth(max(_NODE_DRAG_PREVIEW_MIN_WIDTH, width))
        return preview

    def _move_drag_preview(self, global_pos) -> None:
        if self._drag_preview is None:
            return
        self._drag_preview.move(global_pos + QPoint(12, 10))

    def _update_node_drag(self, global_pos) -> None:
        self._move_drag_preview(global_pos)
        self._update_drop_indicator(global_pos)

    def _finish_node_drag(self, from_index: int, global_pos) -> None:
        target = self._update_drop_indicator(global_pos)
        self._cleanup_node_drag()
        if target is None:
            return
        if target > from_index:
            target -= 1
        self._move_node(from_index, target)

    def _cleanup_node_drag(self) -> None:
        for row in self._node_rows:
            try:
                row.releaseMouse()
            except RuntimeError:
                pass
            row.setGraphicsEffect(None)
        self._drag_row_effect = None
        if self._drag_preview is not None:
            self._drag_preview.hide()
            self._drag_preview.deleteLater()
            self._drag_preview = None
        if self._drop_indicator is not None:
            self._drop_indicator.hide()
        self._drop_target_index = None

    def _update_drop_indicator(self, global_pos) -> int | None:
        host = self._nodes_scroll.widget()
        indicator = self._drop_indicator
        if host is None or indicator is None or not self._node_rows:
            return None
        local = host.mapFromGlobal(global_pos)
        target = len(self._node_rows)
        indicator_y = self._node_rows[-1].geometry().bottom() + 3
        for index, row in enumerate(self._node_rows):
            row_geo = row.geometry()
            if local.y() < row_geo.center().y():
                target = index
                indicator_y = row_geo.top() - 3
                break
        indicator.setGeometry(4, max(0, indicator_y), max(24, host.width() - 8), 3)
        indicator.show()
        indicator.raise_()
        self._drop_target_index = target
        return target

    def _annotation_items(self) -> list[dict]:
        parent = self.parent()
        route_mgr = getattr(parent, "route_mgr", None)
        if route_mgr is not None and hasattr(route_mgr, "annotation_type_items"):
            return route_mgr.annotation_type_items()
        return []

    def _annotation_icon_path(self, type_id: object) -> str:
        parent = self.parent()
        route_mgr = getattr(parent, "route_mgr", None)
        if route_mgr is not None and hasattr(route_mgr, "point_icon_path_for"):
            return str(route_mgr.point_icon_path_for(type_id) or "")
        return ""

    def set_nodes(self, nodes: list[dict], refresh: bool = True) -> None:
        self.node_panel.set_nodes(nodes, refresh=refresh)
        self._refresh_stats_section()

    def draft_nodes(self) -> list[dict]:
        return self.node_panel.draft_nodes()

    def _refresh_after_node_change(self) -> None:
        self.node_panel._refresh_after_node_change()

    def _change_node_annotation(self, index: int) -> None:
        self.node_panel._change_node_annotation(index)

    def _move_node(self, from_index: int, to_index: int) -> bool:
        return self.node_panel._move_node(from_index, to_index)

    def eventFilter(self, source, event) -> bool:
        return super().eventFilter(source, event)

    def _pick_color(self) -> None:
        color = open_styled_color_picker(
            self,
            strings.ROUTE_NOTES_COLOR_PICK,
            self.effective_color_hex(),
        )
        if color is None or not color.isValid():
            return
        self._color_override = color.name(QColor.HexRgb)
        self._sync_color_controls()
        self.color_preview_changed.emit(self._color_override)

    def _reset_color(self) -> None:
        self._color_override = None
        self._sync_color_controls()
        self.color_preview_changed.emit(self._color_override)

    def _sync_color_controls(self) -> None:
        effective = self.effective_color_hex()
        color = QColor(effective)
        text_color = "#000000" if color.lightness() > 150 else "#ffffff"
        if self._color_override:
            tooltip = strings.ROUTE_NOTES_COLOR_CUSTOM_TOOLTIP
        else:
            tooltip = strings.ROUTE_NOTES_COLOR_FOLLOW_TOOLTIP
        self.color_button.setText(_COLOR_BUTTON_TEXT)
        self.color_button.setToolTip(tooltip)
        self.color_button.setStyleSheet(
            f"background: {effective}; color: {text_color}; border: 1px solid rgba(255, 255, 255, 0.35);"
        )
        self.reset_color_button.setEnabled(self._color_override is not None)
        self.reset_color_button.setToolTip(strings.ROUTE_NOTES_COLOR_RESET_TOOLTIP)
        panel = getattr(self, "node_panel", None)
        if panel is not None:
            panel.set_route_color_hex(effective)

    def effective_color_hex(self) -> str:
        return self._color_override or self._route_color_hex

    def notes_text(self) -> str:
        return self.editor.toPlainText()

    def color_override(self) -> str | None:
        return self._color_override

    def enable_versions(self) -> list[str] | None:
        return list(self._enable_versions) if self._enable_versions is not None else None

    def enable_versions_changed(self) -> bool:
        return self._enable_versions != self._original_enable_versions

    def nodes(self) -> list[dict]:
        return self.node_panel.nodes()

    def nodes_changed(self) -> bool:
        return self.nodes() != self._original_nodes

    def _edit_enable_versions(self) -> None:
        options = resource_metadata.route_enable_version_options(
            [*(self._enable_version_options or []), *(self._enable_versions or [])]
        )
        selected = open_route_enable_versions_dialog(self, options, self._enable_versions or [])
        if selected is None:
            return
        if not options and not selected and self._enable_versions is None:
            return
        self._enable_versions = selected
        self._enable_version_options = resource_metadata.route_enable_version_options([*options, *selected])
        self._sync_enable_versions_button()

    def _sync_enable_versions_button(self) -> None:
        versions = self._enable_versions or []
        suffix = str(len(versions)) if versions else "无"
        self.enable_versions_button.setText(f"查看/修改兼容版本（{suffix}）")
        if versions:
            self.enable_versions_button.setToolTip("兼容版本：\n" + "\n".join(versions))
        else:
            self.enable_versions_button.setToolTip("暂无兼容版本")

    def _on_opacity_slider_changed(self, value: int) -> None:
        percent = max(_ROUTE_NOTES_MIN_OPACITY_PERCENT, min(100, int(value)))
        self.setWindowOpacity(percent / 100.0)
        if hasattr(self, "opacity_slider"):
            self.opacity_slider.setToolTip(f"路线详情窗口透明度：{percent}%")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_size_grip()
        if getattr(self, "_initial_splitter_sizes_pending", False):
            self._apply_initial_splitter_sizes()
        self._schedule_layout_preferences_save()

    def accept(self) -> None:
        if self._controller_managed and not self._force_close:
            self.confirm_requested.emit()
            return
        self._flush_layout_preferences_save()
        super().accept()

    def reject(self) -> None:
        if self._controller_managed and not self._force_close:
            self.cancel_requested.emit()
            return
        self._flush_layout_preferences_save()
        super().reject()

    def closeEvent(self, event) -> None:
        if self._controller_managed and not self._force_close:
            event.ignore()
            self.cancel_requested.emit()
            return
        self._flush_layout_preferences_save()
        super().closeEvent(event)

    def force_close(self, accepted: bool = False) -> None:
        self._force_close = True
        try:
            self._flush_layout_preferences_save()
            if accepted:
                super().accept()
            else:
                super().reject()
        finally:
            self._force_close = False


def edit_route_notes(
    parent,
    route_name: str,
    notes: str,
    route_color: tuple[int, int, int],
    color_override: str | None,
    nodes: list[dict],
    enable_versions: list[str] | None = None,
    enable_version_options: list[str] | None = None,
) -> tuple[bool, str, str | None, bool, list[dict], bool, list[str] | None]:
    dialog = RouteNotesDialog(
        parent,
        route_name,
        notes,
        route_color,
        color_override,
        nodes,
        enable_versions=enable_versions,
        enable_version_options=enable_version_options,
    )
    center_dialog(dialog, parent)
    accepted = dialog.exec() == QDialog.Accepted
    if not accepted:
        return (
            False,
            notes,
            color_override,
            False,
            [dict(point) for point in nodes if isinstance(point, dict)],
            False,
            enable_versions,
        )
    return (
        True,
        dialog.notes_text(),
        dialog.color_override(),
        dialog.nodes_changed(),
        dialog.nodes(),
        dialog.enable_versions_changed(),
        dialog.enable_versions(),
    )

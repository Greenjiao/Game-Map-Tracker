"""Shared builders for annotation type rows."""

from __future__ import annotations

from pathlib import Path

import config
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget


class AnnotationGroupSection(QWidget):
    expanded_changed = Signal(str, bool)

    def __init__(
        self,
        group_name: str,
        expanded: bool = True,
        *,
        columns: int = 2,
        annotation_layer: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.group_name = group_name
        self._expanded = bool(expanded)
        self._columns = max(1, int(columns or 1))
        self._annotation_layer = str(annotation_layer or "")
        self.setObjectName("AnnotationGroupSection")
        self.setAttribute(Qt.WA_StyledBackground, True)
        if self._annotation_layer:
            self.setProperty("annotationLayer", self._annotation_layer)

        layout = QVBoxLayout(self)
        if self._annotation_layer:
            layout.setContentsMargins(6, 6, 6, 6)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QPushButton(self)
        self.header.setObjectName("SectionHeader")
        self.header.setProperty("compact", True)
        if self._annotation_layer:
            self.header.setProperty("annotationLayer", self._annotation_layer)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self.toggle_expanded)
        layout.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setObjectName("AnnotationGroupBody")
        if self._annotation_layer:
            self.body.setProperty("annotationLayer", self._annotation_layer)
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        for column in range(self._columns):
            self.grid.setColumnStretch(column, 1)
        layout.addWidget(self.body)

        self._sync_state()

    def add_row(self, row: QWidget, index: int) -> None:
        self.grid.addWidget(row, index // self._columns, index % self._columns)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._sync_state()
        self.expanded_changed.emit(self.group_name, self._expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def _sync_state(self) -> None:
        self.header.setText(f"{'▾' if self._expanded else '▸'} {self.group_name}")
        self.header.setToolTip("收起分类" if self._expanded else "展开分类")
        self.body.setVisible(self._expanded)
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
        self.updateGeometry()


def group_annotation_types(items: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    group_order: list[str] = []
    for item in items:
        group_name = str(item.get("group") or "其他")
        if group_name not in groups:
            groups[group_name] = []
            group_order.append(group_name)
        groups[group_name].append(item)
    return [(group_name, groups[group_name]) for group_name in group_order]


def annotation_icon_path(item: dict, type_id: str) -> Path:
    return Path(config.app_path("tools", "points_icon", str(item.get("iconPath") or f"{type_id}.png")))


def annotation_type_button_text(item: dict, type_id: str | None = None) -> str:
    known_type_id = str(type_id if type_id is not None else item.get("typeId") or "")
    type_name = str(item.get("type") or known_type_id)
    return f"{type_name}  ·  {item.get('count') or 0}"


def build_annotation_type_button(
    item: dict,
    *,
    selected: bool,
    parent=None,
    fade_icon: bool = False,
    strike_out: bool = False,
    min_height: int | None = None,
    icon_size: int | None = 20,
) -> QPushButton:
    type_id = str(item.get("typeId") or "")
    type_name = str(item.get("type") or type_id)

    button = QPushButton(annotation_type_button_text(item, type_id), parent)
    button.setObjectName("AnnotationTypeRow")
    button.setProperty("selected", bool(selected))
    button.setCheckable(True)
    button.setChecked(bool(selected))
    button.setToolTip(type_name)
    if icon_size is not None:
        button.setIconSize(QSize(icon_size, icon_size))
    if min_height is not None:
        button.setMinimumHeight(min_height)

    if strike_out:
        font = button.font()
        font.setStrikeOut(not selected)
        button.setFont(font)

    icon_path = annotation_icon_path(item, type_id)
    if icon_path.exists():
        pixmap = QPixmap(str(icon_path))
        if fade_icon and not selected:
            pixmap = _faded_pixmap(pixmap, 0.35)
        button.setIcon(QIcon(pixmap))
    return button


def _faded_pixmap(pixmap: QPixmap, opacity: float) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    faded = QPixmap(pixmap.size())
    faded.fill(Qt.transparent)
    painter = QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return faded

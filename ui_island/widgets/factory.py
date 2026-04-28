"""Small widget factories shared by island UI modules."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QFrame, QScrollArea, QSizePolicy

from ..design import tokens


def make_scroll_area(
    *,
    object_name: str = "",
    min_height: int | None = None,
    max_height: int | None = None,
    fixed_height: int | None = None,
    min_width: int | None = None,
    widget_resizable: bool = True,
    horizontal_policy=None,
    vertical_policy=None,
    size_policy: tuple[QSizePolicy.Policy, QSizePolicy.Policy] | None = None,
) -> QScrollArea:
    scroll = QScrollArea()
    if object_name:
        scroll.setObjectName(object_name)
    scroll.setWidgetResizable(widget_resizable)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.viewport().setAutoFillBackground(False)
    if horizontal_policy is not None:
        scroll.setHorizontalScrollBarPolicy(horizontal_policy)
    if vertical_policy is not None:
        scroll.setVerticalScrollBarPolicy(vertical_policy)
    if min_height is not None:
        scroll.setMinimumHeight(min_height)
    if max_height is not None:
        scroll.setMaximumHeight(max_height)
    if fixed_height is not None:
        scroll.setFixedHeight(fixed_height)
    if min_width is not None:
        scroll.setMinimumWidth(min_width)
    if size_policy is not None:
        scroll.setSizePolicy(*size_policy)
    return scroll


def make_header_icon_button(
    text: str,
    *,
    role: str,
    tooltip: str = "",
    width: int = 26,
    parent=None,
) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName("HeaderWindowButton")
    button.setProperty("iconRole", role)
    if tooltip:
        button.setToolTip(tooltip)
    button.setFixedWidth(width)
    return button


def make_route_panel_icon_button(
    text: str,
    *,
    role: str,
    tooltip: str = "",
    parent=None,
) -> QPushButton:
    button = make_header_icon_button(
        text,
        role=role,
        tooltip=tooltip,
        width=tokens.RECENT_ROUTE_ITEM_HEIGHT,
        parent=parent,
    )
    button.setProperty("routePanelIconButton", "true")
    button.setFixedSize(tokens.RECENT_ROUTE_ITEM_HEIGHT, tokens.RECENT_ROUTE_ITEM_HEIGHT)
    return button


def make_route_panel_line_edit(
    *,
    placeholder: str = "",
    parent=None,
    size_policy: tuple[QSizePolicy.Policy, QSizePolicy.Policy] | None = None,
) -> QLineEdit:
    editor = QLineEdit(parent)
    editor.setProperty("routePanelInput", "true")
    editor.setFixedHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
    if placeholder:
        editor.setPlaceholderText(placeholder)
    if size_policy is not None:
        editor.setSizePolicy(*size_policy)
    return editor


def make_label(
    text: str = "",
    *,
    object_name: str = "",
    parent=None,
    word_wrap: bool = False,
    alignment: Qt.AlignmentFlag | Qt.Alignment = Qt.Alignment(),
    selectable: bool = False,
) -> QLabel:
    label = QLabel(text, parent)
    if object_name:
        label.setObjectName(object_name)
    label.setWordWrap(word_wrap)
    if alignment:
        label.setAlignment(alignment)
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label

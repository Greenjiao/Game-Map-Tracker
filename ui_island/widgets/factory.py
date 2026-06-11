"""Small widget factories shared by island UI modules."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QFrame, QScrollArea, QSizePolicy, QSlider

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


def make_compact_slider(
    *,
    object_name: str = "",
    minimum: int = 0,
    maximum: int = 100,
    value: int | None = None,
    orientation: Qt.Orientation = Qt.Horizontal,
    min_width: int | None = None,
    max_width: int | None = None,
    parent=None,
) -> QSlider:
    slider = QSlider(orientation, parent)
    if object_name:
        slider.setObjectName(object_name)
    slider.setProperty("compactSlider", "true")
    slider.setRange(minimum, maximum)
    slider.setValue(maximum if value is None else value)
    slider.setFixedHeight(tokens.RECENT_ROUTE_ITEM_HEIGHT)
    slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    if min_width is not None:
        slider.setMinimumWidth(min_width)
    if max_width is not None:
        slider.setMaximumWidth(max_width)
    return slider


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


def style_coord_editor(editor: QLineEdit, *, width: int) -> None:
    """Apply the compact right-aligned coordinate-editor look to an existing line edit.

    Visual style (padding) lives in QSS via the ``coordEditor`` property selector,
    so this leaves ``objectName`` free for callers that look editors up by name.
    """
    editor.setProperty("coordEditor", "true")
    editor.setFixedHeight(26)
    editor.setFixedWidth(width)
    editor.setAlignment(Qt.AlignRight)


def make_coord_editor(*, width: int, parent=None) -> QLineEdit:
    """Create a compact right-aligned coordinate input styled via QSS."""
    editor = QLineEdit(parent)
    style_coord_editor(editor, width=width)
    return editor


def make_error_label(message: str = "", *, object_name: str = "ErrorLabel", parent=None) -> QLabel:
    """Hidden-by-default word-wrapping label for inline error/hint messages."""
    label = QLabel(message, parent)
    label.setObjectName(object_name)
    label.setWordWrap(True)
    label.hide()
    return label


def make_compact_action_button(
    text: str,
    *,
    tooltip: str = "",
    width: int = 42,
    object_name: str = "",
    compact: bool = False,
    size_policy: tuple[QSizePolicy.Policy, QSizePolicy.Policy] | None = None,
    parent=None,
) -> QPushButton:
    """Small fixed-width action button (e.g. 全选/反选/修改/删除 batch controls)."""
    button = QPushButton(text, parent)
    if object_name:
        button.setObjectName(object_name)
    if compact:
        button.setProperty("compact", True)
    if tooltip:
        button.setToolTip(tooltip)
    button.setFixedWidth(width)
    if size_policy is not None:
        button.setSizePolicy(*size_policy)
    return button


def color_swatch_qss(bg: str, fg: str, *, border: str = "rgba(255, 255, 255, 0.35)") -> str:
    """Inline QSS for a button whose background reflects a runtime-chosen color.

    This is intentionally inline (not a QSS object selector) because the colors
    vary per button and change as the user picks colors — a static selector
    cannot express it. Returns a string byte-equal to the previous hand-written one.
    """
    return f"background: {bg}; color: {fg}; border: 1px solid {border};"

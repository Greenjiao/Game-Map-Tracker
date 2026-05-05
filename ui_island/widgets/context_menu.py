"""Small helpers for consistently styled context menus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMenu

from ..design import theme


@dataclass(frozen=True)
class ContextMenuItem:
    text: str = ""
    callback: Callable[[], None] | None = None
    separator: bool = False
    enabled: bool = True
    visible: bool = True
    shortcut: str = ""

    @classmethod
    def separator_item(cls) -> "ContextMenuItem":
        return cls(separator=True)


class _ShortcutMenu(QMenu):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shortcut_actions: dict[str, object] = {}

    def add_shortcut_action(self, shortcut: str, action) -> None:
        key = _shortcut_key(shortcut)
        if key:
            self._shortcut_actions[key] = action

    def keyPressEvent(self, event) -> None:
        key = _shortcut_key(event.text())
        action = self._shortcut_actions.get(key)
        if action is not None and action.isEnabled() and action.isVisible():
            action.trigger()
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)


def _shortcut_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _context_menu_style(parent) -> str:
    candidates: list[str] = []
    if parent is not None:
        style = parent.styleSheet() if hasattr(parent, "styleSheet") else ""
        if style:
            candidates.append(style)
        window = parent.window() if hasattr(parent, "window") else None
        window_style = window.styleSheet() if window is not None and hasattr(window, "styleSheet") else ""
        if window_style:
            candidates.append(window_style)

    app = QApplication.instance()
    app_style = app.styleSheet() if app is not None else ""
    if app_style:
        candidates.append(app_style)

    for style in candidates:
        if "QMenu" in style:
            return style

    if candidates:
        return "\n".join(candidates + [theme.ISLAND_QSS])
    return theme.ISLAND_QSS


def show_context_menu(
    parent,
    global_pos,
    items: Iterable[ContextMenuItem],
    *,
    object_name: str = "",
) -> None:
    menu = _ShortcutMenu(parent)
    if object_name:
        menu.setObjectName(object_name)
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_NoSystemBackground, True)
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    menu.setAutoFillBackground(False)
    menu.setStyleSheet(_context_menu_style(parent))

    has_actions = False
    for item in items:
        if not item.visible:
            continue
        if item.separator:
            menu.addSeparator()
            continue
        action = menu.addAction(item.text)
        action.setEnabled(item.enabled)
        if item.shortcut:
            action.setShortcut(QKeySequence(item.shortcut))
            action.setShortcutVisibleInContextMenu(True)
            menu.add_shortcut_action(item.shortcut, action)
        has_actions = True
        if item.callback is not None:
            action.triggered.connect(lambda _checked=False, callback=item.callback: callback())

    if has_actions:
        window = parent.window() if parent is not None and hasattr(parent, "window") else parent
        previous_suspended = bool(getattr(window, "_hotkeys_suspended", False))
        hotkey_controller = getattr(window, "hotkey_controller", None)
        if hotkey_controller is not None and hasattr(hotkey_controller, "set_suspended"):
            hotkey_controller.set_suspended(True)
        try:
            menu.exec(global_pos)
        finally:
            if hotkey_controller is not None and hasattr(hotkey_controller, "set_suspended"):
                hotkey_controller.set_suspended(previous_suspended)

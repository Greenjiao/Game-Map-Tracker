"""Window interaction helper methods."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QScrollArea, QWidget


class InteractionController:
    def __init__(self, window) -> None:
        self.window = window

    def install_resize_filters(self, widget: QWidget) -> None:
        widget.installEventFilter(self.window)
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self.window)
            child.setMouseTracking(True)

    def nested_sidebar_scroll_area(self, widget: QWidget | None) -> QScrollArea | None:
        current = widget
        targets = (self.window.routes_scroll,)
        while current is not None:
            if current in targets:
                return current
            current = current.parentWidget()
        return None

    @staticmethod
    def consume_inner_scroll(area: QScrollArea, event) -> None:
        scrollbar = area.verticalScrollBar()
        if scrollbar is None:
            event.accept()
            return

        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()

        step = scrollbar.singleStep() or 20
        if delta != 0:
            if abs(delta) >= 120:
                scrollbar.setValue(scrollbar.value() - int(delta / 120) * step)
            else:
                scrollbar.setValue(scrollbar.value() - delta)
        event.accept()

    def sidebar_resize_hit(self, global_pos) -> bool:
        if self.window._sidebar_collapsed and not self.window.window_mode_controller.is_pause_mode():
            return False
        if not self.window.sidebar_shell.isVisible():
            return False
        local = self.window.sidebar_shell.mapFromGlobal(global_pos)
        return (
            0 <= local.x() <= self.window._SIDEBAR_RESIZE_MARGIN
            and 0 <= local.y() <= self.window.sidebar_shell.height()
        )

    def resize_sidebar(self, global_x: int) -> None:
        delta = global_x - self.window._sidebar_resize_start_x
        self.window._sidebar_width = max(self.window._SIDEBAR_MIN_WIDTH, self.window._sidebar_resize_start_width - delta)
        self.window.window_mode_controller.apply_sidebar_state()

    def resize_edges_at(self, global_pos) -> Qt.Edges:
        if self.window.isMaximized():
            return Qt.Edges()
        local = self.window.mapFromGlobal(global_pos)
        left = local.x() <= self.window._RESIZE_MARGIN
        right = local.x() >= self.window.width() - self.window._RESIZE_MARGIN
        top = local.y() <= self.window._RESIZE_MARGIN
        bottom = local.y() >= self.window.height() - self.window._RESIZE_MARGIN
        edges = Qt.Edges()
        if left:
            edges |= Qt.LeftEdge
        if right:
            edges |= Qt.RightEdge
        if top:
            edges |= Qt.TopEdge
        if bottom:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def cursor_for_edges(edges: Qt.Edges):
        if edges in (Qt.LeftEdge, Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges in (Qt.TopEdge, Qt.BottomEdge):
            return Qt.SizeVerCursor
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        return None

    def update_resize_cursor(self, global_pos) -> None:
        cursor = self.cursor_for_edges(self.resize_edges_at(global_pos))
        if cursor is None:
            if self.window._edge_cursor_active:
                self.window.unsetCursor()
                self.window._edge_cursor_active = False
            return
        self.window.setCursor(QCursor(cursor))
        self.window._edge_cursor_active = True

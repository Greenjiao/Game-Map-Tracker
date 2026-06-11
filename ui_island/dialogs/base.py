"""Reusable frameless dialog shell for island UI."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..design import qss

_LINK_STYLE = """
<style>
a {
  color: #8fd3ff;
  text-decoration: underline;
  font-weight: 600;
}
</style>
"""


class StyledDialogBase(QDialog):
    def __init__(self, parent, title: str, *, modal: bool = True, min_width: int = 340, max_width: int = 460) -> None:
        super().__init__(parent)
        qss.ensure_tooltip_style()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.setModal(modal)

        self._drag_offset: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("IslandRoot")
        self.shell.setMinimumWidth(min_width)
        self.shell.setMaximumWidth(max_width)
        self.shell_layout = QVBoxLayout(self.shell)
        self.shell_layout.setContentsMargins(18, 12, 18, 14)
        self.shell_layout.setSpacing(10)
        root.addWidget(self.shell)

        self.title_bar = QWidget()
        self._title_bar = self.title_bar
        self.title_bar.setToolTip(title)
        title_row = QHBoxLayout(self.title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogTitleLabel")
        self.title_label.setToolTip(title)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self.title_label)
        title_row.addStretch()
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WindowControl")
        self.close_btn.clicked.connect(self.reject)
        title_row.addWidget(self.close_btn)
        self.shell_layout.addWidget(self.title_bar)

    def add_action_row(
        self,
        *,
        confirm_text: str | None = None,
        cancel_text: str | None = None,
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        confirm_default: bool = True,
    ) -> tuple[QPushButton | None, QPushButton | None]:
        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = None
        if cancel_text:
            cancel_btn = QPushButton(cancel_text)
            cancel_btn.clicked.connect(on_cancel or self.reject)
            button_row.addWidget(cancel_btn)

        confirm_btn = None
        if confirm_text:
            confirm_btn = QPushButton(confirm_text)
            confirm_btn.setDefault(confirm_default)
            confirm_btn.clicked.connect(on_confirm or self.accept)
            button_row.addWidget(confirm_btn)

        self.shell_layout.addLayout(button_row)
        return confirm_btn, cancel_btn

    def _is_on_title_bar(self, global_pos: QPoint) -> bool:
        local = self._title_bar.mapFromGlobal(global_pos)
        return self._title_bar.rect().contains(local)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._is_on_title_bar(event.globalPosition().toPoint()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)


class StyledMessage(StyledDialogBase):
    def __init__(self, parent, title: str, message: str, *, allow_links: bool = False) -> None:
        super().__init__(parent, title)
        body = QLabel((_LINK_STYLE + message) if allow_links else message)
        body.setObjectName("BodyLabel")
        body.setWordWrap(True)
        if allow_links:
            body.setTextFormat(Qt.RichText)
            body.setOpenExternalLinks(True)
            body.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard
            )
        else:
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(body, stretch=1)

        self.add_action_row(confirm_text="确定")
        self.adjustSize()


class StyledConfirm(StyledDialogBase):
    def __init__(self, parent, title: str, message: str, confirm_text: str = "确定", cancel_text: str = "取消") -> None:
        super().__init__(parent, title)
        body = QLabel(message)
        body.setObjectName("BodyLabel")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(body, stretch=1)

        self.add_action_row(confirm_text=confirm_text, cancel_text=cancel_text)
        self.adjustSize()


def center_dialog(dialog: QDialog, parent) -> None:
    if parent is None:
        return
    parent_geo = parent.frameGeometry()
    dialog.move(
        parent_geo.center().x() - dialog.width() // 2,
        parent_geo.center().y() - dialog.height() // 2,
    )


def _anchor_global_rect(anchor: QWidget) -> tuple[int, int, int, int]:
    top_left = anchor.mapToGlobal(QPoint(0, 0))
    return top_left.x(), top_left.y(), anchor.width(), anchor.height()


def place_left_of(dialog: QDialog, anchor: QWidget) -> None:
    anchor_left, anchor_top, _anchor_width, _anchor_height = _anchor_global_rect(anchor)
    screen = anchor.screen() if hasattr(anchor, "screen") else None
    avail = screen.availableGeometry() if screen is not None else None

    target_x = anchor_left - dialog.width()
    target_y = anchor_top
    if avail is not None:
        if target_x < avail.left():
            target_x = avail.left()
        target_y = max(avail.top(), min(target_y, avail.bottom() - dialog.height()))
    dialog.move(target_x, target_y)


def place_right_of(dialog: QDialog, anchor: QWidget) -> None:
    anchor_left, anchor_top, anchor_width, _anchor_height = _anchor_global_rect(anchor)
    screen = anchor.screen() if hasattr(anchor, "screen") else None
    avail = screen.availableGeometry() if screen is not None else None

    target_x = anchor_left + anchor_width
    target_y = anchor_top
    if avail is not None:
        target_x = max(avail.left(), min(target_x, avail.right() - dialog.width()))
        target_y = max(avail.top(), min(target_y, avail.bottom() - dialog.height()))
    dialog.move(target_x, target_y)

"""Qt minimap calibration flow for island UI."""

from __future__ import annotations

from typing import Optional

import mss
import numpy as np

import config
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget

from . import StyledDialogBase
from ..design import qss

_DEFAULT_SIZE = 150
_MIN_SIZE = 80
_SCROLL_STEP = 10


class _SelectorOverlay(QWidget):
    confirm_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, x: int, y: int, size: int) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowOpacity(0.55)
        self.setCursor(Qt.SizeAllCursor)

        self._size = max(_MIN_SIZE, int(size))
        self.setGeometry(int(x), int(y), self._size, self._size)
        self._drag_offset: Optional[QPoint] = None

    def region(self) -> tuple[int, int, int]:
        geom = self.frameGeometry()
        ratio = self.devicePixelRatioF() or 1.0
        return (
            int(round(geom.x() * ratio)),
            int(round(geom.y() * ratio)),
            int(round(self._size * ratio)),
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        pen = QPen(QColor("#00FF00"))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawEllipse(3, 3, self._size - 6, self._size - 6)

        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, self._size // 2, self._size, self._size // 2)
        painter.drawLine(self._size // 2, 0, self._size // 2, self._size)

        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        painter.drawText(QRect(0, 6, self._size, 18), Qt.AlignCenter, "左键拖动 | 滚轮缩放")
        painter.setPen(QColor("#ffd60a"))
        painter.drawText(QRect(0, self._size - 24, self._size, 18), Qt.AlignCenter, "按 回车/双击 确认截图")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.confirm_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        step = _SCROLL_STEP if event.angleDelta().y() > 0 else -_SCROLL_STEP
        self._resize_by(step)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm_requested.emit()
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)

    def _resize_by(self, delta: int) -> None:
        new_size = max(_MIN_SIZE, self._size + delta)
        if new_size == self._size:
            return
        cx = self.x() + self._size // 2
        cy = self.y() + self._size // 2
        self._size = new_size
        self.setGeometry(cx - new_size // 2, cy - new_size // 2, new_size, new_size)
        self.update()


def _show_window_on_top(widget: QWidget) -> None:
    widget.show()
    widget.raise_()
    widget.activateWindow()
    widget.setFocus(Qt.ActiveWindowFocusReason)


class _PreviewDialog(StyledDialogBase):
    retake_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent, pixmap: QPixmap, x: int, y: int, size: int) -> None:
        super().__init__(parent, "确认小地图截取区域", modal=True, min_width=340, max_width=520)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.close_btn.clicked.disconnect()
        self.close_btn.clicked.connect(self._on_close)

        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setStyleSheet("background: black; border-radius: 8px;")
        preview.setPixmap(pixmap)
        self.shell_layout.addWidget(preview, alignment=Qt.AlignCenter)

        info = QLabel(f"X: {x}   |   Y: {y}   |   尺寸: {size} × {size}")
        info.setObjectName("FieldLabel")
        info.setAlignment(Qt.AlignCenter)
        self.shell_layout.addWidget(info)

        self.add_action_row(confirm_text="确定", cancel_text="重新截取", on_cancel=self._on_retake)

    def _on_retake(self) -> None:
        self.retake_requested.emit()
        self.reject()

    def _on_close(self) -> None:
        self.cancel_requested.emit()
        self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._on_close()
            return
        super().keyPressEvent(event)


class MinimapCalibrator:
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._parent = parent
        self._overlay: Optional[_SelectorOverlay] = None
        self._saved = False

    def run(self) -> bool:
        app = QApplication.instance()
        prev_quit_flag = None
        if app is not None:
            prev_quit_flag = app.quitOnLastWindowClosed()
            app.setQuitOnLastWindowClosed(False)

        try:
            x, y, size = self._initial_region()
            self._overlay = _SelectorOverlay(x, y, size)
            self._overlay.confirm_requested.connect(self._request_preview)
            self._overlay.cancel_requested.connect(self._cancel)
            _show_window_on_top(self._overlay)

            self._loop = QEventLoop()
            self._overlay.destroyed.connect(lambda _=None: self._loop.quit())
            self._loop.exec()
        finally:
            if app is not None and prev_quit_flag is not None:
                app.setQuitOnLastWindowClosed(prev_quit_flag)
        return self._saved

    @staticmethod
    def _initial_region() -> tuple[int, int, int]:
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        if ratio <= 0:
            ratio = 1.0

        minimap = getattr(config, "MINIMAP", None) or {}
        try:
            x_phys = int(minimap.get("left"))
            y_phys = int(minimap.get("top"))
            size_phys = int(minimap.get("width"))
            if size_phys < _MIN_SIZE:
                raise ValueError
            x = int(round(x_phys / ratio))
            y = int(round(y_phys / ratio))
            size = max(_MIN_SIZE, int(round(size_phys / ratio)))
            return _clamp_to_screen(x, y, size)
        except (TypeError, ValueError):
            pass

        available = screen.availableGeometry() if screen is not None else None
        size = _DEFAULT_SIZE
        if available is None:
            return (100, 100, size)
        return (
            available.x() + (available.width() - size) // 2,
            available.y() + (available.height() - size) // 2,
            size,
        )

    def _request_preview(self) -> None:
        assert self._overlay is not None
        self._overlay.hide()
        QTimer.singleShot(120, self._show_preview)

    def _show_preview(self) -> None:
        assert self._overlay is not None
        x, y, size = self._overlay.region()
        pixmap = _grab_region(x, y, size)
        dialog = _PreviewDialog(self._parent, pixmap, x, y, size)

        cancelled = {"value": False}

        def _on_cancel():
            cancelled["value"] = True

        dialog.retake_requested.connect(self._resume_overlay)
        dialog.cancel_requested.connect(_on_cancel)

        _show_window_on_top(dialog)
        accepted = dialog.exec() == QDialog.Accepted
        if accepted:
            self._save_config(x, y, size)
            self._saved = True
            self._cancel()
        elif cancelled["value"]:
            self._cancel()

    def _resume_overlay(self) -> None:
        if self._overlay is not None:
            _show_window_on_top(self._overlay)

    def _cancel(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    @staticmethod
    def _save_config(x: int, y: int, size: int) -> None:
        config.save_config(
            {
                "MINIMAP": {
                    "top": int(y),
                    "left": int(x),
                    "width": int(size),
                    "height": int(size),
                }
            }
        )


def _grab_region(x: int, y: int, size: int) -> QPixmap:
    with mss.mss() as capture:
        monitor = {"top": y, "left": x, "width": size, "height": size}
        raw = capture.grab(monitor)
        image = np.asarray(raw)
        height, width = image.shape[:2]
        rgb = image[:, :, [2, 1, 0]].copy()
        qimage = QImage(rgb.data, width, height, width * 3, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimage)


def _clamp_to_screen(x: int, y: int, size: int) -> tuple[int, int, int]:
    screen = QApplication.primaryScreen()
    available = screen.availableGeometry() if screen is not None else None
    if available is None:
        return x, y, size
    size = max(_MIN_SIZE, min(size, available.width(), available.height()))
    max_x = max(available.left(), available.right() - size)
    max_y = max(available.top(), available.bottom() - size)
    return (
        min(max(available.left(), x), max_x),
        min(max(available.top(), y), max_y),
        size,
    )


def run_minimap_calibrator(parent: Optional[QWidget] = None) -> bool:
    return MinimapCalibrator(parent).run()

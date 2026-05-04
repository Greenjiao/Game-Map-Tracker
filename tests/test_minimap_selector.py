import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from ui_island.dialogs.minimap_selector import (
    MinimapCalibrator,
    _PreviewDialog,
    _SelectorOverlay,
    _show_window_on_top,
)


class MinimapSelectorWindowLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_preview_dialog_stays_on_top_of_main_overlay_window(self) -> None:
        pixmap = QPixmap(80, 80)
        dialog = _PreviewDialog(None, pixmap, 10, 20, 80)
        try:
            flags = dialog.windowFlags()
            self.assertTrue(flags & Qt.WindowStaysOnTopHint)
            self.assertTrue(flags & Qt.Tool)
            self.assertTrue(dialog.isModal())
        finally:
            dialog.close()

    def test_selector_overlay_keeps_topmost_window_flag(self) -> None:
        overlay = _SelectorOverlay(10, 20, 120)
        try:
            flags = overlay.windowFlags()
            self.assertTrue(flags & Qt.WindowStaysOnTopHint)
            self.assertTrue(flags & Qt.FramelessWindowHint)
        finally:
            overlay.close()

    def test_show_window_on_top_raises_activates_and_focuses_window(self) -> None:
        widget = MagicMock()

        _show_window_on_top(widget)

        widget.show.assert_called_once_with()
        widget.raise_.assert_called_once_with()
        widget.activateWindow.assert_called_once_with()
        widget.setFocus.assert_called_once_with(Qt.ActiveWindowFocusReason)

    def test_resume_overlay_uses_topmost_show_flow(self) -> None:
        overlay = MagicMock()
        calibrator = MinimapCalibrator()
        calibrator._overlay = overlay

        calibrator._resume_overlay()

        overlay.show.assert_called_once_with()
        overlay.raise_.assert_called_once_with()
        overlay.activateWindow.assert_called_once_with()
        overlay.setFocus.assert_called_once_with(Qt.ActiveWindowFocusReason)


if __name__ == "__main__":
    unittest.main()

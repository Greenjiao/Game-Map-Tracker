import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ui_island.widgets.context_menu import _ShortcutMenu


class ContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_shortcut_menu_triggers_action_from_number_key(self) -> None:
        menu = _ShortcutMenu()
        triggered: list[bool] = []
        action = menu.addAction("采集点 (按1)")
        action.triggered.connect(lambda _checked=False: triggered.append(True))
        menu.add_shortcut_action("1", action)

        event = QKeyEvent(QEvent.KeyPress, Qt.Key_1, Qt.NoModifier, "1")
        menu.keyPressEvent(event)

        self.assertTrue(event.isAccepted())
        self.assertEqual(triggered, [True])


if __name__ == "__main__":
    unittest.main()

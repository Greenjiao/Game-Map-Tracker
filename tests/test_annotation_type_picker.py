import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from ui_island.dialogs.annotation_type_picker import AnnotationTypePickerDialog
from ui_island.widgets.annotation_type_widgets import AnnotationGroupSection


class _PickerParent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.annotation_group_expanded: dict[str, bool] = {"Group A": False}
        self.saved_states: list[dict[str, bool]] = []

    def _on_annotation_group_expanded_changed(self, expanded: dict[str, bool]) -> None:
        self.saved_states.append(dict(expanded))


class AnnotationTypePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _items(self) -> list[dict]:
        return [
            {"typeId": "a-1", "type": "Alpha", "group": "Group A", "count": 1},
            {"typeId": "a-2", "type": "Beta", "group": "Group A", "count": 2},
            {"typeId": "a-3", "type": "Delta", "group": "Group A", "count": 4},
            {"typeId": "b-1", "type": "Gamma", "group": "Group B", "count": 3},
        ]

    def _sections(self, dialog: AnnotationTypePickerDialog) -> list[AnnotationGroupSection]:
        return dialog.findChildren(AnnotationGroupSection)

    def test_picker_uses_modal_dialog_shell(self) -> None:
        dialog = AnnotationTypePickerDialog(None, self._items(), "")

        self.assertTrue(dialog.isModal())

    def test_picker_renders_collapsible_groups_with_three_columns(self) -> None:
        dialog = AnnotationTypePickerDialog(None, self._items(), "")
        sections = self._sections(dialog)

        self.assertEqual([section.group_name for section in sections], ["Group A", "Group B"])
        self.assertEqual(sections[0].header.text(), "▾ Group A")
        self.assertIsNotNone(sections[0].grid.itemAtPosition(0, 2).widget())

    def test_picker_uses_shared_group_state_and_saves_changes(self) -> None:
        parent = _PickerParent()
        dialog = AnnotationTypePickerDialog(parent, self._items(), "")
        section = self._sections(dialog)[0]

        self.assertEqual(section.header.text(), "▸ Group A")
        self.assertTrue(section.body.isHidden())

        section.header.click()

        self.assertEqual(parent.annotation_group_expanded["Group A"], True)
        self.assertEqual(parent.saved_states[-1], {"Group A": True})
        self.assertEqual(section.header.text(), "▾ Group A")

    def test_current_type_is_checked_and_click_accepts_selection(self) -> None:
        dialog = AnnotationTypePickerDialog(None, self._items(), "a-2")
        section = self._sections(dialog)[0]
        button = section.grid.itemAtPosition(0, 1).widget()

        self.assertIsInstance(button, QPushButton)
        self.assertTrue(button.isChecked())
        self.assertTrue(button.property("selected"))

        button.click()

        self.assertEqual(dialog.selected_item()["typeId"], "a-2")
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_empty_picker_shows_no_group_sections(self) -> None:
        dialog = AnnotationTypePickerDialog(None, [], "")

        self.assertEqual(self._sections(dialog), [])


if __name__ == "__main__":
    unittest.main()

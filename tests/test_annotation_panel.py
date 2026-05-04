import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ui_island.design import strings, theme
from ui_island.widgets.annotation_panel import AnnotationPanel
from ui_island.widgets.annotation_type_widgets import AnnotationGroupSection


class AnnotationPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _panel_with_types(self) -> AnnotationPanel:
        panel = AnnotationPanel()
        panel._types = [
            {"typeId": "a-1", "type": "Alpha", "group": "Group A", "count": 1},
            {"typeId": "a-2", "type": "Beta", "group": "Group A", "count": 2},
            {"typeId": "b-1", "type": "Gamma", "group": "Group B", "count": 3},
        ]
        return panel

    def _panel_with_many_types(self) -> AnnotationPanel:
        panel = AnnotationPanel()
        panel._types = [
            {
                "typeId": f"type-{index}",
                "type": f"Type {index}",
                "group": "Large Group",
                "count": index,
            }
            for index in range(80)
        ]
        return panel

    def _list_widgets(self, panel: AnnotationPanel) -> list[QWidget]:
        widgets: list[QWidget] = []
        for index in range(panel._list_layout.count()):
            widget = panel._list_layout.itemAt(index).widget()
            if widget is not None:
                widgets.append(widget)
        return widgets

    def _top_sections(self, panel: AnnotationPanel) -> list[AnnotationGroupSection]:
        return [widget for widget in self._list_widgets(panel) if isinstance(widget, AnnotationGroupSection)]

    def _section_rows(self, section: AnnotationGroupSection) -> list[QWidget]:
        widgets: list[QWidget] = []
        for index in range(section.grid.count()):
            widget = section.grid.itemAt(index).widget()
            if widget is not None:
                widgets.append(widget)
        return widgets

    def _nested_sections(self, section: AnnotationGroupSection) -> list[AnnotationGroupSection]:
        return [widget for widget in self._section_rows(section) if isinstance(widget, AnnotationGroupSection)]

    def test_panel_does_not_accept_focus_when_shown(self) -> None:
        panel = AnnotationPanel()

        self.assertTrue(panel.testAttribute(Qt.WA_ShowWithoutActivating))
        self.assertTrue(bool(panel.windowFlags() & Qt.WindowDoesNotAcceptFocus))

    def test_header_button_text_is_compact_and_toggle_is_removed(self) -> None:
        panel = AnnotationPanel()

        self.assertEqual(panel._show_all_btn.text(), "全显")
        self.assertEqual(panel._hide_all_btn.text(), "全隐")
        self.assertFalse(hasattr(panel, "_toggle_btn"))

    def test_expanded_hint_renders_source_link(self) -> None:
        panel = AnnotationPanel()
        label, url = strings.ANNOTATION_SOURCE_LINKS[0]

        self.assertEqual(panel._title.text(), "标注")
        self.assertFalse(panel._hint.isHidden())
        self.assertEqual(panel._hint.toolTip(), strings.ANNOTATION_ROUTE_HINT)
        self.assertIn("感谢17173的地图标注工作者们", panel._hint.text())
        self.assertIn(f'<a href="{url}"', panel._hint.text())
        self.assertIn(f">{label}</a>", panel._hint.text())
        self.assertEqual(panel._hint.textFormat(), Qt.RichText)
        self.assertTrue(panel._hint.openExternalLinks())
        self.assertTrue(panel._hint.textInteractionFlags() & Qt.LinksAccessibleByMouse)

    def test_compact_hint_uses_same_title_and_source_link(self) -> None:
        panel = AnnotationPanel()
        label, url = strings.ANNOTATION_SOURCE_LINKS[0]

        panel.set_compact_hint(True)

        self.assertEqual(panel._title.text(), "标注")
        self.assertIn(panel._title, panel._drag_handles)
        self.assertFalse(panel._hint.isHidden())
        self.assertNotIn("感谢17173的地图标注工作者们", panel._hint.text())
        self.assertIn(strings.ANNOTATION_ROUTE_HINT_COMPACT.replace(label, ""), panel._hint.text())
        self.assertIn(f'<a href="{url}"', panel._hint.text())
        self.assertIn(f">{label}</a>", panel._hint.text())
        self.assertEqual(panel._hint.textFormat(), Qt.RichText)
        self.assertTrue(panel._hint.openExternalLinks())
        self.assertTrue(panel._hint.textInteractionFlags() & Qt.LinksAccessibleByMouse)

    def test_hint_is_passthrough_drag_handle_so_links_can_be_clicked(self) -> None:
        panel = AnnotationPanel()

        self.assertNotIn(panel._hint, panel._drag_handles)
        self.assertIn(panel._hint, panel._drag_passthrough_handles)

    def test_hint_click_without_drag_is_released_to_link_label(self) -> None:
        class _MouseEvent:
            def __init__(self, event_type, global_x: int, global_y: int, button=Qt.LeftButton) -> None:
                self._event_type = event_type
                self._global_pos = QPointF(global_x, global_y)
                self._button = button
                self.accepted = False

            def type(self):
                return self._event_type

            def button(self):
                return self._button

            def globalPosition(self):
                return self._global_pos

            def accept(self) -> None:
                self.accepted = True

        panel = AnnotationPanel()

        pressed = panel.eventFilter(panel._hint, _MouseEvent(QEvent.MouseButtonPress, 15, 15))
        released = panel.eventFilter(panel._hint, _MouseEvent(QEvent.MouseButtonRelease, 15, 15))

        self.assertFalse(pressed)
        self.assertFalse(released)

    def test_hint_drag_moves_panel_and_consumes_release(self) -> None:
        class _MouseEvent:
            def __init__(self, event_type, global_x: int, global_y: int, button=Qt.LeftButton) -> None:
                self._event_type = event_type
                self._global_pos = QPointF(global_x, global_y)
                self._button = button
                self.accepted = False

            def type(self):
                return self._event_type

            def button(self):
                return self._button

            def globalPosition(self):
                return self._global_pos

            def accept(self) -> None:
                self.accepted = True

        panel = AnnotationPanel()
        panel.move(10, 10)
        emitted: list[tuple[int, int]] = []
        panel.drag_finished.connect(lambda x, y: emitted.append((x, y)))

        pressed = panel.eventFilter(panel._hint, _MouseEvent(QEvent.MouseButtonPress, 15, 15))
        moved = panel.eventFilter(panel._hint, _MouseEvent(QEvent.MouseMove, 35, 45, Qt.NoButton))
        released = panel.eventFilter(panel._hint, _MouseEvent(QEvent.MouseButtonRelease, 35, 45))

        self.assertFalse(pressed)
        self.assertTrue(moved)
        self.assertTrue(released)
        self.assertEqual(emitted, [(30, 40)])

    def test_dragging_header_emits_final_position_on_release(self) -> None:
        class _MouseEvent:
            def __init__(self, event_type, global_x: int, global_y: int, button=Qt.LeftButton) -> None:
                self._event_type = event_type
                self._global_pos = QPointF(global_x, global_y)
                self._button = button
                self.accepted = False

            def type(self):
                return self._event_type

            def button(self):
                return self._button

            def globalPosition(self):
                return self._global_pos

            def accept(self) -> None:
                self.accepted = True

        panel = AnnotationPanel()
        panel.move(10, 10)
        emitted: list[tuple[int, int]] = []
        panel.drag_finished.connect(lambda x, y: emitted.append((x, y)))

        panel.eventFilter(panel._header, _MouseEvent(QEvent.MouseButtonPress, 15, 15))
        panel.eventFilter(panel._header, _MouseEvent(QEvent.MouseMove, 35, 45, Qt.NoButton))
        panel.eventFilter(panel._header, _MouseEvent(QEvent.MouseButtonRelease, 35, 45))

        self.assertEqual(emitted, [(30, 40)])

    def test_scroll_height_tracks_small_content_when_custom_section_is_empty(self) -> None:
        panel = self._panel_with_types()

        panel._render()

        self.assertLess(panel._scroll.minimumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)
        self.assertEqual(panel._scroll.maximumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)

    def test_scroll_height_caps_large_content_at_maximum(self) -> None:
        panel = self._panel_with_many_types()

        panel._render()

        self.assertEqual(panel._scroll.minimumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)
        self.assertEqual(panel._scroll.maximumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)

    def test_scroll_height_recomputes_after_outer_group_collapse(self) -> None:
        panel = self._panel_with_many_types()
        panel._render()
        section = self._top_sections(panel)[0]

        section.header.click()

        self.assertLess(panel._scroll.minimumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)
        self.assertEqual(panel._scroll.maximumHeight(), theme.ANNOTATION_PANEL_SCROLL_HEIGHT)

    def test_panel_renders_two_layered_top_level_sections(self) -> None:
        panel = self._panel_with_types()

        panel._render()

        top_sections = self._top_sections(panel)
        self.assertEqual([section.group_name for section in top_sections], ["标注", "标注方案预设"])
        self.assertEqual(top_sections[0].header.text(), "▾ 标注")
        self.assertEqual(top_sections[1].header_label.text(), "▾ 标注方案预设")
        self.assertTrue(all(section.header.property("compact") for section in top_sections))
        self.assertEqual([section.property("annotationLayer") for section in top_sections], ["pulled", "custom"])
        self.assertEqual([section.header.property("annotationLayer") for section in top_sections], ["pulled", "custom"])
        self.assertIsNotNone(top_sections[1].add_btn)

        pulled_groups = self._nested_sections(top_sections[0])
        custom_groups = self._nested_sections(top_sections[1])
        self.assertEqual([section.group_name for section in pulled_groups], ["Group A", "Group B"])
        self.assertEqual(custom_groups, [])

    def test_preset_add_button_emits_create_request(self) -> None:
        panel = self._panel_with_types()
        emitted: list[bool] = []
        panel.preset_create_requested.connect(lambda: emitted.append(True))
        panel._render()

        custom_section = self._top_sections(panel)[1]
        custom_section.add_btn.click()

        self.assertEqual(emitted, [True])

    def test_preset_row_renders_actions_and_emits_edit_delete(self) -> None:
        panel = self._panel_with_types()
        panel.set_presets([{"id": "preset-1", "name": "Preset A", "type_ids": ["a-1", "b-1"]}])
        edited: list[str] = []
        deleted: list[str] = []
        panel.preset_edit_requested.connect(lambda preset_id: edited.append(preset_id))
        panel.preset_delete_requested.connect(lambda preset_id: deleted.append(preset_id))

        custom_section = self._top_sections(panel)[1]
        row = self._section_rows(custom_section)[0]
        buttons = row.findChildren(QPushButton)

        self.assertEqual([button.text() for button in buttons], ["Preset A", "全选", "反选", "修改", "删除"])

        buttons[3].click()
        buttons[4].click()

        self.assertEqual(edited, ["preset-1"])
        self.assertEqual(deleted, ["preset-1"])

    def test_preset_name_click_toggles_only_available_preset_types(self) -> None:
        panel = self._panel_with_types()
        panel.set_preferences(["b-1"])
        panel.set_presets([{"id": "preset-1", "name": "Preset A", "type_ids": ["a-1", "missing"]}])
        emitted: list[list[str]] = []
        panel.selection_changed.connect(lambda ids: emitted.append(list(ids)))

        custom_section = self._top_sections(panel)[1]
        name_button = self._section_rows(custom_section)[0].findChildren(QPushButton)[0]
        name_button.click()

        self.assertEqual(emitted[-1], ["b-1", "a-1"])

        custom_section = self._top_sections(panel)[1]
        name_button = self._section_rows(custom_section)[0].findChildren(QPushButton)[0]
        name_button.click()

        self.assertEqual(emitted[-1], ["b-1"])

    def test_preset_select_all_and_invert_affect_only_preset_types(self) -> None:
        panel = self._panel_with_types()
        panel.set_preferences(["a-1", "b-1"])
        panel.set_presets([{"id": "preset-1", "name": "Preset A", "type_ids": ["a-1", "a-2"]}])
        emitted: list[list[str]] = []
        panel.selection_changed.connect(lambda ids: emitted.append(list(ids)))

        custom_section = self._top_sections(panel)[1]
        buttons = self._section_rows(custom_section)[0].findChildren(QPushButton)
        buttons[1].click()

        self.assertEqual(emitted[-1], ["a-1", "b-1", "a-2"])

        custom_section = self._top_sections(panel)[1]
        buttons = self._section_rows(custom_section)[0].findChildren(QPushButton)
        buttons[2].click()

        self.assertEqual(emitted[-1], ["b-1"])

    def test_outer_group_header_click_collapses_without_rerender(self) -> None:
        saved_states: list[dict[str, bool]] = []
        panel = self._panel_with_types()
        panel.set_group_expanded_state({}, lambda expanded: saved_states.append(dict(expanded)))
        panel._render()
        section = self._top_sections(panel)[0]

        section.header.click()

        self.assertIs(self._top_sections(panel)[0], section)
        self.assertEqual(panel._group_expanded["标注"], False)
        self.assertEqual(saved_states[-1], {"标注": False})
        self.assertEqual(section.header.text(), "▸ 标注")
        self.assertTrue(section.body.isHidden())

    def test_inner_group_header_click_updates_state(self) -> None:
        saved_states: list[dict[str, bool]] = []
        panel = self._panel_with_types()
        panel.set_group_expanded_state({}, lambda expanded: saved_states.append(dict(expanded)))
        panel._render()
        pulled_group = self._nested_sections(self._top_sections(panel)[0])[0]

        pulled_group.header.click()

        self.assertIs(self._nested_sections(self._top_sections(panel)[0])[0], pulled_group)
        self.assertEqual(panel._group_expanded["Group A"], False)
        self.assertEqual(saved_states[-1], {"Group A": False})
        self.assertEqual(pulled_group.header.text(), "▸ Group A")
        self.assertTrue(pulled_group.body.isHidden())

    def test_group_collapse_state_survives_selection_rerender(self) -> None:
        panel = self._panel_with_types()
        panel.set_group_expanded_state({"Group A": False}, None)
        panel._render()
        panel._toggle_type("b-1")

        pulled_group = self._nested_sections(self._top_sections(panel)[0])[0]
        self.assertEqual(pulled_group.header.text(), "▸ Group A")
        self.assertTrue(pulled_group.body.isHidden())

    def test_bulk_buttons_emit_selected_type_ids_only(self) -> None:
        panel = self._panel_with_types()
        emitted: list[list[str]] = []
        panel.selection_changed.connect(lambda ids: emitted.append(list(ids)))

        panel._select_all_types()
        self.assertEqual(panel._selected_type_ids, ["a-1", "a-2", "b-1"])
        self.assertEqual(emitted[-1], ["a-1", "a-2", "b-1"])

        panel._clear_all_types()
        self.assertEqual(panel._selected_type_ids, [])
        self.assertEqual(emitted[-1], [])


if __name__ == "__main__":
    unittest.main()

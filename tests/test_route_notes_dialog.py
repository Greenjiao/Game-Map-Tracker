import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QSplitter,
    QStyle,
    QStyleOptionSlider,
    QWidget,
)

from ui_island.services.route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL
from ui_island.dialogs.route_notes_dialog import (
    _NODE_ICON_SIZE,
    _NODE_NAME_MIN_WIDTH,
    _NODE_PANEL_SPACING,
    _NODE_SCROLL_MIN_HEIGHT,
    _ROUTE_NOTES_DIALOG_INITIAL_HEIGHT,
    _ROUTE_NOTES_DIALOG_INITIAL_WIDTH,
    _ROUTE_NOTES_MIN_OPACITY_PERCENT,
    _ROUTE_NOTES_OPACITY_SLIDER_MAX_WIDTH,
    _ROUTE_NOTES_OPACITY_SLIDER_MIN_WIDTH,
    _ROUTE_NOTES_RIGHT_MIN_WIDTH,
    _TITLE_ROW_HEIGHT,
    RouteNotesDialog,
    apply_route_node_auto_labels,
    route_node_display_name,
    route_node_display_names,
    route_node_icon_pixmap,
    summarize_route_nodes,
    RouteNodeEditorPanel,
)


class RouteNotesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._save_config_patcher = patch("ui_island.dialogs.route_notes_dialog.config.save_config")
        self._mock_save_config = self._save_config_patcher.start()

    def tearDown(self) -> None:
        self._save_config_patcher.stop()

    def test_route_node_display_name_falls_back_to_indexed_name(self) -> None:
        self.assertEqual(route_node_display_name({}, 2), "节点 3")
        self.assertEqual(route_node_display_name({"typeId": "ore", "type": "矿石"}, 0), "矿石 1")
        self.assertEqual(route_node_display_name({"node_type": "teleport"}, 0), "传送点 1")
        self.assertEqual(route_node_display_name({"label": " 黑矿 "}, 0), "黑矿")

    def test_apply_route_node_auto_labels_counts_annotation_and_node_types(self) -> None:
        labeled = apply_route_node_auto_labels([
            {"x": 1, "y": 1, "typeId": "chest", "type": "宝箱"},
            {"x": 2, "y": 2, "label": "自定义", "typeId": "chest", "type": "宝箱"},
            {"x": 3, "y": 3, "label": "宝箱 9", "typeId": "chest", "type": "宝箱"},
            {"x": 4, "y": 4, "node_type": "teleport"},
            {"x": 5, "y": 5, "label": "节点 99", "node_type": "teleport"},
            {"x": 6, "y": 6, "node_type": "virtual"},
            {"x": 7, "y": 7},
        ])

        self.assertEqual(
            [point.get("label") for point in labeled],
            ["宝箱 1", "自定义", "宝箱 3", "传送点 1", "传送点 2", "引路点 1", "节点 7"],
        )

    def test_route_node_display_names_use_route_order_counts(self) -> None:
        names = route_node_display_names([
            {"x": 1, "y": 1, "label": "宝箱 9", "typeId": "chest", "type": "宝箱"},
            {"x": 2, "y": 2, "typeId": "chest", "type": "宝箱"},
            {"x": 3, "y": 3, "node_type": "collect"},
        ])

        self.assertEqual(names, ["宝箱 1", "宝箱 2", "采集点 1"])

    def test_missing_icon_uses_route_color_fallback_pixmap(self) -> None:
        pixmap, fallback = route_node_icon_pixmap({"icon_path": "missing.png"}, "#123456")

        self.assertTrue(fallback)
        self.assertFalse(pixmap.isNull())

    def test_summary_counts_node_types_and_annotation_types(self) -> None:
        summary = summarize_route_nodes([
            {"node_type": "collect", "typeId": "ore", "type": "矿石"},
            {"node_type": "teleport"},
            {"node_type": "virtual", "typeId": "ore", "type": "矿石"},
            {"node_type": "invalid", "type": "宝箱"},
        ])

        self.assertEqual(summary["node_counts"][NODE_TYPE_COLLECT], 2)
        self.assertEqual(summary["node_counts"][NODE_TYPE_TELEPORT], 1)
        self.assertEqual(summary["node_counts"][NODE_TYPE_VIRTUAL], 1)
        self.assertEqual(
            [(item["label"], item["count"]) for item in summary["annotations"]],
            [("矿石", 2), ("宝箱", 1)],
        )

    def test_dialog_renders_node_rows_with_fallback_icons(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 2}, {"label": "已命名", "icon_path": "missing.png"}],
        )

        names = [editor.text() for editor in dialog.findChildren(QLineEdit, "RouteNotesNodeName")]
        icons = dialog.findChildren(QPushButton, "RouteNotesNodeIcon")
        name_inputs = dialog.findChildren(QLineEdit, "RouteNotesNodeName")

        self.assertEqual(names, ["节点 1", "已命名"])
        self.assertTrue(all(editor.minimumWidth() == _NODE_NAME_MIN_WIDTH for editor in name_inputs))
        self.assertEqual([icon.property("fallbackIcon") for icon in icons], [True, True])
        self.assertTrue(all(icon.iconSize() == QSize(_NODE_ICON_SIZE, _NODE_ICON_SIZE) for icon in icons))

    def test_node_panel_hydrates_annotation_icon_path_without_persisting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            icon_path = os.path.join(tmpdir, "ore.png")
            pixmap = QPixmap(_NODE_ICON_SIZE, _NODE_ICON_SIZE)
            pixmap.fill(QColor("#ff0000"))
            self.assertTrue(pixmap.save(icon_path))

            panel = RouteNodeEditorPanel(
                None,
                annotation_icon_path_provider=lambda type_id: icon_path if type_id == "ore" else "",
            )
            panel.set_nodes([{"x": 1, "y": 2, "typeId": "ore", "type": "鐭跨煶"}])

            icon = panel.findChild(QPushButton, "RouteNotesNodeIcon")
            self.assertIsNotNone(icon)
            self.assertFalse(icon.property("fallbackIcon"))
            self.assertNotIn("icon_path", panel.draft_nodes()[0])
            self.assertNotIn("icon_path", panel.nodes()[0])

    def test_node_name_context_menu_uses_chinese_items(self) -> None:
        panel = RouteNodeEditorPanel(None)
        panel.set_nodes([{"x": 1, "y": 2, "label": "A"}])
        editor = panel.findChild(QLineEdit, "RouteNotesNodeName")
        self.assertIsNotNone(editor)
        editor.selectAll()

        with patch("ui_island.dialogs.route_notes_dialog.show_context_menu") as menu:
            editor.customContextMenuRequested.emit(QPoint(1, 1))

        menu.assert_called_once()
        labels = [item.text for item in menu.call_args.args[2] if not item.separator]
        self.assertEqual(labels, ["撤销", "重做", "剪切", "复制", "粘贴", "删除", "全选"])

    def test_node_order_input_has_no_context_menu(self) -> None:
        panel = RouteNodeEditorPanel(None)
        panel.set_nodes([{"x": 1, "y": 2}])
        order_input = panel.findChild(QLineEdit, "RouteNotesNodeOrderInput")

        self.assertIsNotNone(order_input)
        self.assertEqual(order_input.contextMenuPolicy(), Qt.NoContextMenu)

    def test_dialog_renders_old_auto_name_as_refreshed_display_name(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [
                {"x": 1, "y": 1, "label": "宝箱 9", "typeId": "chest", "type": "宝箱"},
                {"x": 2, "y": 2, "label": "节点 99", "node_type": "collect"},
            ],
        )

        names = [editor.text() for editor in dialog.findChildren(QLineEdit, "RouteNotesNodeName")]

        self.assertEqual(names, ["宝箱 1", "采集点 1"])

    def test_node_name_input_updates_returned_node_draft(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 2}, {"x": 3, "y": 4, "label": "旧名"}],
        )

        editors = dialog.findChildren(QLineEdit, "RouteNotesNodeName")
        editors[0].setText("新节点")
        editors[1].clear()

        self.assertEqual(dialog.nodes()[0]["label"], "新节点")
        self.assertEqual(dialog.nodes()[1]["label"], "节点 2")
        self.assertTrue(dialog.nodes_changed())

    def test_node_annotation_picker_updates_and_clears_node_draft(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 2, "typeId": "old", "type": "旧"}],
        )

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_annotation_type_picker",
            return_value={"typeId": "ore", "type": "矿石"},
        ) as picker:
            dialog._change_node_annotation(0)

        picker.assert_called_once()
        self.assertEqual(picker.call_args.kwargs["include_clear"], True)
        self.assertEqual(picker.call_args.kwargs["placement"], "left_of")
        self.assertIs(picker.call_args.kwargs["anchor"], dialog.findChild(QWidget, "RouteNotesRightColumn"))
        self.assertEqual(dialog.nodes()[0]["typeId"], "ore")
        self.assertEqual(dialog.nodes()[0]["type"], "矿石")
        self.assertEqual(dialog.nodes()[0]["label"], "矿石 1")

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_annotation_type_picker",
            return_value={"clear": True},
        ):
            dialog._change_node_annotation(0)

        self.assertNotIn("typeId", dialog.nodes()[0])
        self.assertNotIn("type", dialog.nodes()[0])
        self.assertEqual(dialog.nodes()[0]["label"], "节点 1")

    def test_confirm_nodes_auto_label_empty_and_old_auto_names_without_overwriting_manual(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [
                {"x": 1, "y": 1, "typeId": "chest", "type": "宝箱"},
                {"x": 2, "y": 2, "label": "手写宝箱", "typeId": "chest", "type": "宝箱"},
                {"x": 3, "y": 3, "label": "节点 99", "node_type": "collect"},
            ],
        )

        self.assertEqual(
            [node["label"] for node in dialog.nodes()],
            ["宝箱 1", "手写宝箱", "采集点 1"],
        )

    def test_order_input_reorders_nodes_and_refreshes_position_text(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 1, "label": "A"}, {"x": 2, "y": 2, "label": "B"}, {"x": 3, "y": 3, "label": "C"}],
        )

        order_inputs = dialog.findChildren(QLineEdit, "RouteNotesNodeOrderInput")
        order_inputs[0].setText("3/3")
        order_inputs[0].editingFinished.emit()

        self.assertEqual([node.get("label") for node in dialog.nodes()], ["B", "C", "A"])
        self.assertEqual(
            [editor.text() for editor in dialog.findChildren(QLineEdit, "RouteNotesNodeOrderInput")],
            ["1/3", "2/3", "3/3"],
        )

    def test_reorder_refreshes_old_auto_labels_by_new_route_order(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [
                {"x": 1, "y": 1, "label": "宝箱 1", "typeId": "chest", "type": "宝箱"},
                {"x": 2, "y": 2, "label": "矿石 1", "typeId": "ore", "type": "矿石"},
                {"x": 3, "y": 3, "label": "宝箱 2", "typeId": "chest", "type": "宝箱"},
            ],
        )

        order_inputs = dialog.findChildren(QLineEdit, "RouteNotesNodeOrderInput")
        order_inputs[2].setText("1/3")
        order_inputs[2].editingFinished.emit()

        self.assertEqual(
            [node.get("label") for node in dialog.nodes()],
            ["宝箱 1", "宝箱 2", "矿石 1"],
        )

    def test_dragging_node_row_reorders_nodes(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "路线",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 1, "label": "A"}, {"x": 2, "y": 2, "label": "B"}, {"x": 3, "y": 3, "label": "C"}],
        )
        dialog.show()
        self._app.processEvents()
        rows = dialog.findChildren(QWidget, "RouteNotesNodeRow")

        start = rows[0].rect().center()
        end = rows[2].mapTo(rows[0], rows[2].rect().center())
        QTest.mousePress(rows[0], Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(rows[0], end, 50)
        QTest.mouseRelease(rows[0], Qt.LeftButton, Qt.NoModifier, end)
        self._app.processEvents()

        self.assertEqual([node.get("label") for node in dialog.nodes()], ["B", "C", "A"])

    def test_dragging_node_name_input_reorders_nodes(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "璺嚎",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 1, "label": "A"}, {"x": 2, "y": 2, "label": "B"}, {"x": 3, "y": 3, "label": "C"}],
        )
        dialog.show()
        self._app.processEvents()
        editors = dialog.findChildren(QLineEdit, "RouteNotesNodeName")
        rows = dialog.findChildren(QWidget, "RouteNotesNodeRow")

        start = editors[0].rect().center()
        end = rows[2].mapTo(editors[0], rows[2].rect().center())
        QTest.mousePress(editors[0], Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(editors[0], end, 50)
        QTest.mouseRelease(editors[0], Qt.LeftButton, Qt.NoModifier, end)
        self._app.processEvents()

        self.assertEqual([node.get("label") for node in dialog.nodes()], ["B", "C", "A"])

    def test_rejected_dialog_reports_no_node_changes_from_edit_route_notes(self) -> None:
        def reject_dialog(dialog):
            dialog.findChild(QLineEdit, "RouteNotesNodeName").setText("不会保存")
            dialog.reject()

        with patch("ui_island.dialogs.route_notes_dialog.center_dialog"), patch.object(
            RouteNotesDialog,
            "exec",
            lambda self: reject_dialog(self) or 0,
        ):
            from ui_island.dialogs.route_notes_dialog import edit_route_notes

            accepted, _notes, _color, nodes_changed, nodes, versions_changed, versions = edit_route_notes(
                None,
                "路线",
                "",
                (0x56, 0x34, 0x12),
                None,
                [{"x": 1, "y": 2}],
            )

        self.assertFalse(accepted)
        self.assertFalse(nodes_changed)
        self.assertEqual(nodes, [{"x": 1, "y": 2}])
        self.assertFalse(versions_changed)
        self.assertIsNone(versions)

    def test_dialog_title_uses_route_name_without_duplicate_subtitle(self) -> None:
        route_name = "Long Route Name"
        dialog = RouteNotesDialog(None, route_name, "", (0x56, 0x34, 0x12), None, [])

        self.assertEqual(dialog.title_label.text(), route_name)
        self.assertEqual(dialog.title_label.toolTip(), route_name)
        self.assertEqual(dialog.title_bar.toolTip(), route_name)
        self.assertFalse(any(label.text() == f"路线：{route_name}" for label in dialog.findChildren(QLabel)))

    def test_color_controls_share_notes_header_and_hide_hex_text(self) -> None:
        dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), None, [])

        header = dialog.findChild(QWidget, "RouteNotesHeaderRow")
        header_buttons = header.findChildren(QPushButton) if header is not None else []

        self.assertIsNotNone(header)
        self.assertIn(dialog.color_button, header_buttons)
        self.assertIn(dialog.reset_color_button, header_buttons)
        self.assertIn(dialog.enable_versions_button, header_buttons)
        self.assertIsNotNone(dialog.findChild(QPushButton, "RouteEnableVersionsButton"))
        self.assertEqual(dialog.color_button.text(), "当前路线颜色")
        self.assertEqual(dialog.color_button.width(), 96)
        self.assertNotIn("#", dialog.color_button.text())

    def test_route_enable_versions_dialog_allows_unchecking_current_version(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "Route",
            "",
            (0x56, 0x34, 0x12),
            None,
            [],
            enable_versions=["old-format", "GMT-N-0.1.3"],
            enable_version_options=["GMT-N-0.1.3"],
        )

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_route_enable_versions_dialog",
            return_value=["old-format"],
        ):
            dialog._edit_enable_versions()

        self.assertTrue(dialog.enable_versions_changed())
        self.assertEqual(dialog.enable_versions(), ["old-format"])
        self.assertEqual(dialog.enable_versions_button.text(), "查看/修改兼容版本（1）")

    def test_route_enable_versions_button_shows_version_count(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "Route",
            "",
            (0x56, 0x34, 0x12),
            None,
            [],
            enable_versions=["1.0.0", "1.0.1"],
            enable_version_options=["1.0.0", "1.0.1"],
        )

        self.assertEqual(dialog.enable_versions_button.text(), "查看/修改兼容版本（2）")
        self.assertIn("1.0.0", dialog.enable_versions_button.toolTip())
        self.assertIn("1.0.1", dialog.enable_versions_button.toolTip())

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_route_enable_versions_dialog",
            return_value=[],
        ):
            dialog._edit_enable_versions()

        self.assertEqual(dialog.enable_versions(), [])
        self.assertEqual(dialog.enable_versions_button.text(), "查看/修改兼容版本（无）")

    def test_opacity_slider_updates_route_notes_window_opacity(self) -> None:
        dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), None, [])
        slider = dialog.findChild(QSlider, "RouteNotesOpacitySlider")

        self.assertIsNotNone(slider)
        self.assertEqual(slider.property("compactSlider"), "true")
        self.assertEqual(slider.minimum(), _ROUTE_NOTES_MIN_OPACITY_PERCENT)
        self.assertEqual(slider.maximum(), 100)
        self.assertEqual(slider.minimumWidth(), _ROUTE_NOTES_OPACITY_SLIDER_MIN_WIDTH)
        self.assertEqual(slider.maximumWidth(), _ROUTE_NOTES_OPACITY_SLIDER_MAX_WIDTH)
        self.assertAlmostEqual(dialog.windowOpacity(), 1.0)

        slider.setValue(55)

        self.assertAlmostEqual(dialog.windowOpacity(), 0.55, places=2)
        self.assertIn("55%", slider.toolTip())

    def test_opacity_slider_lives_in_title_bar_before_close_button(self) -> None:
        dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), None, [])
        slider = dialog.findChild(QSlider, "RouteNotesOpacitySlider")
        header = dialog.findChild(QWidget, "RouteNotesHeaderRow")

        self.assertIsNotNone(slider)
        self.assertIs(slider.parent(), dialog.title_bar)
        self.assertNotIn(slider, header.findChildren(QSlider) if header is not None else [])
        title_layout = dialog.title_bar.layout()
        self.assertLess(title_layout.indexOf(slider), title_layout.indexOf(dialog.close_btn))

    def test_follow_global_button_is_enabled_only_for_custom_color(self) -> None:
        follow_dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), None, [])
        custom_dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), "#abcdef", [])

        self.assertFalse(follow_dialog.reset_color_button.isEnabled())
        self.assertTrue(custom_dialog.reset_color_button.isEnabled())

    def test_route_details_stats_panel_is_below_notes_editor(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "璺嚎",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"node_type": "collect", "typeId": "ore", "type": "鐭跨煶"}],
        )

        left = dialog.findChild(QWidget, "RouteNotesLeftColumn")
        right = dialog.findChild(QWidget, "RouteNotesRightColumn")
        stats = dialog.findChild(QWidget, "RouteNotesStatsPanel")
        editor = dialog.findChild(QPlainTextEdit)
        stats_scroll = dialog.findChild(QScrollArea, "RouteNotesStatsScroll")
        nodes_title = right.findChildren(QLabel, "FieldLabel")[0] if right is not None else None
        notes_header = dialog.findChild(QWidget, "RouteNotesHeaderRow")
        right_stats = right.findChild(QWidget, "RouteNotesStatsPanel") if right is not None else None

        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertIsNotNone(stats)
        self.assertIsNotNone(editor)
        self.assertIsNotNone(stats_scroll)
        self.assertIsNotNone(nodes_title)
        self.assertIsNotNone(notes_header)
        self.assertIs(stats_scroll.widget(), stats)
        self.assertIn(stats, left.findChildren(QWidget))
        self.assertNotIn(stats, right.findChildren(QWidget))
        self.assertIsNone(right_stats)
        self.assertEqual(editor.minimumHeight(), 120)
        self.assertEqual(right.minimumWidth(), _ROUTE_NOTES_RIGHT_MIN_WIDTH)
        self.assertGreaterEqual(dialog.width(), dialog.minimumWidth())
        self.assertEqual(dialog.height(), _ROUTE_NOTES_DIALOG_INITIAL_HEIGHT)
        self.assertEqual(stats_scroll.minimumHeight(), 72)
        self.assertEqual(stats_scroll.maximumHeight(), 72)
        self.assertEqual(nodes_title.minimumHeight(), notes_header.minimumHeight())
        self.assertEqual(nodes_title.maximumHeight(), notes_header.maximumHeight())
        splitter = dialog.findChild(QSplitter, "RouteNotesSplitter")
        size_grip = dialog.findChild(QSizeGrip, "RouteNotesSizeGrip")
        self.assertIsNotNone(splitter)
        self.assertFalse(splitter.childrenCollapsible())
        self.assertEqual(splitter.handleWidth(), 8)
        self.assertIsNotNone(size_grip)

        dialog.show()
        self._app.processEvents()
        self.assertEqual(stats_scroll.verticalScrollBar().maximum(), 0)

    def test_route_details_geometry_keeps_stats_under_notes_and_nodes_on_right(self) -> None:
        def panel_geometry_for(nodes: list[dict]) -> tuple[int, int, int, int, int, int, int, int, int, int, int, int]:
            dialog = RouteNotesDialog(None, "Route", "", (0x56, 0x34, 0x12), None, nodes)
            dialog.show()
            self._app.processEvents()
            left = dialog.findChild(QWidget, "RouteNotesLeftColumn")
            right = dialog.findChild(QWidget, "RouteNotesRightColumn")
            stats_scroll = dialog.findChild(QScrollArea, "RouteNotesStatsScroll")
            stats_panel = dialog.stats_panel
            scroll = dialog.findChild(QScrollArea, "RouteNotesNodeScroll")
            editor = dialog.findChild(QPlainTextEdit)
            self.assertIsNotNone(left)
            self.assertIsNotNone(right)
            self.assertIsNotNone(stats_scroll)
            self.assertIsNotNone(stats_panel)
            self.assertIsNotNone(scroll)
            self.assertIsNotNone(editor)
            nodes_title = right.findChildren(QLabel, "FieldLabel")[0]
            bottom_blank = right.height() - (scroll.geometry().y() + scroll.height())
            bottom_gap = left.height() - (right.geometry().y() + right.height())
            geometry = (
                left.height(),
                right.height(),
                right.geometry().y(),
                editor.geometry().y(),
                editor.geometry().height(),
                stats_panel.geometry().y(),
                stats_panel.height(),
                nodes_title.geometry().y(),
                nodes_title.height(),
                scroll.geometry().y(),
                scroll.height(),
                bottom_blank,
                bottom_gap,
            )
            dialog.close()
            return geometry

        small_geometry = panel_geometry_for([
            {"node_type": "collect", "typeId": "ore", "type": "Ore"}
        ])
        large_geometry = panel_geometry_for([
            {"node_type": "collect", "typeId": f"type-{index}", "type": f"Type {index}"}
            for index in range(80)
        ])

        for geometry in (small_geometry, large_geometry):
            (
                left_height,
                right_height,
                right_y,
                editor_y,
                editor_height,
                stats_y,
                stats_height,
                nodes_title_y,
                nodes_title_height,
                scroll_y,
                scroll_height,
                bottom_blank,
                bottom_gap,
            ) = geometry
            self.assertEqual(right_y, 0)
            self.assertEqual(right_height, left_height)
            self.assertGreater(stats_y, editor_y + editor_height)
            self.assertGreaterEqual(stats_height, 72)
            self.assertEqual(nodes_title_y, 0)
            self.assertEqual(nodes_title_height, _TITLE_ROW_HEIGHT)
            self.assertEqual(scroll_y, _TITLE_ROW_HEIGHT + _NODE_PANEL_SPACING)
            self.assertEqual(scroll_height, right_height - scroll_y)
            self.assertGreaterEqual(scroll_height, _NODE_SCROLL_MIN_HEIGHT)
            self.assertEqual(bottom_blank, 0)
            self.assertEqual(bottom_gap, 0)

        self.assertGreaterEqual(large_geometry[10], _NODE_SCROLL_MIN_HEIGHT)
        self.assertGreaterEqual(small_geometry[10], _NODE_SCROLL_MIN_HEIGHT)

    def test_large_stats_panel_grows_to_max_then_scrolls(self) -> None:
        nodes = [
            {"node_type": "collect", "typeId": f"type-{index}", "type": f"Type {index}"}
            for index in range(80)
        ]
        dialog = RouteNotesDialog(None, "Route", "", (0x56, 0x34, 0x12), None, nodes)
        dialog.show()
        self._app.processEvents()

        stats_scroll = dialog.findChild(QScrollArea, "RouteNotesStatsScroll")
        self.assertIsNotNone(stats_scroll)
        self.assertEqual(stats_scroll.minimumHeight(), 150)
        self.assertEqual(stats_scroll.maximumHeight(), 150)

        scrollbar = stats_scroll.verticalScrollBar()
        self.assertTrue(scrollbar.isVisible())
        self.assertGreater(scrollbar.maximum(), 0)

        option = QStyleOptionSlider()
        scrollbar.initStyleOption(option)
        handle = scrollbar.style().subControlRect(QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, scrollbar)
        self.assertGreaterEqual(handle.height(), 24)
        self.assertGreaterEqual(scrollbar.width(), 10)

        start = handle.center()
        end = QPoint(start.x(), scrollbar.rect().bottom() - 4)
        before = scrollbar.value()
        QTest.mousePress(scrollbar, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(scrollbar, end, 50)
        QTest.mouseRelease(scrollbar, Qt.LeftButton, Qt.NoModifier, end)
        self._app.processEvents()

        self.assertGreater(scrollbar.value(), before)

    def test_route_details_stats_refresh_after_node_annotation_change(self) -> None:
        dialog = RouteNotesDialog(
            None,
            "Route",
            "",
            (0x56, 0x34, 0x12),
            None,
            [{"x": 1, "y": 2}],
        )
        stats = dialog.findChild(QWidget, "RouteNotesStatsPanel")
        self.assertIsNotNone(stats)
        self.assertFalse(any(label.text() == "Ore 1" for label in stats.findChildren(QLabel, "RouteNotesStatChip")))

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_annotation_type_picker",
            return_value={"typeId": "ore", "type": "Ore"},
        ):
            dialog._change_node_annotation(0)

        stats = dialog.findChild(QWidget, "RouteNotesStatsPanel")
        self.assertTrue(any(label.text() == "Ore 1" for label in stats.findChildren(QLabel, "RouteNotesStatChip")))

    def test_annotation_picker_placement_helpers_keep_default_centering(self) -> None:
        from ui_island.dialogs.annotation_type_picker import open_annotation_type_picker

        accepted = 0
        with (
            patch("ui_island.dialogs.annotation_type_picker.AnnotationTypePickerDialog.exec", return_value=accepted),
            patch("ui_island.dialogs.annotation_type_picker.center_dialog") as center,
            patch("ui_island.dialogs.annotation_type_picker.place_left_of") as left,
            patch("ui_island.dialogs.annotation_type_picker.place_right_of") as right,
        ):
            open_annotation_type_picker(None, [], "")

        center.assert_called_once()
        left.assert_not_called()
        right.assert_not_called()

    def test_annotation_picker_can_be_placed_left_or_right_of_anchor(self) -> None:
        from ui_island.dialogs.annotation_type_picker import open_annotation_type_picker

        anchor = QWidget()
        accepted = 0
        with (
            patch("ui_island.dialogs.annotation_type_picker.AnnotationTypePickerDialog.exec", return_value=accepted),
            patch("ui_island.dialogs.annotation_type_picker.center_dialog") as center,
            patch("ui_island.dialogs.annotation_type_picker.place_left_of") as left,
            patch("ui_island.dialogs.annotation_type_picker.place_right_of") as right,
        ):
            open_annotation_type_picker(anchor, [], "", placement="left_of", anchor=anchor)
            open_annotation_type_picker(anchor, [], "", placement="right_of", anchor=anchor)

        center.assert_not_called()
        self.assertEqual(left.call_count, 1)
        self.assertIs(left.call_args.args[1], anchor)
        self.assertEqual(right.call_count, 1)
        self.assertIs(right.call_args.args[1], anchor)

    def test_pick_color_uses_shared_styled_picker(self) -> None:
        dialog = RouteNotesDialog(None, "路线", "", (0x56, 0x34, 0x12), None, [])

        with patch(
            "ui_island.dialogs.route_notes_dialog.open_styled_color_picker",
            return_value=QColor("#abcdef"),
        ) as picker:
            dialog._pick_color()

        picker.assert_called_once()
        self.assertEqual(dialog.color_override(), "#abcdef")
        self.assertEqual(dialog.color_button.text(), "当前路线颜色")

    def test_route_details_uses_persisted_dialog_and_node_panel_widths(self) -> None:
        with (
            patch("ui_island.dialogs.route_notes_dialog.config.ROUTE_NOTES_DIALOG_WIDTH", 860, create=True),
            patch("ui_island.dialogs.route_notes_dialog.config.ROUTE_NOTES_NODE_PANEL_WIDTH", 280, create=True),
        ):
            dialog = RouteNotesDialog(None, "Route", "", (0x56, 0x34, 0x12), None, [])
            dialog.show()
            self._app.processEvents()

        self.assertEqual(dialog.width(), 860)
        splitter = dialog.findChild(QSplitter, "RouteNotesSplitter")
        self.assertIsNotNone(splitter)
        self.assertAlmostEqual(splitter.sizes()[1], 280, delta=24)

    def test_route_details_persists_dialog_and_node_panel_widths(self) -> None:
        dialog = RouteNotesDialog(None, "Route", "", (0x56, 0x34, 0x12), None, [])
        dialog.show()
        self._app.processEvents()
        dialog.resize(880, dialog.height())
        dialog.splitter.setSizes([580, 300])
        self._app.processEvents()
        expected_right_width = dialog.splitter.sizes()[1]

        dialog._persist_layout_preferences()

        self._mock_save_config.assert_called()
        payload = self._mock_save_config.call_args.args[0]
        self.assertEqual(payload["ROUTE_NOTES_DIALOG_WIDTH"], 880)
        self.assertEqual(payload["ROUTE_NOTES_NODE_PANEL_WIDTH"], expected_right_width)

    def test_route_details_schedules_layout_save_while_dragging_sizes(self) -> None:
        dialog = RouteNotesDialog(None, "Route", "", (0x56, 0x34, 0x12), None, [])
        dialog.show()
        self._app.processEvents()

        dialog.resize(840, dialog.height())
        self.assertTrue(dialog._layout_save_timer.isActive())

        dialog._layout_save_timer.stop()
        dialog._on_splitter_moved(260, 1)
        self.assertTrue(dialog._layout_save_timer.isActive())

        dialog._layout_save_timer.stop()

    def test_node_scrollbar_has_draggable_handle_and_changes_value_when_dragged(self) -> None:
        nodes = [{"label": f"Node {index}", "x": index, "y": index} for index in range(400)]
        dialog = RouteNotesDialog(None, "璺嚎", "", (0x56, 0x34, 0x12), None, nodes)
        dialog.show()
        self._app.processEvents()

        scroll = dialog.findChild(QScrollArea, "RouteNotesNodeScroll")
        self.assertIsNotNone(scroll)
        scrollbar = scroll.verticalScrollBar()
        self.assertTrue(scrollbar.isVisible())
        self.assertGreater(scrollbar.maximum(), 0)

        option = QStyleOptionSlider()
        scrollbar.initStyleOption(option)
        handle = scrollbar.style().subControlRect(QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, scrollbar)
        self.assertGreaterEqual(handle.height(), 24)
        self.assertGreaterEqual(scrollbar.width(), 10)

        start = handle.center()
        end = QPoint(start.x(), scrollbar.rect().bottom() - 4)
        before = scrollbar.value()
        QTest.mousePress(scrollbar, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(scrollbar, end, 50)
        QTest.mouseRelease(scrollbar, Qt.LeftButton, Qt.NoModifier, end)
        self._app.processEvents()

        self.assertGreater(scrollbar.value(), before)


if __name__ == "__main__":
    unittest.main()

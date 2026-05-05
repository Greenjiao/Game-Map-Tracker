import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QWidget

import config
from ui_island.services import resource_metadata
from ui_island.dialogs.settings_dialog import AnnotationFormatConverterDialog, RouteFormatConverterDialog, SettingsDialog
from ui_island.services.settings_schema import TOOL_BUTTONS


class SettingsDialogMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_settings_tool_buttons_remove_documentation_entry(self) -> None:
        self.assertNotIn("更新文档", TOOL_BUTTONS)

        dialog = SettingsDialog(None)
        self._app.processEvents()

        self.assertNotIn("更新文档", dialog._TOOL_BUTTON_ICONS)
        for _, names in dialog._TOOL_BUTTON_GROUPS:
            self.assertNotIn("更新文档", names)
        dialog.close()

    def test_interaction_tab_collects_annotation_panel_follow_window(self) -> None:
        with patch.object(config, "ANNOTATION_PANEL_FOLLOW_WINDOW", True, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            self.assertIn("交互", [button.text() for button in dialog._common_tab_buttons])
            self.assertIsNotNone(dialog._annotation_panel_follow_checkbox)
            self.assertTrue(dialog._annotation_panel_follow_checkbox.isChecked())

            dialog._annotation_panel_follow_checkbox.setChecked(False)
            values = dialog._collect()

            self.assertIsNotNone(values)
            self.assertEqual(values["ANNOTATION_PANEL_FOLLOW_WINDOW"], False)
            dialog.close()

    def test_interaction_tab_collects_window_lock_follows_guide(self) -> None:
        with patch.object(config, "WINDOW_LOCK_FOLLOWS_GUIDE", True, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            self.assertIsNotNone(dialog._window_lock_follows_guide_checkbox)
            self.assertTrue(dialog._window_lock_follows_guide_checkbox.isChecked())

            dialog._window_lock_follows_guide_checkbox.setChecked(False)
            values = dialog._collect()

            self.assertIsNotNone(values)
            self.assertEqual(values["WINDOW_LOCK_FOLLOWS_GUIDE"], False)
            dialog.close()

    def test_interaction_tab_collects_pure_navigation_mode(self) -> None:
        with (
            patch.object(config, "PURE_NAVIGATION_MODE", False, create=True),
            patch.object(config, "ACTION_HOTKEYS", {}, create=True),
        ):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            self.assertIsNotNone(dialog._pure_navigation_checkbox)
            dialog._pure_navigation_checkbox.setChecked(True)
            dialog._action_hotkey_editors["terminate_navigation"].setKeySequence(QKeySequence("T"))
            values = dialog._collect()

            self.assertIsNotNone(values)
            self.assertEqual(values["PURE_NAVIGATION_MODE"], True)
            dialog.close()

    def test_interaction_tab_rejects_pure_navigation_without_terminate_hotkey(self) -> None:
        with (
            patch.object(config, "PURE_NAVIGATION_MODE", False, create=True),
            patch.object(config, "ACTION_HOTKEYS", {}, create=True),
            patch("ui_island.dialogs.settings_dialog.styled_info") as info,
        ):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            dialog._pure_navigation_checkbox.setChecked(True)
            values = dialog._collect()

            self.assertIsNone(values)
            info.assert_called()
            self.assertIn("终止导航快捷键", info.call_args.args[2])
            dialog.close()

    def test_interaction_tab_option_labels_share_one_row(self) -> None:
        dialog = SettingsDialog(None)
        self._app.processEvents()

        checkboxes = {
            checkbox.text(): checkbox
            for checkbox in dialog.findChildren(QCheckBox)
        }
        for label in ("纯净导航模式", "锁定状态流转", "标注栏固定在底部"):
            self.assertIn(label, checkboxes)
        self.assertIs(checkboxes["纯净导航模式"].parentWidget(), checkboxes["锁定状态流转"].parentWidget())
        self.assertIs(checkboxes["锁定状态流转"].parentWidget(), checkboxes["标注栏固定在底部"].parentWidget())
        dialog.close()

    def test_interaction_tab_collects_action_hotkeys(self) -> None:
        with patch.object(config, "ACTION_HOTKEYS", {}, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            self.assertIn("reset_view", dialog._action_hotkey_editors)
            dialog._action_hotkey_editors["reset_view"].setKeySequence(QKeySequence("R"))
            values = dialog._collect()

            self.assertIsNotNone(values)
            self.assertEqual(values["ACTION_HOTKEYS"]["reset_view"]["key"], "R")
            self.assertEqual(values["ACTION_HOTKEYS"]["reset_view"]["modifiers"], [])
            self.assertIsNone(values["ACTION_HOTKEYS"]["relocate"])
            dialog.close()

    def test_interaction_tab_hotkeys_use_compact_chinese_layout(self) -> None:
        with patch.object(config, "ACTION_HOTKEYS", {}, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            labels = [
                label.text()
                for label in dialog.findChildren(QLabel)
                if label.property("settingsHotkeyLabel")
            ]
            self.assertEqual(
                labels,
                [
                    "锁定/解锁",
                    "开始导航",
                    "终止导航",
                    "重置视图",
                    "重定位",
                    "跳转路线节点",
                    "角色位置加点",
                ],
            )
            hints = [
                label.text()
                for label in dialog.findChildren(QLabel)
                if label.property("settingsHotkeyHint")
            ]
            self.assertEqual(hints, ["快捷键可能与游戏按键冲突"])
            self.assertEqual(dialog._action_hotkey_editors["reset_view"].text(), "未设置")
            dialog._action_hotkey_editors["reset_view"].click()
            self.assertEqual(dialog._action_hotkey_editors["reset_view"].text(), "请按键")
            self.assertNotIn("shortcut", dialog._action_hotkey_editors["reset_view"].toolTip().casefold())
            dialog.close()

    def test_interaction_tab_can_clear_action_and_restore_lock_default(self) -> None:
        with patch.object(config, "ACTION_HOTKEYS", {}, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            dialog._action_hotkey_editors["reset_view"].setKeySequence(QKeySequence("R"))
            dialog._action_hotkey_editors["reset_view"].clear()
            dialog._hotkey_editor.setKeySequence(QKeySequence("L"))
            dialog._reset_hotkey_to_default()
            values = dialog._collect()

            self.assertIsNotNone(values)
            self.assertIsNone(values["ACTION_HOTKEYS"]["reset_view"])
            self.assertEqual(values["TOGGLE_LOCK_HOTKEY"]["label"], "Alt+`")
            dialog.close()

    def test_interaction_tab_rejects_duplicate_hotkeys(self) -> None:
        with (
            patch.object(config, "ACTION_HOTKEYS", {}, create=True),
            patch("ui_island.dialogs.settings_dialog.styled_info") as info,
        ):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            dialog._hotkey_editor.setKeySequence(QKeySequence("R"))
            dialog._action_hotkey_editors["reset_view"].setKeySequence(QKeySequence("R"))
            values = dialog._collect()

            self.assertIsNone(values)
            self.assertTrue(info.called)
            dialog.close()

    def test_reset_defaults_restores_annotation_panel_follow_checkbox(self) -> None:
        with patch.object(config, "ANNOTATION_PANEL_FOLLOW_WINDOW", False, create=True):
            dialog = SettingsDialog(None)
            self._app.processEvents()

            self.assertIsNotNone(dialog._annotation_panel_follow_checkbox)
            self.assertFalse(dialog._annotation_panel_follow_checkbox.isChecked())

            dialog._on_reset_defaults()

            self.assertTrue(dialog._annotation_panel_follow_checkbox.isChecked())
            dialog.close()

    def test_feedback_uses_configured_named_links(self) -> None:
        with (
            patch.object(
                config,
                "FEEDBACK_LINKS",
                [
                    {"name": " Bilibili ", "url": " https://space.bilibili.com/example "},
                    {"name": "QQ Group", "url": "https://qm.qq.com/q/example"},
                ],
                create=True,
            ),
            patch("ui_island.dialogs.settings_dialog.styled_info") as styled_info,
        ):
            dialog = SettingsDialog(None)
            dialog._on_feedback_clicked()

            styled_info.assert_called_once()
            args, kwargs = styled_info.call_args
            self.assertEqual(args[1], "问题反馈")
            self.assertIn("Bilibili", args[2])
            self.assertIn("QQ Group", args[2])
            self.assertTrue(kwargs["allow_links"])
            dialog.close()

    def test_feedback_reports_invalid_or_missing_named_links(self) -> None:
        with patch.object(
            config,
            "FEEDBACK_LINKS",
            [{"name": "Bad", "url": "not a url"}],
            create=True,
        ):
            self.assertEqual(SettingsDialog._configured_feedback_links(), ([], True))

        with patch.object(config, "FEEDBACK_LINKS", [], create=True):
            self.assertEqual(SettingsDialog._configured_feedback_links(), ([], False))

    def test_existing_unregistered_map_remains_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_map_file = getattr(config, "MAP_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.MAP_FILE = "maps/custom/big_map.png"
                path = Path(tmp, "maps", "custom", "big_map.png")
                path.parent.mkdir(parents=True)
                path.write_bytes(b"user map")

                dialog = SettingsDialog(None)
                self._app.processEvents()

                combo = dialog._map_file_combo
                self.assertIsNotNone(combo)
                self.assertTrue(combo.isEnabled())
                self.assertEqual(combo.currentData(), "maps/custom/big_map.png")
                self.assertIn("可能导致路线/标注偏移", combo.toolTip())
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.MAP_FILE = old_map_file

    def test_map_combo_stays_unselected_until_user_chooses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_map_file = getattr(config, "MAP_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.MAP_FILE = ""
                path = Path(tmp, "maps", "candidate.png")
                path.parent.mkdir(parents=True)
                path.write_bytes(b"user map")

                dialog = SettingsDialog(None)
                self._app.processEvents()

                combo = dialog._map_file_combo
                self.assertIsNotNone(combo)
                self.assertTrue(combo.isEnabled())
                self.assertEqual(combo.currentData(), "")
                self.assertEqual(combo.currentText(), "请选择底图")
                values = dialog._collect()
                self.assertIsNotNone(values)
                self.assertEqual(values.get("MAP_FILE"), "")
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.MAP_FILE = old_map_file

    def test_annotation_combo_stays_unselected_until_user_chooses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = ""
                path = Path(tmp, "annotations", "points_17173.json")
                path.parent.mkdir(parents=True)
                path.write_text("{}", encoding="utf-8")

                dialog = SettingsDialog(None)
                self._app.processEvents()

                combo = dialog._annotation_file_combo
                self.assertIsNotNone(combo)
                self.assertEqual(combo.currentData(), "")
                self.assertEqual(combo.currentText(), "请选择标注文件")
                self.assertEqual(dialog._annotation_format_version_label.text(), "创建版本：未选择")
                values = dialog._collect()
                self.assertIsNotNone(values)
                self.assertEqual(values.get("ANNOTATION_FILE"), "")
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_missing_configured_annotation_file_is_not_kept_as_combo_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/deleted.json"
                Path(tmp, "annotations").mkdir(parents=True)

                dialog = SettingsDialog(None)
                self._app.processEvents()

                combo = dialog._annotation_file_combo
                self.assertIsNotNone(combo)
                self.assertEqual(combo.currentData(), "")
                self.assertEqual(combo.currentText(), "请选择标注文件")
                self.assertEqual(combo.findData("annotations/deleted.json"), -1)
                self.assertNotIn("缺失", [combo.itemText(index) for index in range(combo.count())])
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_deleted_selected_annotation_file_is_removed_when_choices_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                annotations_dir = Path(tmp, "annotations")
                annotations_dir.mkdir(parents=True)
                current = annotations_dir / "current.json"
                current.write_text("{}", encoding="utf-8")

                dialog = SettingsDialog(None)
                self._app.processEvents()
                combo = dialog._annotation_file_combo
                self.assertIsNotNone(combo)
                self.assertEqual(combo.currentData(), "annotations/current.json")

                current.unlink()
                dialog._refresh_annotation_file_combo_preserving_selection()

                self.assertEqual(combo.currentData(), "")
                self.assertEqual(combo.currentText(), "请选择标注文件")
                self.assertEqual(combo.findData("annotations/current.json"), -1)
                self.assertNotIn("缺失", [combo.itemText(index) for index in range(combo.count())])
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_annotation_file_row_shows_selected_file_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                path = Path(tmp, "annotations", "current.json")
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"format_version": "tool-1"}), encoding="utf-8")

                dialog = SettingsDialog(None)
                self._app.processEvents()

                self.assertEqual(dialog._annotation_file_combo.currentData(), "annotations/current.json")
                self.assertEqual(dialog._annotation_format_version_label.text(), "创建版本：tool-1")
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_annotation_conversion_refreshes_choices_without_applying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                annotations_dir = Path(tmp, "annotations")
                annotations_dir.mkdir(parents=True)
                current = annotations_dir / "current.json"
                current.write_text("{}", encoding="utf-8")
                converted = annotations_dir / "converted_2026050101.json"
                old_source = annotations_dir / "old.json"
                old_source.write_text("{}", encoding="utf-8")

                settings = SettingsDialog(None)
                self._app.processEvents()
                applied_count = {"value": 0}
                settings.applied.connect(lambda: applied_count.__setitem__("value", applied_count["value"] + 1))
                settings._refresh_updated_resources = lambda: (_ for _ in ()).throw(
                    AssertionError("conversion must not refresh active resources")
                )

                dialog = AnnotationFormatConverterDialog(settings)
                dialog._old_file_editor.setText(str(old_source))
                dialog._merge_checkbox.setChecked(False)

                def fake_convert(*_args, **_kwargs):
                    converted.write_text("{}", encoding="utf-8")
                    return SimpleNamespace(
                        output_path=str(converted),
                        converted_points=1,
                        skipped_points=0,
                        deduplicated_points=0,
                        errors=0,
                        messages=[f"[完成] 已写入：{converted}"],
                    )

                with (
                    patch("ui_island.dialogs.settings_dialog.styled_confirm") as styled_confirm,
                    patch("ui_island.dialogs.settings_dialog.toast"),
                    patch("tools.annotation_converters.registry.convert_annotation_file", side_effect=fake_convert),
                    patch("config.save_config") as save_config,
                ):
                    dialog._start_conversion()

                styled_confirm.assert_not_called()
                combo = settings._annotation_file_combo
                self.assertIsNotNone(combo)
                self.assertEqual(combo.currentData(), "annotations/current.json")
                self.assertGreaterEqual(combo.findData("annotations/converted_2026050101.json"), 0)
                self.assertEqual(applied_count["value"], 0)
                save_config.assert_not_called()
                dialog.close()
                settings.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_annotation_conversion_dialog_shows_source_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": "tool-1"}), encoding="utf-8")

            dialog = AnnotationFormatConverterDialog(None)
            dialog._old_file_editor.setText(str(source))
            self._app.processEvents()

            self.assertEqual(dialog._source_version_label.text(), "创建格式：tool-1")
            dialog.close()

    def test_annotation_conversion_dialog_has_merge_mode_and_target_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            target = Path(tmp, "target.json")
            source.write_text(json.dumps({"format_version": "tool-1"}), encoding="utf-8")
            target.write_text(json.dumps({"format_version": "tool-1"}), encoding="utf-8")

            dialog = AnnotationFormatConverterDialog(None)
            dialog._old_file_editor.setText(str(source))
            dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(dialog._MODE_ANNOTATION_MERGE))
            dialog._new_file_editor.setText(str(target))
            self._app.processEvents()

            mode_values = [dialog._mode_combo.itemData(index) for index in range(dialog._mode_combo.count())]
            mode_labels = [dialog._mode_combo.itemText(index) for index in range(dialog._mode_combo.count())]
            self.assertEqual(
                mode_values,
                [dialog._MODE_LEGACY_COORDINATES, dialog._MODE_ANNOTATION_MERGE, dialog._MODE_OUTSIDE_FORMAT],
            )
            self.assertIn("标注文件合并", mode_labels)
            self.assertEqual(dialog._source_version_label.text(), "创建格式：tool-1")
            self.assertEqual(dialog._target_version_label.text(), "创建格式：tool-1")
            self.assertFalse(dialog._new_file_row.isHidden())
            self.assertFalse(dialog._new_file_editor.isReadOnly())
            dialog.close()

    def test_annotation_conversion_merge_mode_rejects_different_format_versions_before_convert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            target = Path(tmp, "target.json")
            source.write_text(json.dumps({"format_version": "tool-1"}), encoding="utf-8")
            target.write_text(json.dumps({"format_version": "tool-2"}), encoding="utf-8")

            with (
                patch("ui_island.dialogs.settings_dialog.styled_info") as styled_info,
                patch("ui_island.dialogs.settings_dialog.styled_confirm") as styled_confirm,
                patch("tools.annotation_converters.registry.convert_annotation_file") as convert,
            ):
                dialog = AnnotationFormatConverterDialog(None)
                dialog._old_file_editor.setText(str(source))
                dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(dialog._MODE_ANNOTATION_MERGE))
                dialog._new_file_editor.setText(str(target))
                self._app.processEvents()

                dialog._start_conversion()

                styled_info.assert_called_with(dialog, "标注转换", "格式版本不同，无法合并。")
                styled_confirm.assert_not_called()
                convert.assert_not_called()
                dialog.close()

    def test_annotation_conversion_legacy_mode_shows_auto_created_tool_version_and_does_not_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"pointsByType": {}}), encoding="utf-8")
            report = SimpleNamespace(
                output_path=str(Path(tmp, "annotations", "converted.json")),
                converted_points=0,
                skipped_points=0,
                deduplicated_points=0,
                errors=0,
                messages=[],
            )

            with (
                patch("ui_island.dialogs.settings_dialog.styled_confirm") as styled_confirm,
                patch("ui_island.dialogs.settings_dialog.toast"),
                patch("tools.annotation_converters.registry.convert_annotation_file", return_value=report) as convert,
            ):
                dialog = AnnotationFormatConverterDialog(None)
                dialog._old_file_editor.setText(str(source))
                dialog._merge_checkbox.setChecked(False)
                self._app.processEvents()

                self.assertTrue(dialog._new_file_editor.isReadOnly())
                self.assertEqual(dialog._new_file_editor.text(), dialog._AUTO_CREATED_TARGET_TEXT)
                self.assertEqual(dialog._target_version_label.text(), f"创建格式：{resource_metadata.APP_FORMAT_VERSION}")

                dialog._start_conversion()

                styled_confirm.assert_not_called()
                self.assertEqual(convert.call_args.args[0], dialog._MODE_LEGACY_COORDINATES)
                self.assertFalse(convert.call_args.kwargs["merge"])
                self.assertIsNone(convert.call_args.kwargs["merge_with"])
                dialog.close()

    def test_annotation_conversion_legacy_mode_defaults_to_selectable_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                annotations_dir = Path(tmp, "annotations")
                annotations_dir.mkdir()
                target = annotations_dir / "current.json"
                target.write_text(json.dumps({"format_version": resource_metadata.APP_FORMAT_VERSION}), encoding="utf-8")
                source = Path(tmp, "source.json")
                source.write_text(json.dumps({"pointsByType": {}}), encoding="utf-8")
                report = SimpleNamespace(
                    output_path=str(annotations_dir / "converted.json"),
                    converted_points=0,
                    skipped_points=0,
                    deduplicated_points=0,
                    errors=0,
                    messages=[],
                )

                with (
                    patch("ui_island.dialogs.settings_dialog.styled_confirm", return_value=True) as styled_confirm,
                    patch("ui_island.dialogs.settings_dialog.toast"),
                    patch("tools.annotation_converters.registry.convert_annotation_file", return_value=report) as convert,
                ):
                    dialog = AnnotationFormatConverterDialog(None)
                    dialog._old_file_editor.setText(str(source))
                    self._app.processEvents()

                    self.assertFalse(dialog._new_file_editor.isReadOnly())
                    self.assertEqual(Path(dialog._new_file_editor.text()), target)
                    self.assertFalse(dialog._new_file_button.isHidden())
                    self.assertFalse(dialog._merge_option_row.isHidden())
                    self.assertIn(resource_metadata.APP_FORMAT_VERSION, dialog._target_version_label.text())

                    dialog._start_conversion()

                    styled_confirm.assert_called_once()
                    self.assertEqual(convert.call_args.args[0], dialog._MODE_LEGACY_COORDINATES)
                    self.assertTrue(convert.call_args.kwargs["merge"])
                    self.assertEqual(Path(convert.call_args.kwargs["merge_with"]), target)
                    dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_annotation_conversion_outside_mode_reports_unsupported_version_on_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": "unsupported"}), encoding="utf-8")

            with (
                patch("config.APP_ENABLE_VERSIONS", ["supported"], create=True),
                patch("ui_island.dialogs.settings_dialog.styled_info") as styled_info,
                patch("tools.annotation_converters.registry.convert_annotation_file") as convert,
            ):
                dialog = AnnotationFormatConverterDialog(None)
                dialog._old_file_editor.setText(str(source))
                dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(dialog._MODE_OUTSIDE_FORMAT))
                self._app.processEvents()

                self.assertEqual(dialog._source_version_label.text(), "创建格式：unsupported")
                self.assertTrue(dialog._start_button.isEnabled())
                self.assertFalse(dialog._new_file_editor.isEnabled())
                self.assertTrue(dialog._new_file_row.isHidden())
                self.assertTrue(dialog._merge_option_row.isHidden())

                dialog._start_conversion()

                styled_info.assert_called_with(dialog, "标注转换", "暂不兼容：unsupported")
                convert.assert_not_called()
                dialog.close()

    def test_annotation_conversion_outside_mode_accepts_enabled_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": "supported"}), encoding="utf-8")

            with patch("config.APP_ENABLE_VERSIONS", ["supported"], create=True):
                dialog = AnnotationFormatConverterDialog(None)
                dialog._old_file_editor.setText(str(source))
                dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(dialog._MODE_OUTSIDE_FORMAT))
                self._app.processEvents()

                self.assertTrue(dialog._start_button.isEnabled())
                self.assertFalse(dialog._new_file_editor.isEnabled())
                self.assertTrue(dialog._new_file_row.isHidden())
                self.assertTrue(dialog._merge_option_row.isHidden())
                dialog.close()

    def test_annotation_conversion_outside_mode_does_not_show_merge_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.json")
            source.write_text(json.dumps({"format_version": "supported"}), encoding="utf-8")

            report = SimpleNamespace(
                output_path=str(Path(tmp, "annotations", "converted.json")),
                converted_points=0,
                skipped_points=0,
                deduplicated_points=0,
                errors=0,
                messages=[],
            )

            with (
                patch("config.APP_ENABLE_VERSIONS", ["supported"], create=True),
                patch("ui_island.dialogs.settings_dialog.styled_confirm") as styled_confirm,
                patch("ui_island.dialogs.settings_dialog.toast"),
                patch("tools.annotation_converters.registry.convert_annotation_file", return_value=report) as convert,
            ):
                dialog = AnnotationFormatConverterDialog(None)
                dialog._old_file_editor.setText(str(source))
                dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(dialog._MODE_OUTSIDE_FORMAT))
                self._app.processEvents()

                dialog._start_conversion()

                styled_confirm.assert_not_called()
                self.assertEqual(convert.call_args.args[0], dialog._MODE_OUTSIDE_FORMAT)
                self.assertFalse(convert.call_args.kwargs["merge"])
                self.assertIsNone(convert.call_args.kwargs["merge_with"])
                dialog.close()

    def test_route_conversion_dialog_defaults_to_dedicated_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            try:
                config.BASE_DIR = tmp

                dialog = RouteFormatConverterDialog(None)

                self.assertEqual(dialog._input_editor.text(), str(Path(tmp, "routes")))
                self.assertEqual(dialog._output_editor.text(), str(Path(tmp, "routes_converted")))
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir

    def test_route_conversion_modes_and_output_strategy_ui_are_unified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            try:
                config.BASE_DIR = tmp

                dialog = RouteFormatConverterDialog(None)

                combo = dialog._mode_combo
                self.assertIsNotNone(combo)
                self.assertEqual(combo.count(), 2)
                self.assertEqual([combo.itemText(index) for index in range(combo.count())], ["旧路线转新格式", "为路线自动添加标注"])
                self.assertEqual(
                    [combo.itemData(index) for index in range(combo.count())],
                    [dialog._MODE_NORMALIZE, dialog._MODE_ANNOTATE],
                )

                self.assertTrue(dialog._is_output_to_dir())
                self.assertFalse(dialog._output_row.isHidden())
                self.assertFalse(dialog._overwrite_checkbox.isHidden())
                self.assertTrue(dialog._output_to_dir_button.isChecked())
                self.assertTrue(dialog._output_to_dir_button.property("selected"))
                self.assertFalse(dialog._overwrite_source_button.isChecked())
                self.assertFalse(dialog._overwrite_source_button.property("selected"))

                dialog._set_output_mode(dialog._OUTPUT_IN_PLACE)

                self.assertFalse(dialog._is_output_to_dir())
                self.assertTrue(dialog._output_row.isHidden())
                self.assertTrue(dialog._overwrite_checkbox.isHidden())
                self.assertFalse(dialog._output_to_dir_button.isChecked())
                self.assertFalse(dialog._output_to_dir_button.property("selected"))
                self.assertTrue(dialog._overwrite_source_button.isChecked())
                self.assertTrue(dialog._overwrite_source_button.property("selected"))

                dialog._set_output_mode(dialog._OUTPUT_TO_DIR)

                self.assertTrue(dialog._is_output_to_dir())
                self.assertFalse(dialog._output_row.isHidden())
                self.assertFalse(dialog._overwrite_checkbox.isHidden())
                self.assertTrue(dialog._output_to_dir_button.property("selected"))
                self.assertFalse(dialog._overwrite_source_button.property("selected"))
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir

    def test_route_conversion_normalize_does_not_refresh_active_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            try:
                config.BASE_DIR = tmp
                input_dir = Path(tmp, "routes")
                output_dir = Path(tmp, "routes_converted")
                input_dir.mkdir()

                refresh_called = {"value": False}
                parent = QWidget()
                parent.route_panel_controller = SimpleNamespace(
                    reload_route_list=lambda: refresh_called.__setitem__("value", True)
                )
                dialog = RouteFormatConverterDialog(parent)
                dialog._input_editor.setText(str(input_dir))
                dialog._output_editor.setText(str(output_dir))

                report = SimpleNamespace(
                    converted=1,
                    skipped=0,
                    ignored=0,
                    errors=0,
                    points_converted=2,
                    messages=[f"[完成] {input_dir / 'a.json'} -> {output_dir / 'a_新格式.json'}"],
                )

                with (
                    patch("tools.route_format_converter.convert_route_folder", return_value=report),
                    patch("ui_island.dialogs.settings_dialog.toast"),
                ):
                    dialog._start_conversion()

                self.assertFalse(refresh_called["value"])
                self.assertIn("完整日志：", dialog._log.toPlainText())
                self.assertTrue(list(Path(tmp, "logs").glob("route_conversion_*.log")))
                dialog.close()
                parent.close()
            finally:
                config.BASE_DIR = old_base_dir

    def test_route_conversion_normalize_in_place_uses_overwrite_flow_and_refreshes_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            try:
                config.BASE_DIR = tmp
                input_dir = Path(tmp, "routes")
                input_dir.mkdir()

                refresh_called = {"value": False}
                parent = QWidget()
                parent.route_panel_controller = SimpleNamespace(
                    reload_route_list=lambda: refresh_called.__setitem__("value", True)
                )
                dialog = RouteFormatConverterDialog(parent)
                dialog._input_editor.setText(str(input_dir))
                dialog._set_output_mode(dialog._OUTPUT_IN_PLACE)

                report = SimpleNamespace(
                    converted=1,
                    skipped=0,
                    ignored=0,
                    errors=0,
                    points_converted=2,
                    messages=[f"[完成] {input_dir / 'a.json'}"],
                )

                with (
                    patch("ui_island.dialogs.settings_dialog.styled_confirm", return_value=True) as confirm,
                    patch("tools.route_format_converter.convert_old_big_map_routes_in_place", return_value=report) as convert_in_place,
                    patch("tools.route_format_converter.convert_route_folder") as convert_to_dir,
                    patch("ui_island.dialogs.settings_dialog.toast"),
                ):
                    dialog._start_conversion()

                confirm.assert_called_once()
                convert_in_place.assert_called_once_with(str(input_dir), recursive=True)
                convert_to_dir.assert_not_called()
                self.assertTrue(refresh_called["value"])
                self.assertIn("完整日志：", dialog._log.toPlainText())
                dialog.close()
                parent.close()
            finally:
                config.BASE_DIR = old_base_dir

    def test_route_conversion_failure_is_logged_in_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            try:
                config.BASE_DIR = tmp
                input_dir = Path(tmp, "routes")
                output_dir = Path(tmp, "routes_converted")
                input_dir.mkdir()

                dialog = RouteFormatConverterDialog(None)
                dialog._input_editor.setText(str(input_dir))
                dialog._output_editor.setText(str(output_dir))

                with (
                    patch("tools.route_format_converter.convert_route_folder", side_effect=ValueError("bad conversion")),
                    patch("ui_island.dialogs.settings_dialog.styled_info") as styled_info,
                ):
                    dialog._start_conversion()

                self.assertIn("[错误] bad conversion", dialog._log.toPlainText())
                self.assertTrue(list(Path(tmp, "logs").glob("route_conversion_error_*.log")))
                styled_info.assert_called()
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir


if __name__ == "__main__":
    unittest.main()

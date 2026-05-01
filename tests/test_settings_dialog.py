import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

import config
from ui_island.dialogs.settings_dialog import AnnotationFormatConverterDialog, RouteFormatConverterDialog, SettingsDialog


class SettingsDialogMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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

    def test_annotation_enable_versions_show_file_versions_and_switches_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                annotations_dir = Path(tmp, "annotations")
                annotations_dir.mkdir(parents=True)
                (annotations_dir / "current.json").write_text(
                    json.dumps({"enable_versions": ["1.0.0", "hidden", "2.0.0"]}),
                    encoding="utf-8",
                )
                (annotations_dir / "other.json").write_text(
                    json.dumps({"enable_versions": ["2.0.0"]}),
                    encoding="utf-8",
                )

                with patch("config.APP_ENABLE_VERSIONS", ["1.0.0", "2.0.0"], create=True):
                    dialog = SettingsDialog(None)
                    self._app.processEvents()

                    button = dialog._annotation_enable_versions_button
                    combo = dialog._annotation_file_combo
                    self.assertIsNotNone(button)
                    self.assertIsNotNone(combo)
                    self.assertEqual(button.text(), "查看/修改兼容版本（3）")
                    self.assertIn("1.0.0", button.toolTip())
                    self.assertIn("2.0.0", button.toolTip())
                    self.assertIn("hidden", button.toolTip())
                    self.assertTrue(button.isEnabled())

                    combo.setCurrentIndex(combo.findData("annotations/other.json"))
                    self._app.processEvents()

                    self.assertEqual(button.text(), "查看/修改兼容版本（1）")
                    self.assertIn("2.0.0", button.toolTip())
                    self.assertTrue(button.isEnabled())
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_annotation_enable_versions_disabled_without_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = ""
                Path(tmp, "annotations").mkdir(parents=True)

                dialog = SettingsDialog(None)
                self._app.processEvents()

                self.assertEqual(dialog._annotation_enable_versions_button.text(), "查看/修改兼容版本（无）")
                self.assertFalse(dialog._annotation_enable_versions_button.isEnabled())
                dialog.close()
            finally:
                config.BASE_DIR = old_base_dir
                config.ANNOTATION_FILE = old_annotation_file

    def test_edit_annotation_enable_versions_writes_empty_array_and_preserves_format_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_base_dir = config.BASE_DIR
            old_annotation_file = getattr(config, "ANNOTATION_FILE", "")
            try:
                config.BASE_DIR = tmp
                config.ANNOTATION_FILE = "annotations/current.json"
                annotations_dir = Path(tmp, "annotations")
                annotations_dir.mkdir(parents=True)
                path = annotations_dir / "current.json"
                path.write_text(
                    json.dumps(
                        {
                            "format_version": "publisher-format",
                            "enable_versions": ["1.0.0"],
                            "pointsByType": {"ore": []},
                        }
                    ),
                    encoding="utf-8",
                )

                with (
                    patch("config.APP_ENABLE_VERSIONS", ["1.0.0"], create=True),
                    patch("ui_island.dialogs.settings_dialog.open_route_enable_versions_dialog", return_value=[]),
                    patch("ui_island.dialogs.settings_dialog.toast"),
                ):
                    dialog = SettingsDialog(None)
                    self._app.processEvents()
                    dialog._on_edit_annotation_enable_versions()

                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["format_version"], "publisher-format")
                self.assertEqual(payload["enable_versions"], ["publisher-format"])
                self.assertEqual(payload["pointsByType"], {"ore": []})
                self.assertEqual(dialog._annotation_enable_versions_button.text(), "查看/修改兼容版本（1）")
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
                    patch("ui_island.dialogs.settings_dialog.styled_confirm", return_value=True),
                    patch("ui_island.dialogs.settings_dialog.toast"),
                    patch("tools.annotation_format_converter.convert_annotation_file", side_effect=fake_convert),
                    patch("config.save_config") as save_config,
                ):
                    dialog._start_conversion()

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

"""岛状界面的设置对话框和统一提示辅助函数。"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from html import escape
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDoubleValidator, QIntValidator, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QKeySequenceEdit,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config

from . import StyledConfirm, StyledDialogBase, StyledMessage, Toast, center_dialog, place_left_of, toast, toast_persistent
from .annotation_type_picker import open_annotation_type_multi_picker
from .color_picker import open_styled_color_picker
from ..app.app_info import APP_VERSION
from ..design import qss, strings, tokens
from ..services.annotation_preferences import normalize_type_ids
from ..services.app_updater import (
    AppUpdateCheckResult,
    AppUpdateInstallResult,
    check_app_update,
    cleanup_staging,
    download_changed_files,
    install_non_restart_update,
    start_restart_update,
)
from ..services.hotkey_config import hotkey_sequence, payload_from_key_sequence
from ..services import resource_metadata
from ..services.settings_schema import ALL_FIELDS, COMMON_FIELDS, FIELD_INDEX, SIFT_FIELDS, TOOL_BUTTONS, Field
from ..widgets.context_menu import ContextMenuItem, show_context_menu
from ..widgets.factory import make_scroll_area

_DEFAULT_ROUTE_COLOR_HEX = "#1ad1ff"
_DEFAULT_SPECIAL_LINE_COLOR_HEX = "#ffffff"
_DEFAULT_POINTER_ARROW_COLOR_HEX = "#000000"
_ROUTE_COLOR_BUTTON_HEIGHT = 26
_ROUTE_COLOR_BUTTON_WIDTH = 72
_ROUTE_POINTER_ARROW_BUTTON_WIDTH = 78
_ROUTE_COLOR_FIELDS = (
    ("ROUTE_DEFAULT_COLOR", "默认颜色", _DEFAULT_ROUTE_COLOR_HEX),
    ("ROUTE_TELEPORT_LINE_COLOR", "传送线", _DEFAULT_SPECIAL_LINE_COLOR_HEX),
    ("ROUTE_GUIDE_LINE_COLOR", "引导线", _DEFAULT_SPECIAL_LINE_COLOR_HEX),
    ("ROUTE_POINTER_ARROW_COLOR", "指向箭头", _DEFAULT_POINTER_ARROW_COLOR_HEX),
)
_FOLLOW_ROUTE_COLOR_KEYS = {"ROUTE_TELEPORT_LINE_COLOR", "ROUTE_GUIDE_LINE_COLOR"}
_ROUTE_COLOR_TOOLTIPS = {
    "ROUTE_DEFAULT_COLOR": "路线及节点颜色",
    "ROUTE_TELEPORT_LINE_COLOR": "代表前往传送点的传送路径",
    "ROUTE_GUIDE_LINE_COLOR": "代表引路点的指引路径",
    "ROUTE_POINTER_ARROW_COLOR": "玩家点位到追踪目标节点的指向箭头",
}
_SETTINGS_DISCLAIMER = "本工具免费分享，内置地图与标注数据来源于17173，感谢地图维护者"
_MAP_FILE_PLACEHOLDER = "请选择底图"
_ANNOTATION_FILE_PLACEHOLDER = "请选择标注文件"
_ROUTE_CONVERSION_LOG_LIMIT = 40


class _ElidedLabel(QLabel):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._full_text = str(text or "")
        self.setText(self._full_text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        available_width = max(0, self.width())
        text = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, available_width)
        if text != self.text():
            self.setText(text)


def styled_info(parent, title: str, message: str, *, allow_links: bool = False) -> None:
    dialog = StyledMessage(parent, title, message, allow_links=allow_links)
    center_dialog(dialog, parent)
    dialog.exec()


def styled_confirm(
    parent,
    title: str,
    message: str,
    confirm_text: str = "确定",
    cancel_text: str = "取消",
) -> bool:
    dialog = StyledConfirm(parent, title, message, confirm_text=confirm_text, cancel_text=cancel_text)
    center_dialog(dialog, parent)
    return dialog.exec() == QDialog.Accepted


def _summarize_release_notes(body: str, *, limit: int = 800) -> str:
    text = "\n".join(line.rstrip() for line in str(body or "").strip().splitlines())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def format_update_bytes(size: int) -> str:
    value = float(max(0, int(size or 0)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def format_app_update_message(result: AppUpdateCheckResult) -> str:
    notes = _summarize_release_notes(result.notes)
    parts = [
        f"当前版本：{escape(result.current_version)}",
        f"最新版本：{escape(result.latest_version)}",
        f"更新文件：{len(result.changed_files)} 个",
        f"删除文件：{len(result.delete_files)} 个",
        f"下载大小：{format_update_bytes(result.download_size)}",
    ]
    if result.skipped_conflicts:
        parts.append(f"本地改动冲突：{len(result.skipped_conflicts)} 个文件将跳过")
    parts.append("安装方式：需要重启" if result.requires_restart else "安装方式：不重启热更新")
    if notes:
        parts.extend(["", "更新说明：", escape(notes).replace("\n", "<br>")])
    return "<br>".join(parts)


def format_update_progress_message(downloaded: int, total: int, path: str = "") -> str:
    total = max(0, int(total or 0))
    downloaded = max(0, int(downloaded or 0))
    if total > 0:
        percent = min(100, int(downloaded * 100 / total))
        return f"正在下载更新... {percent}% ({format_update_bytes(downloaded)} / {format_update_bytes(total)})"
    if path:
        return f"正在下载更新... {path}"
    return "正在下载更新..."


class RouteFormatConverterDialog(StyledDialogBase):
    _MODE_NORMALIZE = "normalize"
    _MODE_ANNOTATE = "annotate"
    _OUTPUT_TO_DIR = "output_to_dir"
    _OUTPUT_IN_PLACE = "in_place"

    def __init__(self, parent=None) -> None:
        super().__init__(parent, "路线转换", min_width=680, max_width=860)
        self._mode_combo: QComboBox | None = None
        self._output_row: QWidget | None = None
        self._input_editor: QLineEdit | None = None
        self._output_editor: QLineEdit | None = None
        self._recursive_checkbox: QCheckBox | None = None
        self._overwrite_checkbox: QCheckBox | None = None
        self._output_to_dir_button: QPushButton | None = None
        self._overwrite_source_button: QPushButton | None = None
        self._output_mode = self._OUTPUT_TO_DIR
        self._annotation_options: QWidget | None = None
        self._match_types_button: QPushButton | None = None
        self._teleport_types_button: QPushButton | None = None
        self._match_radius_spin: QSpinBox | None = None
        self._annotation_type_items: list[dict] = []
        self._match_type_ids: list[str] = []
        self._teleport_type_ids: list[str] = []
        self._log: QPlainTextEdit | None = None
        self._build_ui()
        self.resize(760, 520)

    def _build_ui(self) -> None:
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        mode_row = QWidget(self)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        mode_label = QLabel("转换模式")
        mode_label.setObjectName("FieldLabel")
        mode_layout.addWidget(mode_label)
        mode_combo = QComboBox(self)
        mode_combo.addItem("旧路线转新格式", self._MODE_NORMALIZE)
        mode_combo.addItem("为路线自动添加标注", self._MODE_ANNOTATE)
        mode_combo.currentIndexChanged.connect(self._sync_mode_ui)
        self._mode_combo = mode_combo
        mode_layout.addWidget(mode_combo, stretch=1)
        layout.addWidget(mode_row)

        self._input_editor = self._build_path_row(layout, "输入目录", config.app_path("routes"), self._choose_input)
        self._output_editor = self._build_path_row(
            layout,
            "输出目录",
            config.app_path("routes_converted"),
            self._choose_output,
        )

        option_row = QWidget(self)
        option_layout = QHBoxLayout(option_row)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(8)

        recursive_checkbox = QCheckBox("包含子文件夹")
        recursive_checkbox.setChecked(True)
        self._recursive_checkbox = recursive_checkbox
        option_layout.addWidget(recursive_checkbox)

        overwrite_checkbox = QCheckBox("覆盖已存在输出")
        overwrite_checkbox.setChecked(False)
        self._overwrite_checkbox = overwrite_checkbox
        option_layout.addWidget(overwrite_checkbox)

        output_to_dir_button = self._build_output_mode_button("输出到新目录", self._OUTPUT_TO_DIR)
        self._output_to_dir_button = output_to_dir_button
        option_layout.addWidget(output_to_dir_button)

        overwrite_source_button = self._build_output_mode_button("覆盖源文件", self._OUTPUT_IN_PLACE)
        self._overwrite_source_button = overwrite_source_button
        option_layout.addWidget(overwrite_source_button)
        option_layout.addStretch()
        layout.addWidget(option_row)

        self._annotation_options = self._build_annotation_options(layout)

        start_btn = QPushButton("开始转换")
        start_btn.setFixedHeight(32)
        start_btn.clicked.connect(self._start_conversion)
        layout.addWidget(start_btn)

        log = QPlainTextEdit(self)
        log.setReadOnly(True)
        log.setMinimumHeight(220)
        log.setPlaceholderText("转换日志")
        self._log = log
        layout.addWidget(log, stretch=1)
        self.shell_layout.addWidget(content, stretch=1)
        self.add_action_row(confirm_text="关闭", cancel_text="")
        self._sync_mode_ui()

    def _build_output_mode_button(self, text: str, mode: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("SettingsTabButton")
        button.setCheckable(True)
        button.setMinimumHeight(24)
        button.clicked.connect(lambda _checked=False, value=mode: self._set_output_mode(value))
        return button

    def _build_annotation_options(self, layout: QVBoxLayout) -> QWidget:
        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)

        type_row = QWidget(panel)
        type_layout = QHBoxLayout(type_row)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(8)

        match_button = QPushButton("匹配标注类型：未加载")
        match_button.setMinimumHeight(30)
        match_button.clicked.connect(self._choose_match_types)
        self._match_types_button = match_button
        type_layout.addWidget(match_button, stretch=1)

        teleport_button = QPushButton("传送点类型：未加载")
        teleport_button.setMinimumHeight(30)
        teleport_button.clicked.connect(self._choose_teleport_types)
        self._teleport_types_button = teleport_button
        type_layout.addWidget(teleport_button, stretch=1)
        panel_layout.addWidget(type_row)

        radius_row = QWidget(panel)
        radius_layout = QHBoxLayout(radius_row)
        radius_layout.setContentsMargins(0, 0, 0, 0)
        radius_layout.setSpacing(8)
        radius_label = QLabel("最大匹配半径")
        radius_label.setObjectName("FieldLabel")
        radius_layout.addWidget(radius_label)
        radius_spin = QSpinBox(panel)
        radius_spin.setRange(1, 100)
        radius_spin.setValue(12)
        radius_spin.setSuffix(" px")
        self._match_radius_spin = radius_spin
        radius_layout.addWidget(radius_spin)
        hint = QLabel("批量模式在半径内直接采用最近标注；可疑候选会写入日志。")
        hint.setObjectName("StatLabel")
        hint.setWordWrap(True)
        radius_layout.addWidget(hint, stretch=1)
        panel_layout.addWidget(radius_row)

        layout.addWidget(panel)
        return panel

    def _build_path_row(self, layout: QVBoxLayout, label_text: str, value: str, callback) -> QLineEdit:
        row = QWidget(self)
        if label_text == "输出目录":
            self._output_row = row
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        row_layout.addWidget(label)
        editor = QLineEdit(value)
        editor.setMinimumHeight(28)
        row_layout.addWidget(editor, stretch=1)
        button = QPushButton("浏览")
        button.setFixedHeight(28)
        button.clicked.connect(callback)
        row_layout.addWidget(button)
        layout.addWidget(row)
        return editor

    def _current_mode(self) -> str:
        if self._mode_combo is None:
            return self._MODE_NORMALIZE
        return str(self._mode_combo.currentData() or self._MODE_NORMALIZE)

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        annotate = mode == self._MODE_ANNOTATE
        output_to_dir = self._is_output_to_dir()
        if self._output_row is not None:
            self._output_row.setVisible(output_to_dir)
        if self._overwrite_checkbox is not None:
            self._overwrite_checkbox.setVisible(output_to_dir)
        self._sync_output_mode_buttons()
        if self._annotation_options is not None:
            self._annotation_options.setVisible(annotate)
        if self._log is not None:
            if annotate:
                placeholder = "转换日志：会按当前标注文件为路线节点自动补齐 type、typeId 和 node_type"
            else:
                placeholder = "转换日志：会转换坐标并补齐 id，保留 format_version，已有 enable_versions 时追加当前版本"
            self._log.setPlaceholderText(placeholder)
        if annotate:
            self._ensure_annotation_type_defaults()

    def _is_output_to_dir(self) -> bool:
        return self._output_mode == self._OUTPUT_TO_DIR

    def _set_output_mode(self, mode: str) -> None:
        if mode not in {self._OUTPUT_TO_DIR, self._OUTPUT_IN_PLACE}:
            mode = self._OUTPUT_TO_DIR
        self._output_mode = mode
        self._sync_mode_ui()

    def _sync_output_mode_buttons(self) -> None:
        for button, mode in (
            (self._output_to_dir_button, self._OUTPUT_TO_DIR),
            (self._overwrite_source_button, self._OUTPUT_IN_PLACE),
        ):
            if button is None:
                continue
            selected = self._output_mode == mode
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _annotation_file_path(self) -> str:
        return config.selected_annotation_path_from_settings()

    def _ensure_annotation_type_defaults(self) -> None:
        if self._annotation_type_items:
            self._sync_annotation_type_buttons()
            return
        annotation_file = self._annotation_file_path()
        if not annotation_file:
            self._sync_annotation_type_buttons()
            return
        try:
            from tools.route_format_converter import (
                default_route_annotation_type_ids,
                default_route_teleport_type_ids,
            )
            from ui_island.services.annotation_matcher import load_annotation_type_items

            self._annotation_type_items = load_annotation_type_items(annotation_file)
            self._match_type_ids = default_route_annotation_type_ids(annotation_file)
            self._teleport_type_ids = default_route_teleport_type_ids(annotation_file)
        except Exception as exc:
            self._annotation_type_items = []
            self._match_type_ids = []
            self._teleport_type_ids = []
            if self._log is not None:
                self._append_log(f"[警告] 加载标注类型失败：{exc}")
        self._sync_annotation_type_buttons()

    def _sync_annotation_type_buttons(self) -> None:
        match_count = len(normalize_type_ids(self._match_type_ids))
        teleport_count = len(normalize_type_ids(self._teleport_type_ids))
        if self._match_types_button is not None:
            self._match_types_button.setText(f"匹配标注类型：{match_count} 个")
            self._match_types_button.setToolTip("选择参与路线节点自动匹配的标注类型")
        if self._teleport_types_button is not None:
            self._teleport_types_button.setText(f"传送点类型：{teleport_count} 个")
            self._teleport_types_button.setToolTip("匹配到这些类型时，未设置节点类型的路线节点会写为传送点")

    def _choose_match_types(self) -> None:
        self._ensure_annotation_type_defaults()
        selected = open_annotation_type_multi_picker(
            self,
            self._annotation_type_items,
            self._match_type_ids,
            title="选择参与匹配的标注类型",
        )
        if selected is None:
            return
        self._match_type_ids = normalize_type_ids(selected)
        self._teleport_type_ids = [
            type_id for type_id in normalize_type_ids(self._teleport_type_ids) if type_id in set(self._match_type_ids)
        ]
        self._sync_annotation_type_buttons()

    def _choose_teleport_types(self) -> None:
        self._ensure_annotation_type_defaults()
        match_set = set(normalize_type_ids(self._match_type_ids))
        items = [item for item in self._annotation_type_items if str(item.get("typeId") or "") in match_set]
        selected = open_annotation_type_multi_picker(
            self,
            items,
            self._teleport_type_ids,
            title="选择传送点类型",
        )
        if selected is None:
            return
        self._teleport_type_ids = normalize_type_ids(selected)
        self._sync_annotation_type_buttons()

    def _choose_input(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输入目录", self._input_editor.text() if self._input_editor else "")
        if selected and self._input_editor is not None:
            self._input_editor.setText(selected)
            if self._output_editor is not None and not self._output_editor.text().strip():
                self._output_editor.setText(selected)

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输出目录", self._output_editor.text() if self._output_editor else "")
        if selected and self._output_editor is not None:
            self._output_editor.setText(selected)

    def _append_log(self, text: str) -> None:
        if self._log is None:
            return
        self._log.appendPlainText(text)

    def _append_report_log(self, report, log_path: str = "") -> None:
        self._append_log(f"已转换：{report.converted}")
        self._append_log(f"已跳过：{report.skipped}")
        self._append_log(f"已忽略：{report.ignored}")
        if report.points_converted:
            self._append_log(f"已转换点位：{report.points_converted}")
        annotation_total = (
            getattr(report, "annotation_matched", 0)
            + getattr(report, "annotation_unmatched", 0)
            + getattr(report, "annotation_existing_skipped", 0)
            + getattr(report, "annotation_virtual_skipped", 0)
            + getattr(report, "annotation_teleports", 0)
            + getattr(report, "annotation_suspicious", 0)
        )
        if annotation_total:
            self._append_log(f"标注匹配：{report.annotation_matched}")
            self._append_log(f"未匹配默认采集点：{report.annotation_unmatched}")
            self._append_log(f"跳过已有标注：{report.annotation_existing_skipped}")
            self._append_log(f"跳过引路点：{report.annotation_virtual_skipped}")
            self._append_log(f"传送点节点：{report.annotation_teleports}")
            self._append_log(f"可疑候选：{report.annotation_suspicious}")
        self._append_log(f"错误数：{report.errors}")
        if log_path:
            self._append_log(f"完整日志：{log_path}")
        if report.messages:
            self._append_log("")
            shown = report.messages[:_ROUTE_CONVERSION_LOG_LIMIT]
            for message in shown:
                self._append_log(message)
            remaining = len(report.messages) - len(shown)
            if remaining > 0:
                self._append_log(f"... 还有 {remaining} 条，见完整日志")

    def _write_conversion_log(self, report, *, input_dir: str, output_dir: str, mode: str) -> str:
        logs_dir = config.app_path("logs")
        os.makedirs(logs_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(logs_dir, f"route_conversion_{stamp}.log")
        lines = [
            f"时间：{datetime.now().isoformat(timespec='seconds')}",
            f"模式：{mode}",
            f"输入目录：{input_dir}",
            f"输出目录：{output_dir}",
            f"已转换：{report.converted}",
            f"已跳过：{report.skipped}",
            f"已忽略：{report.ignored}",
            f"已转换点位：{report.points_converted}",
            f"标注匹配：{getattr(report, 'annotation_matched', 0)}",
            f"未匹配默认采集点：{getattr(report, 'annotation_unmatched', 0)}",
            f"跳过已有标注：{getattr(report, 'annotation_existing_skipped', 0)}",
            f"跳过引路点：{getattr(report, 'annotation_virtual_skipped', 0)}",
            f"传送点节点：{getattr(report, 'annotation_teleports', 0)}",
            f"可疑候选：{getattr(report, 'annotation_suspicious', 0)}",
            f"错误数：{report.errors}",
            "",
            "明细：",
            *[str(message) for message in report.messages],
            "",
        ]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        return path

    def _show_conversion_error(self, title: str, exc: Exception) -> None:
        self._append_log(f"[错误] {exc}")
        try:
            logs_dir = config.app_path("logs")
            os.makedirs(logs_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(logs_dir, f"route_conversion_error_{stamp}.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(traceback.format_exc())
            self._append_log(f"错误日志：{path}")
        except Exception:
            path = ""
        message = str(exc)
        if path:
            message += f"\n\n详细错误已写入：{path}"
        styled_info(self, title, message)

    def _start_conversion(self) -> None:
        from tools.route_format_converter import (
            RouteAnnotationOptions,
            annotate_route_folder,
            convert_old_big_map_routes_in_place,
            convert_route_folder,
            validate_distinct_output_dir,
        )

        input_dir = self._input_editor.text().strip() if self._input_editor is not None else ""
        mode = self._current_mode()
        if not input_dir:
            styled_info(self, "路线转换", "请先选择输入目录。")
            return
        if self._log is not None:
            self._log.clear()
        try:
            output_to_dir = self._is_output_to_dir()
            output_dir = self._output_editor.text().strip() if self._output_editor is not None else ""
            if output_to_dir and not output_dir:
                styled_info(self, "路线转换", "请先选择输出目录。")
                return

            if mode == self._MODE_ANNOTATE:
                self._ensure_annotation_type_defaults()
                annotation_file = self._annotation_file_path()
                if not annotation_file:
                    styled_info(self, "路线转换", "请先在设置中选择标注文件。")
                    return
                if not self._match_type_ids:
                    styled_info(self, "路线转换", "请先选择至少一个匹配标注类型。")
                    return
                if not output_to_dir:
                    confirmed = styled_confirm(
                        self,
                        "覆盖添加路线标注",
                        "此操作会直接覆盖源路线文件，为未设置标注的节点补齐 type、typeId 和 node_type。\n\n"
                        "正式执行前请先备份原路线文件。确定继续吗？",
                        confirm_text="已备份，开始转换",
                        cancel_text="取消",
                    )
                    if not confirmed:
                        return
                options = RouteAnnotationOptions(
                    annotation_file=annotation_file,
                    match_type_ids=tuple(normalize_type_ids(self._match_type_ids)),
                    teleport_type_ids=tuple(normalize_type_ids(self._teleport_type_ids)),
                    max_radius=float(self._match_radius_spin.value() if self._match_radius_spin is not None else 12),
                )
                report = annotate_route_folder(
                    input_dir,
                    output_dir if output_to_dir else None,
                    options,
                    recursive=self._recursive_checkbox.isChecked() if self._recursive_checkbox is not None else True,
                    overwrite=self._overwrite_checkbox.isChecked() if self._overwrite_checkbox is not None else False,
                    in_place=not output_to_dir,
                )
                refresh_dir = output_dir if output_to_dir else input_dir
            else:
                if output_to_dir:
                    validate_distinct_output_dir(
                        input_dir,
                        output_dir,
                        recursive=self._recursive_checkbox.isChecked() if self._recursive_checkbox is not None else True,
                    )
                    report = convert_route_folder(
                        input_dir,
                        output_dir,
                        recursive=self._recursive_checkbox.isChecked() if self._recursive_checkbox is not None else True,
                        overwrite=self._overwrite_checkbox.isChecked() if self._overwrite_checkbox is not None else False,
                    )
                    refresh_dir = output_dir
                else:
                    confirmed = styled_confirm(
                        self,
                        "覆盖转换路线",
                        "此操作会把旧路线坐标转换为新路线坐标，补齐 id，保留 format_version，已有 enable_versions 时追加当前版本，并直接覆盖源路线文件。\n\n"
                        "正式执行前请先备份原路线文件。确定继续吗？",
                        confirm_text="已备份，开始转换",
                        cancel_text="取消",
                    )
                    if not confirmed:
                        return
                    report = convert_old_big_map_routes_in_place(
                        input_dir,
                        recursive=self._recursive_checkbox.isChecked() if self._recursive_checkbox is not None else True,
                    )
                    refresh_dir = input_dir
        except Exception as exc:
            self._show_conversion_error("路线转换失败", exc)
            return

        log_path = ""
        try:
            log_path = self._write_conversion_log(report, input_dir=input_dir, output_dir=refresh_dir, mode=mode)
        except Exception as exc:
            self._append_log(f"[警告] 写入完整日志失败：{exc}")
        self._append_report_log(report, log_path)
        if report.errors:
            styled_info(self, "路线转换完成", "转换已结束，但存在错误，请查看日志。")
        else:
            toast(self, "路线转换完成")
        if (mode == self._MODE_ANNOTATE) or not self._is_output_to_dir():
            self._refresh_routes_if_needed(refresh_dir)

    def _refresh_routes_if_needed(self, output_dir: str) -> None:
        try:
            output_path = os.path.abspath(output_dir)
            routes_path = os.path.abspath(config.app_path("routes"))
            if os.path.commonpath([output_path, routes_path]) != routes_path:
                return
        except (OSError, ValueError):
            return
        parent = self.parent()
        controller = getattr(parent, "route_panel_controller", None)
        if controller is not None:
            try:
                controller.reload_route_list()
            except Exception as exc:
                self._show_conversion_error("路线列表刷新失败", exc)


class AnnotationFormatConverterDialog(StyledDialogBase):
    _MODE_LEGACY_COORDINATES = "legacy_coordinates"
    _MODE_ANNOTATION_MERGE = "annotation_merge"
    _MODE_OUTSIDE_FORMAT = "outside_format"
    _AUTO_CREATED_TARGET_TEXT = "由工具自动创建到 annotations/ 目录"

    def __init__(self, parent=None) -> None:
        super().__init__(parent, "标注转换", min_width=680, max_width=860)
        self._mode_combo: QComboBox | None = None
        self._old_file_editor: QLineEdit | None = None
        self._new_file_editor: QLineEdit | None = None
        self._new_file_button: QPushButton | None = None
        self._new_file_row: QWidget | None = None
        self._source_version_label: QLabel | None = None
        self._target_version_label: QLabel | None = None
        self._merge_checkbox: QCheckBox | None = None
        self._merge_option_row: QWidget | None = None
        self._start_button: QPushButton | None = None
        self._log: QPlainTextEdit | None = None
        self._last_target_file_text = config.selected_annotation_path_from_settings() or config.ensure_annotations_dir()
        self._build_ui()
        self.resize(760, 480)

    def _build_ui(self) -> None:
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        warning = QLabel("选择转换会在 annotations/ 下生成新标注文件，不会覆盖原文件。但选择合并前请先备份目标文件")
        warning.setObjectName("FieldLabel")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        mode_row = QWidget(self)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(8)
        mode_label = QLabel("转换模式")
        mode_label.setObjectName("FieldLabel")
        mode_layout.addWidget(mode_label)
        mode_combo = QComboBox(self)
        mode_combo.addItem("旧坐标迁移", self._MODE_LEGACY_COORDINATES)
        mode_combo.addItem("标注文件合并", self._MODE_ANNOTATION_MERGE)
        mode_combo.addItem("外部格式转换", self._MODE_OUTSIDE_FORMAT)
        mode_combo.currentIndexChanged.connect(self._sync_mode_ui)
        self._mode_combo = mode_combo
        mode_layout.addWidget(mode_combo, stretch=1)
        layout.addWidget(mode_row)

        self._old_file_editor = self._build_file_row(
            layout,
            "原标注文件",
            config.ensure_annotations_dir(),
            self._choose_old_file,
            include_version_label=True,
            version_role="source",
        )
        self._new_file_editor = self._build_file_row(
            layout,
            "新标注文件",
            self._last_target_file_text,
            self._choose_new_file,
            include_version_label=True,
            version_role="target",
        )
        self._new_file_row = self._new_file_editor.parentWidget()

        option_row = QWidget(self)
        option_layout = QHBoxLayout(option_row)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(8)
        merge_checkbox = QCheckBox("合并到新标注文件")
        merge_checkbox.setChecked(True)
        merge_checkbox.toggled.connect(self._sync_merge_ui)
        self._merge_checkbox = merge_checkbox
        option_layout.addWidget(merge_checkbox)
        option_layout.addStretch()
        layout.addWidget(option_row)
        self._merge_option_row = option_row

        start_btn = QPushButton("开始转换")
        start_btn.setFixedHeight(32)
        start_btn.clicked.connect(self._start_conversion)
        self._start_button = start_btn
        layout.addWidget(start_btn)

        log = QPlainTextEdit(self)
        log.setReadOnly(True)
        log.setMinimumHeight(200)
        log.setPlaceholderText("转换日志")
        self._log = log
        layout.addWidget(log, stretch=1)

        self.shell_layout.addWidget(content, stretch=1)
        self.add_action_row(confirm_text="关闭", cancel_text="")
        self._sync_source_version_label()
        self._sync_mode_ui()

    def _build_file_row(
        self,
        layout: QVBoxLayout,
        label_text: str,
        value: str,
        callback,
        *,
        include_version_label: bool = False,
        version_role: str = "",
    ) -> QLineEdit:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        row_layout.addWidget(label)
        editor = QLineEdit(value)
        editor.setMinimumHeight(28)
        row_layout.addWidget(editor, stretch=1)
        if include_version_label:
            if version_role == "target":
                editor.textChanged.connect(self._sync_target_version_label)
            else:
                editor.textChanged.connect(self._sync_source_version_label)
            version_label = QLabel("创建格式：未识别")
            version_label.setObjectName("FieldLabel")
            version_label.setMinimumWidth(150)
            row_layout.addWidget(version_label)
            if version_role == "target":
                self._target_version_label = version_label
            else:
                self._source_version_label = version_label
        button = QPushButton("浏览")
        button.setFixedHeight(28)
        button.clicked.connect(callback)
        row_layout.addWidget(button)
        if version_role == "target":
            self._new_file_button = button
        layout.addWidget(row)
        return editor

    def _choose_old_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择旧标注数据文件",
            self._old_file_editor.text() if self._old_file_editor else config.ensure_annotations_dir(),
            "标注数据 (*.json)",
        )
        if selected and self._old_file_editor is not None:
            self._old_file_editor.setText(selected)
            self._sync_source_version_label()

    def _choose_new_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择新标注数据文件",
            self._new_file_editor.text() if self._new_file_editor else config.ensure_annotations_dir(),
            "标注数据 (*.json)",
        )
        if selected and self._new_file_editor is not None:
            self._new_file_editor.setText(selected)
            self._sync_target_version_label()

    def _current_mode(self) -> str:
        if self._mode_combo is None:
            return self._MODE_LEGACY_COORDINATES
        return str(self._mode_combo.currentData() or self._MODE_LEGACY_COORDINATES)

    def _source_format_version(self) -> str:
        from tools.annotation_converters.base import source_format_version

        old_file = self._old_file_editor.text().strip() if self._old_file_editor is not None else ""
        return source_format_version(old_file)

    def _target_format_version(self) -> str:
        from tools.annotation_converters.base import source_format_version

        new_file = self._new_file_editor.text().strip() if self._new_file_editor is not None else ""
        if new_file == self._AUTO_CREATED_TARGET_TEXT:
            return resource_metadata.APP_FORMAT_VERSION
        return source_format_version(new_file)

    def _source_format_is_supported(self) -> bool:
        version = self._source_format_version()
        return bool(version and version in resource_metadata.default_enable_versions())

    def _sync_source_version_label(self) -> None:
        if self._source_version_label is None:
            return
        version = self._source_format_version()
        self._source_version_label.setText(f"创建格式：{version or '未识别'}")
        self._sync_mode_ui()

    def _sync_target_version_label(self) -> None:
        if self._target_version_label is None:
            return
        legacy_mode = self._current_mode() == self._MODE_LEGACY_COORDINATES
        legacy_merge = self._merge_checkbox is not None and self._merge_checkbox.isChecked()
        if legacy_mode and not legacy_merge:
            version = resource_metadata.APP_FORMAT_VERSION
        else:
            version = self._target_format_version()
        self._target_version_label.setText(f"创建格式：{version or '未识别'}")

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        legacy_mode = mode == self._MODE_LEGACY_COORDINATES
        annotation_merge_mode = mode == self._MODE_ANNOTATION_MERGE
        legacy_merge = legacy_mode and self._merge_checkbox is not None and self._merge_checkbox.isChecked()
        if self._new_file_row is not None:
            self._new_file_row.setVisible(legacy_mode or annotation_merge_mode)
        if self._merge_option_row is not None:
            self._merge_option_row.setVisible(legacy_mode)
        if self._merge_checkbox is not None:
            self._merge_checkbox.setEnabled(legacy_mode)
        if self._new_file_editor is not None:
            if legacy_mode:
                current_text = self._new_file_editor.text().strip()
                if current_text and current_text != self._AUTO_CREATED_TARGET_TEXT:
                    self._last_target_file_text = self._new_file_editor.text().strip()
                if legacy_merge:
                    if not current_text or current_text == self._AUTO_CREATED_TARGET_TEXT:
                        self._new_file_editor.setText(self._last_target_file_text)
                    self._new_file_editor.setReadOnly(False)
                else:
                    self._new_file_editor.setText(self._AUTO_CREATED_TARGET_TEXT)
                    self._new_file_editor.setReadOnly(True)
                self._new_file_editor.setEnabled(True)
            elif annotation_merge_mode:
                if self._new_file_editor.text().strip() == self._AUTO_CREATED_TARGET_TEXT:
                    self._new_file_editor.setText(self._last_target_file_text)
                self._new_file_editor.setReadOnly(False)
                self._new_file_editor.setEnabled(True)
            else:
                if self._new_file_editor.text().strip() and self._new_file_editor.text().strip() != self._AUTO_CREATED_TARGET_TEXT:
                    self._last_target_file_text = self._new_file_editor.text().strip()
                self._new_file_editor.setReadOnly(True)
                self._new_file_editor.setEnabled(False)
        if self._new_file_button is not None:
            self._new_file_button.setVisible(annotation_merge_mode or legacy_merge)
            self._new_file_button.setEnabled(annotation_merge_mode or legacy_merge)
        self._sync_target_version_label()
        if self._start_button is not None:
            self._start_button.setEnabled(legacy_mode or annotation_merge_mode or mode == self._MODE_OUTSIDE_FORMAT)

    def _sync_merge_ui(self) -> None:
        self._sync_mode_ui()

    def _append_log(self, text: str) -> None:
        if self._log is not None:
            self._log.appendPlainText(text)

    def _start_conversion(self) -> None:
        from tools.annotation_converters.registry import (
            MODE_ANNOTATION_MERGE,
            MODE_LEGACY_COORDINATES,
            MODE_OUTSIDE_FORMAT,
            convert_annotation_file,
        )

        old_file = self._old_file_editor.text().strip() if self._old_file_editor is not None else ""
        new_file = self._new_file_editor.text().strip() if self._new_file_editor is not None else ""
        mode = self._current_mode()
        legacy_mode = mode == self._MODE_LEGACY_COORDINATES
        legacy_merge = legacy_mode and self._merge_checkbox is not None and self._merge_checkbox.isChecked()
        annotation_merge_mode = mode == self._MODE_ANNOTATION_MERGE
        requires_target_file = legacy_merge or annotation_merge_mode
        if new_file == self._AUTO_CREATED_TARGET_TEXT:
            new_file = ""
        if not old_file:
            styled_info(self, "标注转换", "请先选择原标注文件。")
            return
        if mode == self._MODE_OUTSIDE_FORMAT and not self._source_format_is_supported():
            version = self._source_format_version()
            if version:
                styled_info(self, "标注转换", f"暂不兼容：{version}")
            else:
                styled_info(self, "标注转换", "原标注文件缺少 format_version，暂未兼容转换。")
            return
        if requires_target_file and not new_file:
            styled_info(self, "标注转换", "请先选择目标标注文件。")
            return
        if annotation_merge_mode:
            source_version = self._source_format_version()
            target_version = self._target_format_version()
            if not source_version or not target_version:
                styled_info(self, "标注转换", "标注文件缺少 format_version，无法合并。")
                return
            if source_version != target_version:
                styled_info(self, "标注转换", "格式版本不同，无法合并。")
                return
        if requires_target_file:
            confirmed = styled_confirm(
                self,
                "标注转换",
                "合并前请先备份标注数据\n\n转换会在 annotations/ 下生成新的标注文件，不会覆盖旧标注或新标注文件。确定继续吗？",
                confirm_text="已备份，开始转换",
                cancel_text="取消",
            )
            if not confirmed:
                return
        if self._log is not None:
            self._log.clear()

        try:
            registry_mode = MODE_LEGACY_COORDINATES
            if mode == self._MODE_OUTSIDE_FORMAT:
                registry_mode = MODE_OUTSIDE_FORMAT
            elif mode == self._MODE_ANNOTATION_MERGE:
                registry_mode = MODE_ANNOTATION_MERGE
            report = convert_annotation_file(
                registry_mode,
                old_file,
                config.ensure_annotations_dir(),
                merge=legacy_merge,
                merge_with=new_file if requires_target_file else None,
            )
        except Exception as exc:
            self._append_log(f"[错误] {exc}")
            styled_info(self, "标注转换失败", str(exc))
            return

        self._append_log(f"已转换点位：{report.converted_points}")
        self._append_log(f"已跳过点位：{report.skipped_points}")
        self._append_log(f"已去重点位：{report.deduplicated_points}")
        self._append_log(f"错误数：{report.errors}")
        if report.messages:
            self._append_log("")
            for message in report.messages:
                self._append_log(message)
        if report.errors:
            styled_info(self, "标注转换完成", "转换已结束，但存在错误，请查看日志。")
            return

        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_annotation_file_combo_preserving_selection"):
            parent._refresh_annotation_file_combo_preserving_selection()
        toast(self, "标注转换完成，请在标注文件中手动选择后应用")


class SettingsDialog(QDialog):
    applied = Signal()
    restart_requested = Signal()
    annotation_refresh_requested = Signal()
    update_check_finished = Signal(object)
    update_install_finished = Signal(object)
    update_progress_changed = Signal(str)

    _FIXED_WIDTH = 660
    _FIXED_HEIGHT = 620
    _SHELL_H_MARGIN = 18
    _SHELL_TOP_MARGIN = 12
    _SHELL_BOTTOM_MARGIN = 14
    _SECTION_H_MARGIN = 14
    _SECTION_TOP_MARGIN = 12
    _SECTION_BOTTOM_MARGIN = 12
    _TOOLS_SECTION_WIDTH = 136
    _TOOLS_SCROLL_MAX_HEIGHT = 252
    _TOOL_BUTTON_ICONS = {
        "检查更新": "↻",
        "夸克网盘": "☁",
        "路线资源": "◇",
        "更新文档": "▤",
        "问题反馈": "?",
        "标注转换": "⌖",
        "路线转换": "⤳",
    }
    _TOOL_BUTTON_GROUPS = (
        ("常用入口", ("夸克网盘", "路线资源", "更新文档", "问题反馈")),
        ("数据转换", ("标注转换", "路线转换")),
    )
    _TITLE_BAR_TOOL_NAMES = {"检查更新"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        qss.ensure_tooltip_style()
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(qss.ISLAND_QSS)
        self.resize(self._FIXED_WIDTH, self._FIXED_HEIGHT)

        self._drag_offset: QPoint | None = None
        self._editors: dict[str, QLineEdit] = {}
        self._initial_values: dict[str, str] = {}
        self._minimap_editors: dict[str, QLineEdit] = {}
        self._map_dir_combo: QComboBox | None = None
        self._map_file_combo: QComboBox | None = None
        self._annotation_file_combo: QComboBox | None = None
        self._annotation_format_version_label: QLabel | None = None
        self._route_multi_color_checkbox: QCheckBox | None = None
        self._route_special_lines_follow_checkbox: QCheckBox | None = None
        self._route_strict_guide_checkbox: QCheckBox | None = None
        self._route_color_buttons: dict[str, QPushButton] = {}
        self._route_colors = {
            key: self._normalize_route_color(getattr(config, key, default), default)
            for key, _label, default in _ROUTE_COLOR_FIELDS
        }
        self._route_pointer_arrow_visible = bool(getattr(config, "ROUTE_POINTER_ARROW_VISIBLE", True))
        self._route_color_button: QPushButton | None = None
        self._hotkey_editor: QKeySequenceEdit | None = None
        self._route_default_color = self._route_colors["ROUTE_DEFAULT_COLOR"]
        self._opacity_editors: dict[str, QLineEdit] = {}
        self._update_check_button: QPushButton | None = None
        self._update_check_running = False
        self._update_progress_toast: Toast | None = None
        self._build_ui()
        self.update_check_finished.connect(self._on_update_check_finished, Qt.QueuedConnection)
        self.update_install_finished.connect(self._on_update_install_finished, Qt.QueuedConnection)
        self.update_progress_changed.connect(self._on_update_progress_changed, Qt.QueuedConnection)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("IslandRoot")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(18, 12, 18, 14)
        shell_layout.setSpacing(10)
        root.addWidget(shell)

        title_bar = QWidget()
        self._title_bar = title_bar
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        title = QLabel("设置")
        title.setObjectName("TitleLabel")
        title.setStyleSheet("font-size: 14px;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(title)

        subtitle = QLabel("修改后点击“应用”写回 config.json；标记 ⟲ 的参数需重启才生效。")
        subtitle.setObjectName("StatLabel")
        subtitle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_row.addWidget(subtitle, stretch=1)

        check_update_btn = QPushButton(self._settings_tool_button_text("检查更新"))
        check_update_btn.setProperty("settingsTopToolButton", True)
        check_update_btn.setFixedHeight(24)
        check_update_btn.clicked.connect(self._on_check_update_clicked)
        self._update_check_button = check_update_btn
        title_row.addWidget(check_update_btn)

        version_label = QLabel(f"当前版本：{APP_VERSION}")
        version_label.setObjectName("StatLabel")
        version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        version_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_row.addWidget(version_label)

        close_btn = QPushButton("×")
        close_btn.setObjectName("WindowControl")
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn)
        shell_layout.addWidget(title_bar)

        map_file_row = self._build_map_file_row()
        annotation_file_row = self._build_annotation_file_row()
        minimap_row = self._build_minimap_row()
        route_color_row = self._build_route_color_row()
        hotkey_row = self._build_hotkey_row()
        opacity_row = self._build_opacity_row()
        tools_section = self._build_tools_section()

        buttons_bar = QWidget()
        btn_row = QHBoxLayout(buttons_bar)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        disclaimer_label = _ElidedLabel(_SETTINGS_DISCLAIMER)
        disclaimer_label.setObjectName("StatLabel")
        disclaimer_label.setMinimumWidth(0)
        disclaimer_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        disclaimer_label.setToolTip(_SETTINGS_DISCLAIMER)
        btn_row.addWidget(disclaimer_label, stretch=1)

        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._on_reset_defaults)
        btn_row.addWidget(reset_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("应用")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        apply_restart_btn = QPushButton("应用并重启")
        apply_restart_btn.clicked.connect(self._on_apply_and_restart)
        btn_row.addWidget(apply_restart_btn)

        bottom_section_height = 313
        common_section = self._build_common_tabbed_section(
            resource_rows=(map_file_row, annotation_file_row, minimap_row),
            route_rows=(route_color_row, opacity_row),
            interaction_rows=(hotkey_row,),
            param_fields=COMMON_FIELDS,
            section_height=bottom_section_height,
        )
        top_section_max_height = self._compute_top_section_max_height(
            title_bar_height=title_bar.sizeHint().height(),
            bottom_row_height=max(
                common_section.sizeHint().height(),
                tools_section.sizeHint().height(),
            ),
            button_row_height=buttons_bar.sizeHint().height(),
            shell_spacing=shell_layout.spacing(),
        )
        common_section.setFixedHeight(bottom_section_height)
        tools_section.setFixedHeight(bottom_section_height)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        columns.addWidget(
            self._build_section("SIFT 方案", SIFT_FIELDS, max_height=top_section_max_height),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        columns.addWidget(
            self._build_message_section("AI 方案", strings.SETTINGS_AI_DISABLED_MESSAGE),
            stretch=1,
            alignment=Qt.AlignTop,
        )
        shell_layout.addLayout(columns)

        bottom_cols = QHBoxLayout()
        bottom_cols.setSpacing(10)
        bottom_cols.addWidget(common_section, stretch=2, alignment=Qt.AlignTop)
        bottom_cols.addWidget(tools_section, stretch=0, alignment=Qt.AlignTop)
        shell_layout.addLayout(bottom_cols)
        shell_layout.addWidget(buttons_bar)

    def _build_section(
        self,
        title: str,
        fields: list[Field],
        *,
        max_height: int | None = None,
        two_columns: bool = False,
        narrow_editor: bool = False,
        extra_widget: QWidget | None = None,
        extra_widget_position: str = "bottom",
        horizontal_scroll: bool = False,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 13px;")
        title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title_label.setFixedHeight(title_label.sizeHint().height())
        card_layout.addWidget(title_label)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 8)
        body_layout.setSpacing(10)
        if extra_widget is not None and extra_widget_position == "top":
            body_layout.addWidget(extra_widget)

        fields_body = QWidget(body)
        if two_columns:
            outer = QHBoxLayout(fields_body)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(18)
            for chunk in self._split_in_halves(fields):
                col = QVBoxLayout()
                col.setSpacing(10)
                for field in chunk:
                    col.addLayout(self._build_field(field, narrow_editor=narrow_editor))
                col.addStretch()
                outer.addLayout(col, stretch=1)
        else:
            form = QVBoxLayout(fields_body)
            form.setContentsMargins(0, 0, 0, 8)
            form.setSpacing(10)
            for field in fields:
                form.addLayout(self._build_field(field, narrow_editor=narrow_editor))

        body_layout.addWidget(fields_body)
        if extra_widget is not None and extra_widget_position != "top":
            body_layout.addWidget(extra_widget)

        if max_height is not None:
            if horizontal_scroll:
                body.setMinimumWidth(body.sizeHint().width())
                natural = body.sizeHint().height()
            else:
                natural = self._measure_body_height(body, self._estimate_top_section_body_width())
            needs_vertical_scroll = natural > max_height
            if needs_vertical_scroll or horizontal_scroll:
                body.setMinimumHeight(natural)
                fixed_height = max_height if needs_vertical_scroll or horizontal_scroll else natural + 14
                scroll = make_scroll_area(
                    horizontal_policy=Qt.ScrollBarAsNeeded if horizontal_scroll else Qt.ScrollBarAlwaysOff,
                    vertical_policy=Qt.ScrollBarAsNeeded if needs_vertical_scroll else Qt.ScrollBarAlwaysOff,
                    fixed_height=fixed_height,
                )
                scroll.setWidget(body)
                card_layout.addWidget(scroll)
                card_layout.addStretch(1)
                return card

        card_layout.addWidget(body)
        card_layout.addStretch(1)
        return card

    def _build_common_tabbed_section(
        self,
        *,
        resource_rows: tuple[QWidget, ...],
        route_rows: tuple[QWidget, ...],
        interaction_rows: tuple[QWidget, ...],
        param_fields: list[Field],
        section_height: int,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel("通用设置")
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 12px;")
        title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title_label.setFixedHeight(16)
        card_layout.addWidget(title_label)

        tab_bar = QWidget()
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(4)

        stack = QStackedWidget()
        stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        button_group = QButtonGroup(card)
        button_group.setExclusive(True)
        self._common_tab_group = button_group
        self._common_tab_buttons: list[QPushButton] = []

        def _add_tab(label: str, page: QWidget) -> None:
            page_index = stack.addWidget(page)
            button = QPushButton(label)
            button.setObjectName("SettingsTabButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("selected", False)
            button.clicked.connect(lambda _checked=False, idx=page_index: self._activate_common_tab(idx))
            button_group.addButton(button, page_index)
            tab_bar_layout.addWidget(button)
            self._common_tab_buttons.append(button)

        _add_tab("资源", self._build_common_tab_page(resource_rows))
        _add_tab("路线与颜色", self._build_common_tab_page(route_rows))
        _add_tab("快捷键", self._build_common_tab_page(interaction_rows))
        _add_tab("参数", self._build_common_tab_page_fields(param_fields))

        tab_bar_layout.addStretch(1)
        card_layout.addWidget(tab_bar)
        card_layout.addWidget(stack, stretch=1)

        self._common_stack = stack
        if self._common_tab_buttons:
            self._activate_common_tab(0)
        return card

    @staticmethod
    def _build_common_tab_page(rows: tuple[QWidget, ...]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)
        for row in rows:
            layout.addWidget(row)
        layout.addStretch(1)
        return page

    def _build_common_tab_page_fields(self, fields: list[Field]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(18)
        for chunk in self._split_in_halves(fields):
            col = QVBoxLayout()
            col.setSpacing(10)
            for field in chunk:
                col.addLayout(self._build_field(field, narrow_editor=True))
            col.addStretch()
            outer.addLayout(col, stretch=1)
        layout.addLayout(outer)
        layout.addStretch(1)
        return page

    def _activate_common_tab(self, index: int) -> None:
        if not hasattr(self, "_common_stack") or self._common_stack is None:
            return
        self._common_stack.setCurrentIndex(index)
        for i, button in enumerate(self._common_tab_buttons):
            selected = i == index
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_message_section(self, title: str, message: str) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 13px;")
        card_layout.addWidget(title_label)

        body = QLabel(message)
        body.setObjectName("StatLabel")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        card_layout.addWidget(body)
        card_layout.addStretch(1)
        return card

    def _compute_top_section_max_height(
        self,
        *,
        title_bar_height: int,
        bottom_row_height: int,
        button_row_height: int,
        shell_spacing: int,
    ) -> int:
        shell_available = self._FIXED_HEIGHT - self._SHELL_TOP_MARGIN - self._SHELL_BOTTOM_MARGIN
        top_row_total_height = (
            shell_available
            - title_bar_height
            - bottom_row_height
            - button_row_height
            - shell_spacing * 3
        )
        section_chrome = (
            self._SECTION_TOP_MARGIN
            + self._SECTION_BOTTOM_MARGIN
            + 8
            + self._section_title_height()
        )
        return max(160, top_row_total_height - section_chrome)

    def _section_title_height(self) -> int:
        probe = QLabel("X")
        probe.setObjectName("TitleLabel")
        probe.setStyleSheet("font-size: 13px;")
        return probe.sizeHint().height()

    def _estimate_top_section_body_width(self) -> int:
        shell_width = self._FIXED_WIDTH - self._SHELL_H_MARGIN * 2
        row_width = (shell_width - 10) // 2
        return max(160, row_width - self._SECTION_H_MARGIN * 2)

    @staticmethod
    def _measure_body_height(body: QWidget, width: int) -> int:
        layout = body.layout()
        if layout is None:
            return body.sizeHint().height()
        if layout.hasHeightForWidth():
            return layout.totalHeightForWidth(width)
        return max(layout.sizeHint().height(), body.sizeHint().height())

    @staticmethod
    def _split_in_halves(fields: list[Field]) -> list[list[Field]]:
        mid = (len(fields) + 1) // 2
        return [fields[:mid], fields[mid:]]

    @staticmethod
    def _normalize_route_color(value: object, default: str = _DEFAULT_ROUTE_COLOR_HEX) -> str:
        color = QColor(str(value or "").strip())
        if not color.isValid():
            color = QColor(default)
        return color.name(QColor.HexRgb)

    def _build_route_color_row(self) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)

        toggle_row = QWidget()
        toggle_layout = QHBoxLayout(toggle_row)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(8)

        checkbox = QCheckBox("多路线随机颜色")
        checkbox.setChecked(bool(getattr(config, "ROUTE_MULTI_COLOR_ENABLED", True)))
        checkbox.setToolTip("开启后不同路线使用原有稳定随机颜色；关闭后全部路线使用下方默认颜色。")
        self._route_multi_color_checkbox = checkbox
        toggle_layout.addWidget(checkbox)

        follow_checkbox = QCheckBox("传送与引导线跟随路线颜色")
        follow_checkbox.setChecked(bool(getattr(config, "ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", False)))
        follow_checkbox.setToolTip("开启后传送线和引导线使用路线颜色，不使用下方默认颜色。")
        follow_checkbox.toggled.connect(lambda _checked: self._sync_route_color_buttons())
        self._route_special_lines_follow_checkbox = follow_checkbox
        toggle_layout.addWidget(follow_checkbox)

        strict_checkbox = QCheckBox("严格指向模式")
        strict_checkbox.setChecked(bool(getattr(config, "ROUTE_STRICT_GUIDE_MODE", False)))
        strict_checkbox.setToolTip("开启后靠近路线时优先指向该路线中排名最靠前的未到达节点。")
        self._route_strict_guide_checkbox = strict_checkbox
        toggle_layout.addWidget(strict_checkbox)

        toggle_layout.addStretch()
        layout.addWidget(toggle_row)

        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)

        for key, label, _default in _ROUTE_COLOR_FIELDS:
            button = QPushButton(label)
            button.setFixedHeight(_ROUTE_COLOR_BUTTON_HEIGHT)
            button.setFixedWidth(
                _ROUTE_POINTER_ARROW_BUTTON_WIDTH if key == "ROUTE_POINTER_ARROW_COLOR" else _ROUTE_COLOR_BUTTON_WIDTH
            )
            button.clicked.connect(lambda _checked=False, color_key=key: self._on_pick_route_color(color_key))
            if key == "ROUTE_POINTER_ARROW_COLOR":
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(self._show_pointer_arrow_context_menu)
            self._route_color_buttons[key] = button
            if key == "ROUTE_DEFAULT_COLOR":
                self._route_color_button = button
            color_layout.addWidget(button)
        self._sync_route_color_buttons()
        color_layout.addStretch()
        layout.addWidget(color_row)
        return row

    def _build_hotkey_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        label = QLabel("锁定/解锁快捷键")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        editor = QKeySequenceEdit()
        editor.setMaximumSequenceLength(1)
        editor.setFixedHeight(28)
        editor.setKeySequence(hotkey_sequence(getattr(config, "TOGGLE_LOCK_HOTKEY", None)))
        editor.setToolTip("点击后按下新的组合键，需包含 Ctrl、Alt、Shift 或 Win。")
        editor.keySequenceChanged.connect(lambda _sequence: self._sync_hotkey_editor_width())
        self._hotkey_editor = editor
        self._sync_hotkey_editor_width()
        layout.addWidget(editor)

        reset_btn = QPushButton("恢复默认")
        reset_btn.setFixedHeight(28)
        reset_btn.clicked.connect(self._reset_hotkey_to_default)
        layout.addWidget(reset_btn)
        layout.addStretch()
        return row

    def _reset_hotkey_to_default(self) -> None:
        if self._hotkey_editor is None:
            return
        self._hotkey_editor.setKeySequence(hotkey_sequence(config.DEFAULT_CONFIG.get("TOGGLE_LOCK_HOTKEY")))
        self._sync_hotkey_editor_width()

    def _sync_hotkey_editor_width(self) -> None:
        if self._hotkey_editor is None:
            return
        text = self._hotkey_editor.keySequence().toString()
        if not text:
            text = "按下快捷键"
        width = self._hotkey_editor.fontMetrics().horizontalAdvance(text) + 36
        self._hotkey_editor.setFixedWidth(max(92, min(240, width)))

    def _build_opacity_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)

        label = QLabel("透明度")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        for key, title in (
            ("ROUTE_VISITED_POINT_OPACITY", "已达点"),
            ("ROUTE_VISITED_ICON_OPACITY", "已达图标"),
            ("WINDOW_LOCKED_OPACITY", "锁定状态"),
            ("WINDOW_NORMAL_OPACITY", "普通状态"),
        ):
            sub_label = QLabel(title)
            sub_label.setObjectName("StatLabel")
            layout.addWidget(sub_label)

            editor = QLineEdit(str(getattr(config, key, config.DEFAULT_CONFIG.get(key, 1.0))))
            editor.setFixedHeight(26)
            editor.setFixedWidth(48)
            editor.setAlignment(Qt.AlignRight)
            validator = QDoubleValidator(0.0, 1.0, 3, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
            editor.setToolTip("0.0~1.0")
            self._opacity_editors[key] = editor
            layout.addWidget(editor)

        layout.addStretch()
        return row

    def _sync_route_color_button(self) -> None:
        self._sync_route_color_buttons()

    def _sync_route_color_buttons(self) -> None:
        follow = bool(
            self._route_special_lines_follow_checkbox is not None
            and self._route_special_lines_follow_checkbox.isChecked()
        )
        for key, label, default in _ROUTE_COLOR_FIELDS:
            button = self._route_color_buttons.get(key)
            if button is None:
                continue
            color = self._normalize_route_color(self._route_colors.get(key), default)
            self._route_colors[key] = color
            color_value = QColor(color)
            is_light_color = color_value.lightness() > 150
            text_color = "#000000" if is_light_color else "#ffffff"
            border_color = "rgba(20, 20, 20, 0.28)" if is_light_color else "rgba(255, 255, 255, 0.35)"
            disabled = follow and key in _FOLLOW_ROUTE_COLOR_KEYS
            hidden_pointer = key == "ROUTE_POINTER_ARROW_COLOR" and not self._route_pointer_arrow_visible
            font = button.font()
            font.setStrikeOut(hidden_pointer)
            button.setFont(font)
            button.setEnabled(not disabled)
            button.setText(label)
            tooltip = _ROUTE_COLOR_TOOLTIPS.get(key, label)
            if disabled:
                tooltip += "；当前跟随路线颜色"
            if hidden_pointer:
                tooltip += "；当前已隐藏"
            button.setToolTip(tooltip)
            decoration = " text-decoration: line-through;" if hidden_pointer else ""
            size_style = (
                f"min-height: {_ROUTE_COLOR_BUTTON_HEIGHT}px; "
                f"max-height: {_ROUTE_COLOR_BUTTON_HEIGHT}px; padding: 0;"
            )
            if disabled:
                button_qss = (
                    f"QPushButton {{ background: {color}; color: rgba(20, 20, 20, 0.42); "
                    f"border: 1px solid rgba(20, 20, 20, 0.18); {size_style}{decoration} }}"
                )
            else:
                button_qss = (
                    f"QPushButton {{ background: {color}; color: {text_color}; "
                    f"border: 1px solid {border_color}; {size_style}{decoration} }}"
                )
            tooltip_qss = (
                f"QToolTip {{ background: {color}; color: {text_color}; "
                f"border: 1px solid {border_color}; border-radius: 5px; "
                f"padding: 1px 6px; margin: 0px; font-size: 11px; }}"
            )
            button.setStyleSheet(f"{button_qss}\n{tooltip_qss}")
        self._route_default_color = self._route_colors["ROUTE_DEFAULT_COLOR"]

    def _show_pointer_arrow_context_menu(self, pos: QPoint) -> None:
        button = self._route_color_buttons.get("ROUTE_POINTER_ARROW_COLOR")
        if button is None:
            return
        action_text = "隐藏指向箭头" if self._route_pointer_arrow_visible else "显示指向箭头"
        show_context_menu(
            self,
            button.mapToGlobal(pos),
            [ContextMenuItem(action_text, self._toggle_pointer_arrow_visible)],
            object_name="RouteListContextMenu",
        )

    def _toggle_pointer_arrow_visible(self) -> None:
        self._route_pointer_arrow_visible = not self._route_pointer_arrow_visible
        self._sync_route_color_buttons()

    def _on_pick_route_color(self, key: str) -> None:
        field = next((item for item in _ROUTE_COLOR_FIELDS if item[0] == key), None)
        if field is None:
            return
        _field_key, label, default = field
        current = QColor(self._normalize_route_color(self._route_colors.get(key), default))
        color = open_styled_color_picker(
            self,
            f"选择{label}颜色",
            current,
            reset_color=QColor(default),
        )
        if color is None or not color.isValid():
            return
        self._route_colors[key] = color.name(QColor.NameFormat.HexRgb)
        self._sync_route_color_buttons()

    def _sync_route_color_button_legacy(self) -> None:
        if self._route_color_button is None:
            return
        color = self._normalize_route_color(self._route_default_color)
        text_color = "#000000" if QColor(color).lightness() > 150 else "#ffffff"
        self._route_color_button.setText(color)
        self._route_color_button.setStyleSheet(
            f"background: {color}; color: {text_color}; border: 1px solid rgba(255, 255, 255, 0.35);"
        )

    def _on_pick_route_default_color_legacy(self) -> None:
        current = QColor(self._normalize_route_color(self._route_default_color))
        dialog = QColorDialog(current, self)
        dialog.setWindowTitle("选择默认路线颜色")
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dialog.setAttribute(Qt.WA_StyledBackground, True)
        dialog.setStyleSheet(qss.ISLAND_QSS + qss.COLOR_DIALOG_QSS)
        for spin in dialog.findChildren(QSpinBox):
            spin.setFixedWidth(56)
        for editor in dialog.findChildren(QLineEdit):
            editor.setMaximumWidth(96)

        reset_btn = QPushButton("恢复默认颜色", dialog)
        reset_btn.clicked.connect(lambda: dialog.setCurrentColor(QColor(_DEFAULT_ROUTE_COLOR_HEX)))
        layout = dialog.layout()
        if layout is not None:
            layout.addWidget(reset_btn)

        buttons = dialog.findChild(QDialogButtonBox)
        if buttons is not None:
            ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
            cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            if ok_btn is not None:
                ok_btn.setText("确认")
            if cancel_btn is not None:
                cancel_btn.setText("取消")

        center_dialog(dialog, self)
        if dialog.exec() != QDialog.Accepted:
            return
        color = dialog.selectedColor()
        if not color.isValid():
            return
        self._route_default_color = color.name(QColor.NameFormat.HexRgb)
        self._sync_route_color_button()

    def _on_pick_route_default_color(self) -> None:
        self._on_pick_route_color("ROUTE_DEFAULT_COLOR")

    @staticmethod
    def _localize_color_dialog(dialog: QColorDialog) -> None:
        label_map = {
            "&Basic colors": "基础颜色",
            "&Custom colors": "自定义颜色",
            "Hu&e:": "色相:",
            "&Sat:": "饱和度:",
            "&Val:": "明度:",
            "&Red:": "红:",
            "&Green:": "绿:",
            "Bl&ue:": "蓝:",
            "A&lpha channel:": "透明度:",
            "&HTML:": "HTML:",
        }
        button_map = {
            "&Pick Screen Color": "吸取屏幕颜色",
            "&Add to Custom Colors": "添加到自定义颜色",
            "OK": "确认",
            "Cancel": "取消",
        }
        for label in dialog.findChildren(QLabel):
            text = label.text()
            if text in label_map:
                label.setText(label_map[text])
        for button in dialog.findChildren(QPushButton):
            text = button.text()
            if text in button_map:
                button.setText(button_map[text])

    def _build_map_file_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        label = QLabel("地图  *")
        label.setObjectName("FieldLabel")
        label.setToolTip("保存后需要重启生效")
        layout.addWidget(label)

        current = config.normalize_map_file(getattr(config, "MAP_FILE", ""))
        current_dir = config.map_directory_for_file(current)
        dir_combo = QComboBox()
        dir_combo.setFixedHeight(28)
        dir_combo.setMinimumWidth(150)
        dir_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._map_dir_combo = dir_combo
        directories = config.available_map_directories()
        if current_dir not in directories:
            directories.append(current_dir)
        for directory in directories:
            dir_combo.addItem(config.map_directory_display_name(directory), directory)
        self._set_map_directory_value(current_dir)
        dir_combo.currentIndexChanged.connect(lambda _index: self._refresh_map_file_combo())
        layout.addWidget(dir_combo)

        combo = QComboBox()
        combo.setFixedHeight(28)
        combo.setMinimumWidth(190)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._map_file_combo = combo
        self._initial_values["MAP_FILE"] = current
        self._refresh_map_file_combo(current)
        combo.currentIndexChanged.connect(lambda _index: self._sync_map_file_tooltip())
        layout.addWidget(combo)
        choose_btn = QPushButton("选择文件")
        choose_btn.setFixedHeight(28)
        choose_btn.clicked.connect(self._on_choose_map_file)
        layout.addWidget(choose_btn)

        layout.addStretch()
        self._sync_map_file_tooltip()
        return row

    def _current_map_directory_from_combo(self) -> str:
        if self._map_dir_combo is None:
            return config.map_directory_for_file(getattr(config, "MAP_FILE", ""))
        return config.normalize_map_directory(self._map_dir_combo.currentData())

    def _set_map_directory_value(self, directory: object) -> None:
        if self._map_dir_combo is None:
            return
        rel = config.normalize_map_directory(directory)
        index = self._map_dir_combo.findData(rel)
        if index < 0:
            self._map_dir_combo.addItem(config.map_directory_display_name(rel), rel)
            index = self._map_dir_combo.findData(rel)
        if index >= 0:
            self._map_dir_combo.blockSignals(True)
            self._map_dir_combo.setCurrentIndex(index)
            self._map_dir_combo.blockSignals(False)

    def _select_map_file_combo_value(self, map_file: object) -> None:
        if self._map_file_combo is None:
            return
        rel = config.normalize_map_file(map_file)
        index = self._map_file_combo.findData(rel)
        if index < 0:
            index = self._map_file_combo.findData("")
        if index >= 0:
            self._map_file_combo.setCurrentIndex(index)

    def _refresh_map_file_combo(self, preferred: object | None = None) -> None:
        if self._map_file_combo is None:
            return
        current = config.normalize_map_file(preferred if preferred is not None else self._map_file_combo.currentData())
        if preferred is not None and current:
            self._set_map_directory_value(config.map_directory_for_file(current))
        self._map_file_combo.blockSignals(True)
        self._map_file_combo.clear()
        self._map_file_combo.addItem(_MAP_FILE_PLACEHOLDER, "")
        files = config.available_map_files_in_directory(self._current_map_directory_from_combo())
        if files:
            for rel in files:
                self._map_file_combo.addItem(config.map_display_name(rel), rel)
            if current not in files and os.path.isfile(config.resolve_app_path(current)):
                self._map_file_combo.addItem(config.map_display_name(current), current)
            self._map_file_combo.setEnabled(True)
        else:
            self._map_file_combo.setEnabled(True)
        self._map_file_combo.blockSignals(False)
        self._select_map_file_combo_value(current)
        self._sync_map_file_tooltip()

    def _on_choose_map_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择底图文件",
            config.resolve_app_path(self._current_map_directory_from_combo()) or config.ensure_maps_dir(),
            "地图图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not selected:
            return
        try:
            rel = config.import_map_file(selected, destination_dir=self._current_map_directory_from_combo())
        except Exception as exc:
            styled_info(self, "选择底图失败", f"无法导入底图文件：{exc}")
            return

        if self._map_file_combo is not None:
            self._refresh_map_file_combo(rel)

        toast(self, "底图已加入 maps/，点击应用并重启后生效；自定义底图可能导致路线/标注偏移")

    def _set_map_combo_value(self, map_file: object) -> None:
        if self._map_file_combo is None:
            return
        rel = config.normalize_map_file(map_file)
        if rel:
            self._set_map_directory_value(config.map_directory_for_file(rel))
        self._refresh_map_file_combo(rel)

    def _sync_map_file_tooltip(self) -> None:
        if self._map_file_combo is None:
            return
        if not self._map_file_combo.currentData():
            self._map_file_combo.setToolTip("请先选择底图文件")
        elif not config.available_map_files():
            self._map_file_combo.setToolTip("请把底图文件放入 maps 文件夹后重启")
        else:
            self._map_file_combo.setToolTip("保存后需要重启生效；自定义底图可能导致路线/标注偏移")

    def _build_annotation_file_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        label = QLabel("标注文件")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        combo = QComboBox()
        combo.setFixedHeight(28)
        combo.setMinimumWidth(220)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        current = config.selected_annotation_file_from_settings()
        files = config.available_annotation_files()
        combo.addItem(_ANNOTATION_FILE_PLACEHOLDER, "")
        for rel in files:
            combo.addItem(config.annotation_display_name(rel), rel)
        self._annotation_file_combo = combo
        self._initial_values["ANNOTATION_FILE"] = current
        self._set_annotation_combo_value(current)
        combo.currentIndexChanged.connect(lambda _index: self._sync_annotation_file_state())
        layout.addWidget(combo)

        version_label = QLabel("创建版本：未选择")
        version_label.setObjectName("FieldLabel")
        version_label.setMinimumWidth(150)
        self._annotation_format_version_label = version_label
        layout.addWidget(version_label)

        choose_btn = QPushButton("选择文件")
        choose_btn.setFixedHeight(28)
        choose_btn.clicked.connect(self._on_choose_annotation_file)
        layout.addWidget(choose_btn)

        layout.addStretch()
        self._sync_annotation_file_state()
        return row

    def _on_choose_annotation_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择标注数据文件",
            config.ensure_annotations_dir(),
            "标注数据 (*.json)",
        )
        if not selected:
            return
        try:
            rel = config.import_annotation_file(selected)
        except Exception as exc:
            styled_info(self, "选择标注失败", f"无法导入标注数据文件：{exc}")
            return
        if self._annotation_file_combo is not None:
            if self._annotation_file_combo.findData(rel) < 0:
                self._annotation_file_combo.addItem(config.annotation_display_name(rel), rel)
            self._set_annotation_combo_value(rel)
        toast(self, "标注文件已加入 annotations/，点击应用后生效")

    def _set_annotation_combo_value(self, annotation_file: object) -> None:
        if self._annotation_file_combo is None:
            return
        rel = config.normalize_annotation_file(annotation_file)
        index = self._annotation_file_combo.findData(rel)
        if index < 0:
            index = self._annotation_file_combo.findData("")
        if index >= 0:
            self._annotation_file_combo.setCurrentIndex(index)
        self._sync_annotation_file_state()

    def _refresh_annotation_file_combo_preserving_selection(self) -> None:
        if self._annotation_file_combo is None:
            return
        current = config.normalize_annotation_file(self._annotation_file_combo.currentData())
        self._annotation_file_combo.blockSignals(True)
        self._annotation_file_combo.clear()
        self._annotation_file_combo.addItem(_ANNOTATION_FILE_PLACEHOLDER, "")
        files = config.available_annotation_files()
        for rel in files:
            self._annotation_file_combo.addItem(config.annotation_display_name(rel), rel)
        index = self._annotation_file_combo.findData(current)
        if index < 0:
            index = self._annotation_file_combo.findData("")
        if index >= 0:
            self._annotation_file_combo.setCurrentIndex(index)
        self._annotation_file_combo.blockSignals(False)
        self._sync_annotation_file_state()

    def _sync_annotation_file_tooltip(self) -> None:
        if self._annotation_file_combo is None:
            return
        rel = self._annotation_file_combo.currentData()
        if not rel:
            self._annotation_file_combo.setToolTip("请先选择标注文件；不选择则不显示标注")
            return
        path = config.resolve_app_path(rel)
        if path and os.path.isfile(path):
            self._annotation_file_combo.setToolTip("保存后用于地图标注显示和编辑")
        else:
            self._annotation_file_combo.setToolTip("未找到标注文件，可选择 JSON 文件导入 annotations/")

    def _sync_annotation_format_version_label(self) -> None:
        if self._annotation_format_version_label is None or self._annotation_file_combo is None:
            return
        rel = config.normalize_annotation_file(self._annotation_file_combo.currentData())
        if not rel:
            self._annotation_format_version_label.setText("创建版本：未选择")
            return
        path = config.resolve_app_path(rel)
        payload = resource_metadata.read_json_payload(path)
        version = resource_metadata.format_version_as_enable_version(payload)
        self._annotation_format_version_label.setText(f"创建版本：{version or '未识别'}")

    def _sync_annotation_file_state(self) -> None:
        self._sync_annotation_file_tooltip()
        self._sync_annotation_format_version_label()

    def _build_minimap_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        label = QLabel("小地图")
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        minimap_control_height = 26

        set_btn = QPushButton("设置小地图")
        set_btn.setFixedHeight(minimap_control_height)
        set_btn.clicked.connect(self._on_open_minimap_calibrator)
        layout.addWidget(set_btn)

        raw = getattr(config, "MINIMAP", None) or {}
        for key, title in (("top", "Top"), ("left", "Left"), ("width", "W"), ("height", "H")):
            lbl = QLabel(title)
            lbl.setObjectName("StatLabel")
            layout.addWidget(lbl)
            editor = QLineEdit()
            editor.setFixedHeight(minimap_control_height)
            editor.setFixedWidth(48)
            editor.setStyleSheet("padding: 2px 6px;")
            editor.setAlignment(Qt.AlignRight)
            editor.setValidator(QIntValidator(-10_000, 10_000, editor))
            try:
                editor.setText(str(int(raw[key])))
            except (KeyError, TypeError, ValueError):
                editor.setText("")
            self._minimap_editors[key] = editor
            layout.addWidget(editor)
        layout.addStretch()
        return row

    def _on_open_minimap_calibrator(self) -> None:
        from .minimap_selector import run_minimap_calibrator

        self.hide()
        saved = run_minimap_calibrator(None)
        self.show()
        self.raise_()
        self.activateWindow()
        if saved:
            self._refresh_minimap_editors()
            self.applied.emit()
            toast(self, "小地图区域已更新")

    def _refresh_minimap_editors(self) -> None:
        raw = getattr(config, "MINIMAP", None) or {}
        for key, editor in self._minimap_editors.items():
            try:
                editor.setText(str(int(raw[key])))
            except (KeyError, TypeError, ValueError):
                editor.setText("")

    def _build_tools_section(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PanelCard")
        card.setFixedWidth(self._TOOLS_SECTION_WIDTH)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_label = QLabel("工具")
        title_label.setObjectName("TitleLabel")
        title_label.setStyleSheet("font-size: 12px;")
        title_label.setFixedHeight(16)
        card_layout.addWidget(title_label)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)

        grouped_names = set()
        for group_index, (group_title, names) in enumerate(self._TOOL_BUTTON_GROUPS):
            if group_index > 0:
                body_layout.addSpacing(4)
            if group_title != "常用入口":
                group_label = QLabel(group_title)
                group_label.setObjectName("SettingsToolGroupLabel")
                body_layout.addWidget(group_label)
            for name in names:
                grouped_names.add(name)
                body_layout.addWidget(self._build_settings_tool_button(name))

        for name in TOOL_BUTTONS:
            if name not in grouped_names and name not in self._TITLE_BAR_TOOL_NAMES:
                body_layout.addWidget(self._build_settings_tool_button(name))
        body_layout.addStretch(1)

        scroll = make_scroll_area(
            object_name="SettingsToolsScroll",
            max_height=self._TOOLS_SCROLL_MAX_HEIGHT,
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            vertical_policy=Qt.ScrollBarAsNeeded,
            size_policy=(QSizePolicy.Preferred, QSizePolicy.Expanding),
        )
        scroll.setWidget(body)
        card_layout.addWidget(scroll, stretch=1)
        return card

    @classmethod
    def _settings_tool_button_text(cls, name: str) -> str:
        icon = cls._TOOL_BUTTON_ICONS.get(name, "")
        return f"{icon} {name}" if icon else name

    def _build_settings_tool_button(self, name: str) -> QPushButton:
        btn = QPushButton()
        btn.setMinimumHeight(26)
        btn.setProperty("settingsToolButton", True)
        self._decorate_settings_tool_button(btn, name)
        if name in {"标注转换", "路线转换"}:
            btn.setProperty("settingsConversionButton", True)
        if name == "夸克网盘":
            btn.setToolTip("提供夸克网盘最新链接下载")
            btn.clicked.connect(self._on_quark_download_clicked)
        elif name == "路线资源":
            btn.setToolTip("使用默认浏览器打开 config.json 中配置的路线资源链接")
            btn.clicked.connect(self._on_route_resource_clicked)
        elif name == "更新文档":
            btn.setToolTip("使用默认浏览器打开更新文档链接")
            btn.clicked.connect(self._on_documentation_clicked)
        elif name == "问题反馈":
            btn.setToolTip("查看问题反馈与交流方式")
            btn.clicked.connect(self._on_feedback_clicked)
        elif name == "标注转换":
            btn.setToolTip("将旧标注坐标转换为当前标注坐标")
            btn.clicked.connect(self._on_annotation_converter_clicked)
        elif name == "路线转换":
            btn.setToolTip("批量把旧路线 JSON 另存为当前元数据格式")
            btn.clicked.connect(self._on_route_converter_clicked)
        else:
            btn.clicked.connect(lambda _=False, n=name: styled_info(self, n, f"“{n}”功能尚未实现。"))
        return btn

    def _decorate_settings_tool_button(self, button: QPushButton, name: str) -> None:
        icon_label = QLabel(self._TOOL_BUTTON_ICONS.get(name, ""), button)
        icon_label.setObjectName("SettingsToolButtonIcon")
        icon_label.setFixedWidth(16)
        icon_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        text_label = QLabel(name, button)
        text_label.setObjectName("SettingsToolButtonText")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        right_balance = QWidget(button)
        right_balance.setFixedWidth(16)
        right_balance.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(button)
        layout.setContentsMargins(7, 0, 7, 0)
        layout.setSpacing(0)
        layout.addWidget(icon_label)
        layout.addWidget(text_label, stretch=1)
        layout.addWidget(right_balance)

    def _on_annotation_converter_clicked(self) -> None:
        dialog = AnnotationFormatConverterDialog(self)
        center_dialog(dialog, self)
        dialog.exec()

    def _on_route_converter_clicked(self) -> None:
        dialog = RouteFormatConverterDialog(self)
        center_dialog(dialog, self)
        dialog.exec()

    def _on_quark_download_clicked(self) -> None:
        url = str(getattr(config, "QUARK_DOWNLOAD_URL", "") or "").strip()
        if not url:
            styled_info(
                self,
                "夸克网盘",
                "暂未从更新源获取到夸克网盘链接，请稍后再试或检查更新源配置。",
            )
            return
        styled_info(
            self,
            "夸克网盘",
            "最新版本夸克网盘下载链接：<br><br>"
            f'<a href="{escape(url, quote=True)}">{escape(url)}</a>',
            allow_links=True,
        )

    def _on_route_resource_clicked(self) -> None:
        links, had_configured_links = self._configured_route_resource_links()
        if links:
            body = "<br>".join(
                f'<a href="{escape(url, quote=True)}">{escape(name)}</a>'
                for name, url in links
            )
            styled_info(
                self,
                "路线资源",
                "可用路线资源：<br><br>" + body,
                allow_links=True,
            )
            return

        if had_configured_links:
            styled_info(
                self,
                "路线资源",
                "更新源下发的路线资源链接无效，请检查 runtime_config.json 中的配置。",
            )
            return

        styled_info(
            self,
            "路线资源",
            "暂未从更新源获取到路线资源链接，请稍后再试或检查更新源配置。",
        )

    @staticmethod
    def _configured_route_resource_links() -> tuple[list[tuple[str, str]], bool]:
        raw_links = getattr(config, "ROUTE_RESOURCE_LINKS", None)
        configured_links: list[tuple[str, str]] = []
        if isinstance(raw_links, list):
            for item in raw_links:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                url = str(item.get("url") or "").strip()
                if name and url:
                    configured_links.append((name, url))

        links = [
            (name, clean_url)
            for name, url in configured_links
            for clean_url in [SettingsDialog._valid_http_url(url)]
            if clean_url
        ]
        if links or configured_links:
            return links, bool(configured_links)

        legacy_url = str(getattr(config, "ROUTE_RESOURCE_URL", "") or "").strip()
        if not legacy_url:
            return [], False
        clean_legacy_url = SettingsDialog._valid_http_url(legacy_url)
        if not clean_legacy_url:
            return [], True
        return [("路线资源", clean_legacy_url)], False

    @staticmethod
    def _valid_http_url(value: str) -> str:
        qurl = QUrl.fromUserInput(str(value or "").strip())
        if not qurl.isValid() or qurl.scheme() not in {"http", "https"}:
            return ""
        return qurl.toString()

    def _on_documentation_clicked(self) -> None:
        url = str(getattr(config, "DOCUMENTATION_URL", "") or "").strip()
        if not url:
            styled_info(
                self,
                "更新文档",
                "暂未从更新源获取到更新文档链接，请稍后再试或检查更新源配置。",
            )
            return

        qurl = QUrl.fromUserInput(url)
        if not qurl.isValid() or qurl.scheme() not in {"http", "https"}:
            styled_info(
                self,
                "更新文档",
                "更新源下发的更新文档链接无效，请检查 runtime_config.json 中的配置。",
            )
            return

        if not QDesktopServices.openUrl(qurl):
            styled_info(self, "更新文档", "无法打开更新文档链接，请检查系统默认浏览器设置。")

    def _on_feedback_clicked(self) -> None:
        bilibili_url = str(getattr(config, "FEEDBACK_BILIBILI_URL", "") or "").strip()
        qq_group = str(getattr(config, "FEEDBACK_QQ_GROUP", "") or "").strip()

        if bilibili_url:
            qurl = QUrl.fromUserInput(bilibili_url)
            if qurl.isValid() and qurl.scheme() in {"http", "https"}:
                bilibili_text = f'<a href="{escape(qurl.toString(), quote=True)}">{escape(bilibili_url)}</a>'
            else:
                bilibili_text = escape(bilibili_url)
        else:
            bilibili_text = "未配置"

        qq_text = escape(qq_group) if qq_group else "未配置"
        styled_info(
            self,
            "问题反馈",
            f"B站链接：{bilibili_text}<br>GMT-N交流QQ群：{qq_text}",
            allow_links=True,
        )

    def _on_check_update_clicked(self) -> None:
        if self._update_check_running:
            return
        self._update_check_running = True
        if self._update_check_button is not None:
            self._update_check_button.setEnabled(False)
            self._update_check_button.setText("正在检查更新...")

        def worker() -> None:
            result = check_app_update()
            try:
                self.update_check_finished.emit(result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_finished(self, result: object) -> None:
        self._update_check_running = False
        if self._update_check_button is not None:
            self._update_check_button.setEnabled(True)
            self._update_check_button.setText(self._settings_tool_button_text("检查更新"))

        if not isinstance(result, AppUpdateCheckResult):
            styled_info(
                self,
                strings.UPDATE_ERROR_CHECK_TITLE,
                strings.with_update_error_hint(strings.UPDATE_ERROR_CHECK_UNKNOWN),
            )
            return
        if not result.ok:
            styled_info(
                self,
                strings.UPDATE_ERROR_CHECK_TITLE,
                strings.with_update_error_hint(result.error or strings.UPDATE_ERROR_UNKNOWN),
            )
            return
        if not result.has_update:
            styled_info(self, "检查更新", f"当前已是最新版本：{result.current_version}")
            return

        if result.requires_restart:
            confirmed = styled_confirm(
                self,
                "发现程序更新",
                format_app_update_message(result).replace("<br>", "\n")
                + "\n\n此更新将下载变化文件，然后自动关闭并重启程序完成安装。",
                confirm_text="下载并重启更新",
                cancel_text="稍后",
            )
            if confirmed:
                self._start_restart_update(result)
            return

        confirmed = styled_confirm(
            self,
            "发现资源更新",
            format_app_update_message(result).replace("<br>", "\n"),
            confirm_text="下载并更新",
            cancel_text="稍后",
        )
        if confirmed:
            self._start_non_restart_update(result)

    def _start_non_restart_update(self, result: AppUpdateCheckResult) -> None:
        self._update_check_running = True
        if self._update_check_button is not None:
            self._update_check_button.setEnabled(False)
            self._update_check_button.setText("正在下载更新...")
        self._show_update_progress("正在准备更新...")

        def worker() -> None:
            staging = None
            try:
                progress = self._make_update_progress_callback()
                staging = download_changed_files(result, progress_callback=progress)
                self.update_progress_changed.emit("正在安装更新...")
                install_result = install_non_restart_update(result, staging)
            except Exception as exc:
                install_result = AppUpdateInstallResult(ok=False, version=result.latest_version, error=str(exc))
            finally:
                if staging is not None:
                    cleanup_staging(staging)
            try:
                self.update_install_finished.emit(install_result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _start_restart_update(self, result: AppUpdateCheckResult) -> None:
        self._update_check_running = True
        if self._update_check_button is not None:
            self._update_check_button.setEnabled(False)
            self._update_check_button.setText("正在准备重启更新...")
        self._show_update_progress("正在准备更新...")

        def worker() -> None:
            staging = None
            try:
                progress = self._make_update_progress_callback()
                staging = download_changed_files(result, progress_callback=progress)
                self.update_progress_changed.emit("正在启动更新器...")
                install_result = start_restart_update(result, staging)
            except Exception as exc:
                if staging is not None:
                    cleanup_staging(staging)
                install_result = AppUpdateInstallResult(
                    ok=False,
                    version=result.latest_version,
                    requires_restart=True,
                    error=str(exc),
                )
            try:
                self.update_install_finished.emit(install_result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_progress(self, message: str) -> None:
        if self._update_progress_toast is None:
            self._update_progress_toast = toast_persistent(self, message)
            return
        try:
            self._update_progress_toast.update_message(message)
        except RuntimeError:
            self._update_progress_toast = toast_persistent(self, message)

    def _on_update_progress_changed(self, message: str) -> None:
        self._show_update_progress(str(message or "正在更新..."))

    def _clear_update_progress(self) -> None:
        if self._update_progress_toast is None:
            return
        try:
            self._update_progress_toast.dismiss()
        except RuntimeError:
            pass
        self._update_progress_toast = None

    def _make_update_progress_callback(self):
        last_percent = {"value": -1}

        def callback(downloaded: int, total: int, path: str) -> None:
            if total > 0:
                percent = min(100, int(max(0, downloaded) * 100 / total))
                if percent == last_percent["value"]:
                    return
                last_percent["value"] = percent
            self.update_progress_changed.emit(format_update_progress_message(downloaded, total, path))

        return callback

    def _on_update_install_finished(self, result: object) -> None:
        self._update_check_running = False
        self._clear_update_progress()
        if self._update_check_button is not None:
            self._update_check_button.setEnabled(True)
            self._update_check_button.setText(self._settings_tool_button_text("检查更新"))

        if not isinstance(result, AppUpdateInstallResult):
            styled_info(
                self,
                strings.UPDATE_ERROR_INSTALL_TITLE,
                strings.with_update_error_hint(strings.UPDATE_ERROR_INSTALL_UNKNOWN),
            )
            return
        if not result.ok:
            styled_info(
                self,
                strings.UPDATE_ERROR_INSTALL_TITLE,
                strings.with_update_error_hint(result.error or strings.UPDATE_ERROR_UNKNOWN),
            )
            return

        if result.requires_restart:
            styled_info(self, "正在重启更新", "更新器已启动，程序即将关闭并完成安装。")
            QTimer.singleShot(300, QApplication.quit)
            return

        self._refresh_updated_resources()
        conflict_msg = ""
        if result.skipped_conflicts:
            conflict_msg = f"\n\n已跳过 {len(result.skipped_conflicts)} 个用户修改过的文件。"
        styled_info(
            self,
            "更新完成",
            f"资源已更新到 {result.version}，并已保留你的个人配置。{conflict_msg}",
        )

    @staticmethod
    def _format_app_update_message(result: AppUpdateCheckResult) -> str:
        return format_app_update_message(result)

    @staticmethod
    def _format_bytes(size: int) -> str:
        return format_update_bytes(size)

    def _refresh_updated_resources(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        try:
            route_mgr = getattr(parent, "route_mgr", None)
            if route_mgr is not None:
                route_mgr.invalidate_annotation_cache(icons=True)
        except Exception:
            pass
        controller = getattr(parent, "route_panel_controller", None)
        if controller is not None:
            try:
                controller.reload_route_list()
            except Exception:
                pass
        annotation_panel = getattr(parent, "annotation_panel", None)
        if annotation_panel is not None:
            try:
                annotation_panel.load_index(config.selected_annotation_path_from_settings())
                annotation_panel.set_preferences(parent.annotation_type_ids)
            except Exception:
                pass
        map_view = getattr(parent, "map_view", None)
        if map_view is not None:
            try:
                map_view._refresh_from_last_frame()
            except Exception:
                pass

    def _build_field(self, field: Field, *, narrow_editor: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(8)

        left_wrap = QWidget()
        left_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        left = QVBoxLayout(left_wrap)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)

        label_text = field.label
        if field.needs_restart:
            label_text += "  ⟲"
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        label.setWordWrap(True)
        if field.needs_restart:
            label.setToolTip("此参数需要重启应用后才生效")
        left.addWidget(label)

        if field.value_range or field.desc:
            desc = QLabel(self._format_desc(field))
            desc.setObjectName("StatLabel")
            desc.setWordWrap(True)
            desc.setTextFormat(Qt.RichText)
            desc.setTextInteractionFlags(Qt.NoTextInteraction)
            desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            left.addWidget(desc)

        editor = QLineEdit(str(getattr(config, field.key, "")))
        editor.setMinimumHeight(28)
        editor.setFixedWidth(32 if narrow_editor else 60)
        if narrow_editor:
            editor.setStyleSheet("padding: 5px;")
        editor.setAlignment(Qt.AlignRight)
        if field.type_ is int:
            editor.setValidator(QIntValidator(-10_000_000, 10_000_000, editor))
        else:
            validator = QDoubleValidator(-1e9, 1e9, 4, editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
        self._editors[field.key] = editor
        self._initial_values[field.key] = editor.text()
        left_wrap.setMinimumHeight(editor.minimumHeight())
        row.addWidget(left_wrap, stretch=1, alignment=Qt.AlignVCenter)
        row.addWidget(editor, alignment=Qt.AlignVCenter)
        return row

    @staticmethod
    def _format_desc(field: Field) -> str:
        parts: list[str] = []
        if field.value_range:
            parts.append(f'<span style="color:{tokens.ACCENT}; font-weight:600;">{field.value_range}</span>')
        if field.desc:
            parts.append(field.desc)
        return " · ".join(parts)

    def _collect(self) -> dict | None:
        result: dict = {}
        for field in ALL_FIELDS:
            editor = self._editors.get(field.key)
            if editor is None:
                continue
            raw = editor.text().strip()
            if raw == "":
                continue
            try:
                result[field.key] = field.type_(raw) if field.type_ is int else float(raw)
            except ValueError:
                styled_info(
                    self,
                    "输入无效",
                    f"字段 {field.label} 的值“{raw}”无法解析为 {field.type_.__name__}。",
                )
                return None

        if self._map_file_combo is not None:
            selected_map = self._map_file_combo.currentData()
            result["MAP_FILE"] = config.normalize_map_file(selected_map)
        if self._annotation_file_combo is not None:
            selected_annotation = self._annotation_file_combo.currentData()
            result["ANNOTATION_FILE"] = config.normalize_annotation_file(selected_annotation)

        if self._route_multi_color_checkbox is not None:
            result["ROUTE_MULTI_COLOR_ENABLED"] = self._route_multi_color_checkbox.isChecked()
        if self._route_special_lines_follow_checkbox is not None:
            result["ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR"] = self._route_special_lines_follow_checkbox.isChecked()
        if self._route_strict_guide_checkbox is not None:
            result["ROUTE_STRICT_GUIDE_MODE"] = self._route_strict_guide_checkbox.isChecked()
        result["ROUTE_POINTER_ARROW_VISIBLE"] = bool(self._route_pointer_arrow_visible)
        for key, _label, default in _ROUTE_COLOR_FIELDS:
            self._route_colors[key] = self._normalize_route_color(self._route_colors.get(key), default)
            result[key] = self._route_colors[key]
        self._route_default_color = self._route_colors["ROUTE_DEFAULT_COLOR"]
        if self._hotkey_editor is not None:
            hotkey_payload, hotkey_error = payload_from_key_sequence(self._hotkey_editor.keySequence())
            if hotkey_payload is None:
                styled_info(self, "快捷键无效", hotkey_error or "请重新录入一个有效快捷键。")
                return None
            result["TOGGLE_LOCK_HOTKEY"] = hotkey_payload
        for key, editor in self._opacity_editors.items():
            raw = editor.text().strip()
            if raw == "":
                continue
            try:
                result[key] = max(0.0, min(1.0, float(raw)))
            except ValueError:
                styled_info(self, "输入无效", f"透明度 {raw} 不是有效数字。")
                return None

        minimap_payload: dict = {}
        for key, editor in self._minimap_editors.items():
            raw = editor.text().strip()
            if raw == "":
                minimap_payload = {}
                break
            try:
                minimap_payload[key] = int(raw)
            except ValueError:
                styled_info(self, "输入无效", f"小地图 {key} 的值“{raw}”不是有效整数。")
                return None
        if len(minimap_payload) == 4:
            result["MINIMAP"] = {
                "top": minimap_payload["top"],
                "left": minimap_payload["left"],
                "width": minimap_payload["width"],
                "height": minimap_payload["height"],
            }
        return result

    def _changed_restart_fields(self, values: dict) -> list[str]:
        changed: list[str] = []
        if "MAP_FILE" in values and str(values["MAP_FILE"]) != self._initial_values.get("MAP_FILE", ""):
            changed.append("底图")
        for key, new_val in values.items():
            field = FIELD_INDEX.get(key)
            if field is None or not field.needs_restart:
                continue
            if str(new_val) != self._initial_values.get(key, ""):
                changed.append(field.label)
        return changed

    def _persist(self, values: dict) -> bool:
        try:
            config.save_config(values)
        except Exception as exc:
            styled_info(self, "保存失败", f"写入 config.json 失败：{exc}")
            return False
        self.applied.emit()
        for key, value in values.items():
            self._initial_values[key] = str(value)
        return True

    def _on_apply(self) -> None:
        values = self._collect()
        if values is None:
            return
        restart_fields = self._changed_restart_fields(values)
        if not self._persist(values):
            return
        if restart_fields:
            styled_info(
                self,
                "需要重启",
                "已保存，但以下参数需要重启应用后才会生效：\n\n  " + "\n  ".join(restart_fields),
            )
        else:
            toast(self, "设置已应用")

    def _on_apply_and_restart(self) -> None:
        values = self._collect()
        if values is None:
            return
        if not self._persist(values):
            return
        self.close()
        self.restart_requested.emit()

    def _on_reset_defaults(self) -> None:
        for field in ALL_FIELDS:
            editor = self._editors.get(field.key)
            if editor is None:
                continue
            default_val = config.DEFAULT_CONFIG.get(field.key, "")
            editor.setText(str(default_val))
        if self._route_multi_color_checkbox is not None:
            self._route_multi_color_checkbox.setChecked(bool(config.DEFAULT_CONFIG.get("ROUTE_MULTI_COLOR_ENABLED", True)))
        if self._route_special_lines_follow_checkbox is not None:
            self._route_special_lines_follow_checkbox.setChecked(
                bool(config.DEFAULT_CONFIG.get("ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", False))
            )
        if self._route_strict_guide_checkbox is not None:
            self._route_strict_guide_checkbox.setChecked(
                bool(config.DEFAULT_CONFIG.get("ROUTE_STRICT_GUIDE_MODE", False))
            )
        self._route_pointer_arrow_visible = bool(config.DEFAULT_CONFIG.get("ROUTE_POINTER_ARROW_VISIBLE", True))
        for key, _label, default in _ROUTE_COLOR_FIELDS:
            self._route_colors[key] = self._normalize_route_color(config.DEFAULT_CONFIG.get(key, default), default)
        self._route_default_color = self._route_colors["ROUTE_DEFAULT_COLOR"]
        self._sync_route_color_buttons()
        self._reset_hotkey_to_default()
        for key, editor in self._opacity_editors.items():
            editor.setText(str(config.DEFAULT_CONFIG.get(key, 1.0)))
        self._refresh_map_file_combo(config.DEFAULT_CONFIG.get("MAP_FILE", ""))
        self._set_annotation_combo_value(config.DEFAULT_CONFIG.get("ANNOTATION_FILE", ""))

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


def _restart_app() -> None:
    try:
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception:
        pass
    python = sys.executable
    os.execl(python, python, *sys.argv)


_active_dialog: SettingsDialog | None = None


def open_settings_dialog(
    parent,
    on_applied: Callable[[], None] | None = None,
    on_closed: Callable[[], None] | None = None,
    on_annotation_refresh_requested: Callable[[], None] | None = None,
) -> None:
    global _active_dialog
    if _active_dialog is not None:
        try:
            _active_dialog.raise_()
            _active_dialog.activateWindow()
            return
        except RuntimeError:
            _active_dialog = None

    dialog = SettingsDialog(parent)
    if on_applied is not None:
        dialog.applied.connect(on_applied)
    if on_annotation_refresh_requested is not None:
        dialog.annotation_refresh_requested.connect(on_annotation_refresh_requested)
    dialog.restart_requested.connect(_restart_app)

    def _clear_ref():
        global _active_dialog
        _active_dialog = None
        if on_closed is not None:
            on_closed()

    dialog.destroyed.connect(lambda _=None: _clear_ref())
    _active_dialog = dialog
    if parent is not None:
        place_left_of(dialog, parent)
    dialog.show()


def close_active_settings_dialog() -> bool:
    global _active_dialog
    if _active_dialog is None:
        return False
    try:
        _active_dialog.close()
        return True
    except RuntimeError:
        _active_dialog = None
        return False


def has_active_settings_dialog() -> bool:
    return _active_dialog is not None

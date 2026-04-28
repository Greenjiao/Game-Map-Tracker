"""岛状界面的设置对话框和统一提示辅助函数。"""

from __future__ import annotations

import os
import sys
import threading
from html import escape
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDoubleValidator, QIntValidator, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QKeySequenceEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import config

from . import StyledConfirm, StyledDialogBase, StyledMessage, Toast, center_dialog, place_left_of, toast, toast_persistent
from ..app.app_info import APP_VERSION
from ..design import qss, strings, tokens
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
_SETTINGS_DISCLAIMER = "本工具免费分享，地图与标注数据来源于17173，感谢地图维护者"


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
    _TOOLS_SECTION_WIDTH = 112

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

        minimap_row = self._build_minimap_row()
        route_color_row = self._build_route_color_row()
        hotkey_row = self._build_hotkey_row()
        opacity_row = self._build_opacity_row()
        common_extra = self._build_common_extra(minimap_row, opacity_row, route_color_row, hotkey_row)
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

        common_probe = self._build_section(
            "通用设置",
            COMMON_FIELDS,
            two_columns=True,
            narrow_editor=True,
            extra_widget=common_extra,
            extra_widget_position="top",
        )
        top_section_max_height = self._compute_top_section_max_height(
            title_bar_height=title_bar.sizeHint().height(),
            bottom_row_height=max(
                common_probe.sizeHint().height(),
                tools_section.sizeHint().height(),
            ),
            button_row_height=buttons_bar.sizeHint().height(),
            shell_spacing=shell_layout.spacing(),
        )
        bottom_section_height = 313
        bottom_section_body_height = (
            bottom_section_height
            - self._SECTION_TOP_MARGIN
            - self._SECTION_BOTTOM_MARGIN
            - 8
            - self._section_title_height()
        )
        common_section = self._build_section(
            "通用设置",
            COMMON_FIELDS,
            max_height=bottom_section_body_height,
            two_columns=True,
            narrow_editor=True,
            extra_widget=common_extra,
            extra_widget_position="top",
            horizontal_scroll=True,
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
    def _build_common_extra(*widgets: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for widget in widgets:
            layout.addWidget(widget)
        return container

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
                button.setStyleSheet(
                    f"background: {color}; color: rgba(20, 20, 20, 0.42); "
                    f"border: 1px solid rgba(20, 20, 20, 0.18); {size_style}{decoration}"
                )
            else:
                button.setStyleSheet(
                    f"background: {color}; color: {text_color}; border: 1px solid {border_color}; "
                    f"{size_style}{decoration}"
                )
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
        dialog = StyledDialogBase(self, f"选择{label}颜色", min_width=560, max_width=720)

        picker = QColorDialog(current, dialog)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        picker.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        picker.setAttribute(Qt.WA_StyledBackground, True)
        picker.setStyleSheet(qss.COLOR_DIALOG_QSS)
        picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._localize_color_dialog(picker)

        for spin in picker.findChildren(QSpinBox):
            spin.setFixedWidth(56)
        for editor in picker.findChildren(QLineEdit):
            editor.setMaximumWidth(96)

        dialog.shell_layout.addWidget(picker)

        button_row = QHBoxLayout()
        reset_btn = QPushButton("恢复默认颜色", dialog)
        reset_btn.clicked.connect(lambda: picker.setCurrentColor(QColor(default)))
        button_row.addWidget(reset_btn)
        button_row.addStretch()

        cancel_btn = QPushButton("取消", dialog)
        cancel_btn.clicked.connect(dialog.reject)
        button_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("确认", dialog)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(dialog.accept)
        button_row.addWidget(confirm_btn)
        dialog.shell_layout.addLayout(button_row)

        center_dialog(dialog, self)
        if dialog.exec() != QDialog.Accepted:
            return
        color = picker.currentColor()
        if not color.isValid():
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

    def _build_minimap_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 6, 0)
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
        title_label.setStyleSheet("font-size: 13px;")
        card_layout.addWidget(title_label)

        for name in TOOL_BUTTONS:
            btn = QPushButton(name)
            btn.setMinimumHeight(30)
            if name == "检查更新":
                self._update_check_button = btn
                btn.clicked.connect(self._on_check_update_clicked)
            elif name == "夸克网盘":
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
            elif name == strings.ANNOTATION_REFRESH_POINTS:
                btn.setToolTip(strings.ANNOTATION_REFRESH_POINTS_TOOLTIP)
                btn.clicked.connect(self.annotation_refresh_requested.emit)
            else:
                btn.clicked.connect(
                    lambda _=False, n=name: styled_info(self, n, f"“{n}”功能尚未实现。")
                )
            card_layout.addWidget(btn)
        card_layout.addStretch()
        return card

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
        url = str(getattr(config, "ROUTE_RESOURCE_URL", "") or "").strip()
        if not url:
            styled_info(
                self,
                "路线资源",
                "暂未从更新源获取到路线资源链接，请稍后再试或检查更新源配置。",
            )
            return

        qurl = QUrl.fromUserInput(url)
        if not qurl.isValid() or qurl.scheme() not in {"http", "https"}:
            styled_info(
                self,
                "路线资源",
                "更新源下发的路线资源链接无效，请检查 runtime_config.json 中的配置。",
            )
            return

        if not QDesktopServices.openUrl(qurl):
            styled_info(self, "路线资源", "无法打开路线资源链接，请检查系统默认浏览器设置。")

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
            self._update_check_button.setText("检查更新")

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
            self._update_check_button.setText("检查更新")

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
                route_mgr._annotation_points_cache = None
                route_mgr._point_icon_cache.clear()
                route_mgr._annotation_icon_cache.clear()
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
                annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
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

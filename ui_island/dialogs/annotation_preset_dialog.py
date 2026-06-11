"""Dialog for creating and editing annotation display presets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..services.annotation_preferences import normalize_type_ids
from ..widgets.annotation_type_widgets import AnnotationGroupSection, build_annotation_type_button, group_annotation_types
from ..widgets.factory import make_error_label, make_scroll_area
from . import StyledDialogBase, center_dialog


class AnnotationPresetDialog(StyledDialogBase):
    _COLUMNS = 3

    def __init__(
        self,
        parent,
        items: list[dict],
        *,
        preset: dict | None = None,
        existing_names: set[str] | None = None,
    ) -> None:
        title = "修改标注预设方案" if preset else "新增标注预设方案"
        super().__init__(parent, title, min_width=560, max_width=560)
        self._items = list(items)
        self._preset = dict(preset or {})
        self._existing_names = set(existing_names or set())
        self._selected_type_ids = set(normalize_type_ids(self._preset.get("type_ids")))
        self._selected: dict | None = None
        self._buttons_by_type_id: dict[str, QPushButton] = {}
        self._group_expanded = getattr(parent, "annotation_group_expanded", {})
        if not isinstance(self._group_expanded, dict):
            self._group_expanded = {}
        self._group_expanded_changed = getattr(parent, "_on_annotation_group_expanded_changed", None)

        name_label = QLabel("方案名称")
        name_label.setObjectName("FieldLabel")
        self.shell_layout.addWidget(name_label)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入预设方案名称...")
        self._name_edit.setText(str(self._preset.get("name") or ""))
        self.shell_layout.addWidget(self._name_edit)

        type_label = QLabel("选择要纳入此方案的标注")
        type_label.setObjectName("FieldLabel")
        self.shell_layout.addWidget(type_label)

        if not self._items:
            empty = QLabel("未找到可用标注，请先在设置中选择或拉取标注文件")
            empty.setWordWrap(True)
            empty.setObjectName("DimLabel")
            self.shell_layout.addWidget(empty)
        else:
            self._build_type_list()

        self._error_label = make_error_label(object_name="AnnotationPanelMessage")
        self.shell_layout.addWidget(self._error_label)

        self.add_action_row(confirm_text="保存", cancel_text="取消", on_confirm=self._save)
        self.adjustSize()

    def _build_type_list(self) -> None:
        scroll = make_scroll_area(
            object_name="AnnotationPanelScroll",
            horizontal_policy=Qt.ScrollBarAlwaysOff,
            min_height=180,
            max_height=330,
        )

        host = QWidget()
        host.setObjectName("AnnotationPanelInner")
        groups_layout = QVBoxLayout(host)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(8)

        for group_name, group_items in group_annotation_types(self._items):
            section = AnnotationGroupSection(
                group_name,
                self._group_expanded.get(group_name, True),
                columns=self._COLUMNS,
                parent=host,
            )
            section.expanded_changed.connect(self._set_group_expanded)
            for index, item in enumerate(group_items):
                button = self._build_type_button(item)
                if button is not None:
                    section.add_row(button, index)
            groups_layout.addWidget(section)

        groups_layout.addStretch(1)
        scroll.setWidget(host)
        self.shell_layout.addWidget(scroll, stretch=1)

    def _build_type_button(self, item: dict) -> QPushButton | None:
        type_id = str(item.get("typeId") or "")
        if not type_id:
            return None
        button = build_annotation_type_button(
            item,
            selected=type_id in self._selected_type_ids,
            icon_size=None,
        )
        button.clicked.connect(lambda _checked=False, tid=type_id: self._toggle_type(tid))
        self._buttons_by_type_id[type_id] = button
        return button

    def _toggle_type(self, type_id: str) -> None:
        if type_id in self._selected_type_ids:
            self._selected_type_ids.remove(type_id)
        else:
            self._selected_type_ids.add(type_id)
        button = self._buttons_by_type_id.get(type_id)
        if button is not None:
            selected = type_id in self._selected_type_ids
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_group_expanded(self, group_name: str, expanded: bool) -> None:
        self._group_expanded[group_name] = bool(expanded)
        if callable(self._group_expanded_changed):
            self._group_expanded_changed(self._group_expanded)

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()

    def _save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._show_error("请输入预设方案名称。")
            return
        if name in self._existing_names:
            self._show_error("已有同名预设方案，请换一个名称。")
            return
        visible_ids = [str(item.get("typeId") or "") for item in self._items]
        visible_selected_ids = [type_id for type_id in visible_ids if type_id in self._selected_type_ids]
        unknown_selected_ids = [
            type_id
            for type_id in normalize_type_ids(self._preset.get("type_ids"))
            if type_id in self._selected_type_ids and type_id not in visible_selected_ids
        ]
        type_ids = normalize_type_ids([*visible_selected_ids, *unknown_selected_ids])
        if not type_ids:
            self._show_error("请至少选择一个标注类型。")
            return
        self._selected = {
            "id": str(self._preset.get("id") or ""),
            "name": name,
            "type_ids": type_ids,
        }
        self.accept()

    def selected_preset(self) -> dict | None:
        return dict(self._selected) if self._selected is not None else None


def open_annotation_preset_dialog(
    parent,
    items: list[dict],
    *,
    preset: dict | None = None,
    existing_names: set[str] | None = None,
) -> dict | None:
    dialog = AnnotationPresetDialog(parent, items, preset=preset, existing_names=existing_names)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_preset()
    return None

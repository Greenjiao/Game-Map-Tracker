"""Dialog for choosing an annotation type for a route node."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from ..design import strings
from ..services.annotation_preferences import normalize_type_ids
from ..services.annotation_matcher import AnnotationMatchCandidate
from ..widgets.annotation_type_widgets import (
    AnnotationGroupSection,
    annotation_icon_path,
    build_annotation_type_button,
    group_annotation_types,
)
from ..widgets.factory import make_error_label, make_scroll_area
from . import StyledDialogBase, center_dialog, place_left_of, place_right_of


class AnnotationTypePickerDialog(StyledDialogBase):
    _COLUMNS = 3

    def __init__(
        self,
        parent,
        items: list[dict],
        current_type_id: str = "",
        *,
        include_clear: bool = False,
    ) -> None:
        super().__init__(parent, strings.ANNOTATION_TYPE_PICKER_TITLE, min_width=560, max_width=560)
        self._items = list(items)
        self._current_type_id = str(current_type_id or "")
        self._include_clear = bool(include_clear)
        self._selected: dict | None = None
        self._group_expanded = getattr(parent, "annotation_group_expanded", {})
        if not isinstance(self._group_expanded, dict):
            self._group_expanded = {}
        self._group_expanded_changed = getattr(parent, "_on_annotation_group_expanded_changed", None)

        if self._include_clear:
            clear_button = QPushButton(strings.ANNOTATION_TYPE_PICKER_CLEAR)
            clear_button.setObjectName("AnnotationTypeRow")
            clear_button.setProperty("selected", not bool(self._current_type_id))
            clear_button.setCheckable(True)
            clear_button.setChecked(not bool(self._current_type_id))
            clear_button.clicked.connect(lambda _checked=False: self._select({"clear": True}))
            self.shell_layout.addWidget(clear_button)

        if not self._items:
            empty = QLabel(strings.ANNOTATION_TYPE_PICKER_EMPTY)
            empty.setWordWrap(True)
            empty.setObjectName("DimLabel")
            self.shell_layout.addWidget(empty)
            self._add_cancel_row()
            self.adjustSize()
            return

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

        for group_name, group_items in self._grouped_items():
            section = AnnotationGroupSection(
                group_name,
                self._group_expanded.get(group_name, True),
                columns=self._COLUMNS,
                parent=host,
            )
            section.expanded_changed.connect(self._set_group_expanded)
            for index, item in enumerate(group_items):
                button = self._build_type_button(item)
                section.add_row(button, index)
            groups_layout.addWidget(section)

        groups_layout.addStretch(1)

        scroll.setWidget(host)
        self.shell_layout.addWidget(scroll, stretch=1)
        self._add_cancel_row()
        self.adjustSize()

    def _grouped_items(self) -> list[tuple[str, list[dict]]]:
        return group_annotation_types(self._items)

    def _build_type_button(self, item: dict) -> QPushButton:
        type_id = str(item.get("typeId") or "")
        button = build_annotation_type_button(
            item,
            selected=bool(type_id and type_id == self._current_type_id),
            icon_size=None,
        )
        button.clicked.connect(lambda _checked=False, known_item=dict(item): self._select(known_item))
        return button

    def _set_group_expanded(self, group_name: str, expanded: bool) -> None:
        self._group_expanded[group_name] = bool(expanded)
        if callable(self._group_expanded_changed):
            self._group_expanded_changed(self._group_expanded)

    def _add_cancel_row(self) -> None:
        self.add_action_row(cancel_text=strings.ANNOTATION_TYPE_PICKER_CANCEL)

    def _select(self, item: dict) -> None:
        self._selected = item
        self.accept()

    def selected_item(self) -> dict | None:
        return dict(self._selected) if self._selected is not None else None


def open_annotation_type_picker(
    parent,
    items: list[dict],
    current_type_id: str = "",
    *,
    include_clear: bool = False,
    placement: str = "center",
    anchor: QWidget | None = None,
) -> dict | None:
    dialog = AnnotationTypePickerDialog(parent, items, current_type_id, include_clear=include_clear)
    placement_anchor = anchor or parent
    if placement == "left_of" and placement_anchor is not None:
        place_left_of(dialog, placement_anchor)
    elif placement == "right_of" and placement_anchor is not None:
        place_right_of(dialog, placement_anchor)
    else:
        center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_item()
    return None


class AnnotationMatchCandidatePickerDialog(StyledDialogBase):
    def __init__(
        self,
        parent,
        candidates: list[AnnotationMatchCandidate],
        *,
        title: str = "选择匹配标注",
    ) -> None:
        super().__init__(parent, title, min_width=520, max_width=560)
        self._candidates = list(candidates)
        self._selected: AnnotationMatchCandidate | None = None

        if not self._candidates:
            empty = QLabel(strings.ANNOTATION_TYPE_PICKER_EMPTY)
            empty.setWordWrap(True)
            empty.setObjectName("DimLabel")
            self.shell_layout.addWidget(empty)
        else:
            scroll = make_scroll_area(
                object_name="AnnotationPanelScroll",
                horizontal_policy=Qt.ScrollBarAlwaysOff,
                min_height=120,
                max_height=300,
            )
            host = QWidget()
            host.setObjectName("AnnotationPanelInner")
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            for candidate in self._candidates:
                layout.addWidget(self._build_candidate_button(candidate))
            layout.addStretch(1)
            scroll.setWidget(host)
            self.shell_layout.addWidget(scroll, stretch=1)

        self.add_action_row(cancel_text=strings.ANNOTATION_TYPE_PICKER_CANCEL)
        self.adjustSize()

    def _build_candidate_button(self, candidate: AnnotationMatchCandidate) -> QPushButton:
        label = candidate.label or f"#{candidate.point_index + 1}"
        text = f"{candidate.type_name or candidate.type_id}  ·  {label}  ·  {candidate.distance:.1f}px"
        button = QPushButton(text)
        button.setObjectName("AnnotationTypeRow")
        button.setProperty("selected", False)
        button.setCheckable(True)
        button.setIconSize(QSize(20, 20))
        icon_path = annotation_icon_path({"typeId": candidate.type_id, "type": candidate.type_name}, candidate.type_id)
        if icon_path.exists():
            button.setIcon(QIcon(QPixmap(str(icon_path))))
        button.clicked.connect(lambda _checked=False, known_candidate=candidate: self._select(known_candidate))
        return button

    def _select(self, candidate: AnnotationMatchCandidate) -> None:
        self._selected = candidate
        self.accept()

    def selected_candidate(self) -> AnnotationMatchCandidate | None:
        return self._selected


def open_annotation_match_candidate_picker(
    parent,
    candidates: list[AnnotationMatchCandidate],
    *,
    title: str = "选择匹配标注",
) -> AnnotationMatchCandidate | None:
    dialog = AnnotationMatchCandidatePickerDialog(parent, candidates, title=title)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_candidate()
    return None


class AnnotationTypeMultiSelectDialog(StyledDialogBase):
    _COLUMNS = 3

    def __init__(
        self,
        parent,
        items: list[dict],
        selected_type_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        *,
        title: str = "选择标注类型",
        empty_text: str = "未找到可用标注，请先在设置中选择或拉取标注文件",
    ) -> None:
        super().__init__(parent, title, min_width=560, max_width=560)
        self._items = list(items)
        self._selected_type_ids = set(normalize_type_ids(list(selected_type_ids or [])))
        self._selected: list[str] | None = None
        self._buttons_by_type_id: dict[str, QPushButton] = {}
        self._group_expanded = getattr(parent, "annotation_group_expanded", {})
        if not isinstance(self._group_expanded, dict):
            self._group_expanded = {}
        self._group_expanded_changed = getattr(parent, "_on_annotation_group_expanded_changed", None)

        if not self._items:
            empty = QLabel(empty_text)
            empty.setWordWrap(True)
            empty.setObjectName("DimLabel")
            self.shell_layout.addWidget(empty)
        else:
            self._build_type_list()

        self._error_label = make_error_label(object_name="AnnotationPanelMessage")
        self.shell_layout.addWidget(self._error_label)

        self.add_action_row(confirm_text="确定", cancel_text=strings.ANNOTATION_TYPE_PICKER_CANCEL, on_confirm=self._save)
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
            group_type_ids = self._type_ids_for_items(group_items)
            section = AnnotationGroupSection(
                group_name,
                self._group_expanded.get(group_name, True),
                columns=self._COLUMNS,
                show_batch_actions=True,
                select_all_tooltip="选中当前分类所有标注类型",
                invert_select_tooltip="反转当前分类标注类型选择状态",
                parent=host,
            )
            section.expanded_changed.connect(self._set_group_expanded)
            if section.select_all_btn is not None:
                section.select_all_btn.clicked.connect(
                    lambda _checked=False, tids=tuple(group_type_ids): self._set_group_types(tids, True)
                )
            if section.invert_select_btn is not None:
                section.invert_select_btn.clicked.connect(
                    lambda _checked=False, tids=tuple(group_type_ids): self._invert_group_types(tids)
                )
            for index, item in enumerate(group_items):
                button = self._build_type_button(item)
                if button is not None:
                    section.add_row(button, index)
            groups_layout.addWidget(section)

        groups_layout.addStretch(1)
        scroll.setWidget(host)
        self.shell_layout.addWidget(scroll, stretch=1)

    @staticmethod
    def _type_ids_for_items(items: list[dict]) -> list[str]:
        return normalize_type_ids([str(item.get("typeId") or "") for item in items])

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
        self._sync_type_buttons([type_id])

    def _set_group_types(self, type_ids: tuple[str, ...], selected: bool) -> None:
        normalized = normalize_type_ids(list(type_ids))
        if selected:
            self._selected_type_ids.update(normalized)
        else:
            self._selected_type_ids.difference_update(normalized)
        self._sync_type_buttons(normalized)

    def _invert_group_types(self, type_ids: tuple[str, ...]) -> None:
        normalized = normalize_type_ids(list(type_ids))
        for type_id in normalized:
            if type_id in self._selected_type_ids:
                self._selected_type_ids.remove(type_id)
            else:
                self._selected_type_ids.add(type_id)
        self._sync_type_buttons(normalized)

    def _sync_type_buttons(self, type_ids: list[str] | tuple[str, ...] | set[str] | None = None) -> None:
        known_type_ids = normalize_type_ids(list(type_ids)) if type_ids is not None else list(self._buttons_by_type_id)
        for type_id in known_type_ids:
            button = self._buttons_by_type_id.get(type_id)
            if button is None:
                continue
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
        visible_ids = [str(item.get("typeId") or "") for item in self._items]
        selected = normalize_type_ids([type_id for type_id in visible_ids if type_id in self._selected_type_ids])
        if not selected:
            self._show_error("请至少选择一个标注类型。")
            return
        self._selected = selected
        self.accept()

    def selected_type_ids(self) -> list[str] | None:
        return list(self._selected) if self._selected is not None else None


def open_annotation_type_multi_picker(
    parent,
    items: list[dict],
    selected_type_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    *,
    title: str = "选择标注类型",
) -> list[str] | None:
    dialog = AnnotationTypeMultiSelectDialog(parent, items, selected_type_ids, title=title)
    center_dialog(dialog, parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_type_ids()
    return None

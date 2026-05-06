from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..design.strings import (
    LICENSE_DIALOG_CANCEL,
    LICENSE_DIALOG_CONFIRM,
    LICENSE_DIALOG_HINT_FMT,
    LICENSE_DIALOG_PLACEHOLDER,
    LICENSE_DIALOG_TITLE,
    LICENSE_HINT_NO_QQ_GROUPS,
)
from .base import StyledDialogBase, center_dialog


def _format_qq_groups(qq_groups: list) -> str:
    if not isinstance(qq_groups, list) or not qq_groups:
        return LICENSE_HINT_NO_QQ_GROUPS

    lines: list[str] = []
    for item in qq_groups:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if name and url:
            lines.append(f'{name}：{url}')
        elif name:
            lines.append(name)
        elif url:
            lines.append(url)

    return "\n".join(lines) if lines else LICENSE_HINT_NO_QQ_GROUPS


class LicenseDialog(StyledDialogBase):
    def __init__(
        self,
        parent: QWidget | None,
        fingerprint_display: str,
        qq_groups: list | None = None,
    ) -> None:
        super().__init__(parent, LICENSE_DIALOG_TITLE, min_width=380, max_width=520)

        hint_text = LICENSE_DIALOG_HINT_FMT.format(code=fingerprint_display)
        hint_text += "\n" + _format_qq_groups(qq_groups or [])

        body = QLabel(hint_text)
        body.setObjectName("BodyLabel")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.shell_layout.addWidget(body, stretch=1)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(LICENSE_DIALOG_PLACEHOLDER)
        self.input_field.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #3a3f4b; border-radius: 4px; "
            "background: #1e1e2e; color: #cdd6f4; font-size: 13px; }"
        )
        self.shell_layout.addWidget(self.input_field)

        self.activation_code: str | None = None

        confirm_btn, cancel_btn = self.add_action_row(
            confirm_text=LICENSE_DIALOG_CONFIRM,
            cancel_text=LICENSE_DIALOG_CANCEL,
            on_confirm=self._on_confirm,
            on_cancel=self._on_cancel,
        )

        self.adjustSize()

    def _on_confirm(self) -> None:
        code = self.input_field.text().strip()
        if code:
            self.activation_code = code
            self.accept()

    def _on_cancel(self) -> None:
        self.activation_code = None
        self.reject()

    @staticmethod
    def get_activation_code(
        parent: QWidget | None,
        fingerprint_display: str,
        qq_groups: list | None = None,
    ) -> str | None:
        dialog = LicenseDialog(parent, fingerprint_display, qq_groups)
        if parent is not None:
            center_dialog(dialog, parent)
        result = dialog.exec()
        if result:
            return dialog.activation_code
        return None

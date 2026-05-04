"""Persistence helper for window geometry and size preferences."""

from __future__ import annotations

from .settings_gateway import SettingsGateway


class WindowPrefsStore:
    def __init__(self, gateway: SettingsGateway) -> None:
        self._gateway = gateway

    def load_window_geometry(self):
        return self._gateway.parse_window_geometry(self._gateway.get_window_geometry())

    def load_sidebar_collapsed(self):
        return self._gateway.get_sidebar_collapsed()

    def load_sidebar_width(self):
        return self._gateway.get_sidebar_width()

    def load_paused_sidebar_width(self):
        return self._gateway.get_paused_sidebar_width()

    def load_locked_view_size(self):
        return self._gateway.get_locked_view_size()

    def load_paused_view_size(self):
        return self._gateway.get_paused_view_size()

    def load_route_section_expanded(self):
        return self._gateway.get_route_section_expanded()

    def load_annotation_type_ids(self) -> list[str]:
        return self._gateway.get_annotation_type_ids()

    def load_annotation_presets(self) -> list[dict]:
        return self._gateway.get_annotation_presets()

    def load_annotation_group_expanded(self) -> dict[str, bool]:
        return self._gateway.get_annotation_group_expanded()

    def load_annotation_panel_follow_window(self) -> bool:
        return self._gateway.get_annotation_panel_follow_window()

    def load_annotation_panel_offset(self, maximized: bool = False):
        if maximized:
            return self._gateway.get_annotation_panel_maximized_offset()
        return self._gateway.get_annotation_panel_offset()

    def load_annotation_panel_position(self, maximized: bool = False):
        if maximized:
            return self._gateway.get_annotation_panel_maximized_position()
        return self._gateway.get_annotation_panel_position()

    def save_annotation_preferences(self, type_ids: list[str]) -> None:
        self._gateway.save(
            {
                "ANNOTATION_TYPE_IDS": type_ids,
            }
        )

    def save_annotation_presets(self, presets: list[dict]) -> None:
        self._gateway.save({"ANNOTATION_PRESETS": presets})

    def save_annotation_group_expanded(self, expanded: dict[str, bool]) -> None:
        self._gateway.save({"ANNOTATION_GROUP_EXPANDED": expanded})

    def save_annotation_panel_offset(self, offset: dict, maximized: bool = False) -> None:
        key = "ANNOTATION_PANEL_MAXIMIZED_OFFSET" if maximized else "ANNOTATION_PANEL_OFFSET"
        self._gateway.save({key: offset})

    def save_annotation_panel_position(self, position: dict, maximized: bool = False) -> None:
        key = "ANNOTATION_PANEL_MAXIMIZED_POSITION" if maximized else "ANNOTATION_PANEL_POSITION"
        self._gateway.save({key: position})

    def save_route_section_expanded(self, expanded: dict[str, bool]) -> None:
        self._gateway.save({"ROUTE_SECTION_EXPANDED": expanded})

    def save_payload(self, payload: dict) -> None:
        self._gateway.save(payload)

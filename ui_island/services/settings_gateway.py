"""Centralized access to config-backed settings."""

from __future__ import annotations

import config

from .annotation_preferences import normalize_type_ids


class SettingsGateway:
    def save(self, values: dict) -> None:
        config.save_config(values)

    def get_minimap(self):
        return config.MINIMAP

    def get_window_geometry(self):
        return config.WINDOW_GEOMETRY

    def parse_window_geometry(self, raw):
        return config.parse_window_geometry(raw)

    def get_sidebar_collapsed(self):
        return config.SIDEBAR_COLLAPSED

    def get_sidebar_width(self):
        return config.SIDEBAR_WIDTH

    def get_paused_sidebar_width(self):
        return getattr(config, "PAUSED_SIDEBAR_WIDTH", None)

    def get_locked_view_size(self):
        return config.LOCKED_VIEW_SIZE

    def get_paused_view_size(self):
        return getattr(config, "PAUSED_VIEW_SIZE", None)

    def get_toggle_lock_hotkey(self):
        return getattr(config, "TOGGLE_LOCK_HOTKEY", None)

    @staticmethod
    def _opacity(name: str, default: float) -> float:
        try:
            value = float(getattr(config, name, default))
        except (TypeError, ValueError):
            value = default
        return max(0.0, min(1.0, value))

    def get_window_locked_opacity(self) -> float:
        return self._opacity("WINDOW_LOCKED_OPACITY", 0.78)

    def get_window_normal_opacity(self) -> float:
        return self._opacity("WINDOW_NORMAL_OPACITY", 1.0)

    def get_route_section_expanded(self) -> dict[str, bool]:
        raw = getattr(config, "ROUTE_SECTION_EXPANDED", None)
        if not isinstance(raw, dict):
            return {}
        return {str(name): bool(expanded) for name, expanded in raw.items()}

    def get_annotation_type_ids(self) -> list[str]:
        return normalize_type_ids(getattr(config, "ANNOTATION_TYPE_IDS", []))

    def get_annotation_group_expanded(self) -> dict[str, bool]:
        raw = getattr(config, "ANNOTATION_GROUP_EXPANDED", None)
        if not isinstance(raw, dict):
            return {}
        return {str(name): bool(expanded) for name, expanded in raw.items()}

    def get_tracker_refresh_rate(self, tracker) -> int:
        return int(config.SIFT_REFRESH_RATE)

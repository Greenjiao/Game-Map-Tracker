"""Compatibility property bridge for island window state containers."""

from __future__ import annotations


class WindowStateBridgeMixin:
    @property
    def _mode_before_max(self):
        return self.window_mode_state.mode_before_max

    @_mode_before_max.setter
    def _mode_before_max(self, value) -> None:
        self.window_mode_state.mode_before_max = value

    @property
    def _applying_mode(self) -> bool:
        return self.window_mode_state.applying_mode

    @_applying_mode.setter
    def _applying_mode(self, value: bool) -> None:
        self.window_mode_state.applying_mode = value

    @property
    def _preferred_right_edge(self) -> int | None:
        return self.window_mode_state.preferred_right_edge

    @_preferred_right_edge.setter
    def _preferred_right_edge(self, value: int | None) -> None:
        self.window_mode_state.preferred_right_edge = value

    @property
    def _sidebar_collapsed(self) -> bool:
        return self.window_layout_prefs.sidebar_collapsed

    @_sidebar_collapsed.setter
    def _sidebar_collapsed(self, value: bool) -> None:
        self.window_layout_prefs.sidebar_collapsed = value

    @property
    def _sidebar_width(self) -> int:
        return self.window_layout_prefs.sidebar_width

    @_sidebar_width.setter
    def _sidebar_width(self, value: int) -> None:
        self.window_layout_prefs.sidebar_width = value

    @property
    def _paused_sidebar_width(self) -> int:
        return self.window_layout_prefs.paused_sidebar_width

    @_paused_sidebar_width.setter
    def _paused_sidebar_width(self, value: int) -> None:
        self.window_layout_prefs.paused_sidebar_width = value

    @property
    def _normal_minimum_width(self) -> int:
        return self.window_layout_prefs.normal_minimum_width

    @_normal_minimum_width.setter
    def _normal_minimum_width(self, value: int) -> None:
        self.window_layout_prefs.normal_minimum_width = value

    @property
    def _normal_minimum_height(self) -> int:
        return self.window_layout_prefs.normal_minimum_height

    @_normal_minimum_height.setter
    def _normal_minimum_height(self, value: int) -> None:
        self.window_layout_prefs.normal_minimum_height = value

    @property
    def _compact_minimum_height(self) -> int:
        return self.window_layout_prefs.compact_minimum_height

    @_compact_minimum_height.setter
    def _compact_minimum_height(self, value: int) -> None:
        self.window_layout_prefs.compact_minimum_height = value

    @property
    def _pure_navigation_minimum_height(self) -> int:
        return self.window_layout_prefs.pure_navigation_minimum_height

    @_pure_navigation_minimum_height.setter
    def _pure_navigation_minimum_height(self, value: int) -> None:
        self.window_layout_prefs.pure_navigation_minimum_height = value

    @property
    def _sidebar_collapsed_before_pause(self):
        return self.window_layout_prefs.sidebar_collapsed_before_pause

    @_sidebar_collapsed_before_pause.setter
    def _sidebar_collapsed_before_pause(self, value) -> None:
        self.window_layout_prefs.sidebar_collapsed_before_pause = value

    @property
    def _sidebar_width_before_pause(self):
        return self.window_layout_prefs.sidebar_width_before_pause

    @_sidebar_width_before_pause.setter
    def _sidebar_width_before_pause(self, value) -> None:
        self.window_layout_prefs.sidebar_width_before_pause = value

    @property
    def _sidebar_collapsed_before_max(self):
        return self.window_layout_prefs.sidebar_collapsed_before_max

    @_sidebar_collapsed_before_max.setter
    def _sidebar_collapsed_before_max(self, value) -> None:
        self.window_layout_prefs.sidebar_collapsed_before_max = value

    @property
    def _sidebar_width_before_max(self):
        return self.window_layout_prefs.sidebar_width_before_max

    @_sidebar_width_before_max.setter
    def _sidebar_width_before_max(self, value) -> None:
        self.window_layout_prefs.sidebar_width_before_max = value

    @property
    def _sidebar_expand_restore_geometry(self):
        return self.window_layout_prefs.sidebar_expand_restore_geometry

    @_sidebar_expand_restore_geometry.setter
    def _sidebar_expand_restore_geometry(self, value) -> None:
        self.window_layout_prefs.sidebar_expand_restore_geometry = value

    @property
    def _geometry_before_max(self):
        return self.window_layout_prefs.geometry_before_max

    @_geometry_before_max.setter
    def _geometry_before_max(self, value) -> None:
        self.window_layout_prefs.geometry_before_max = value

    @property
    def _size_prefs(self):
        return self.window_layout_prefs.size_prefs

    @_size_prefs.setter
    def _size_prefs(self, value) -> None:
        self.window_layout_prefs.size_prefs = value

    @property
    def _route_checkboxes(self):
        return self.route_panel_state.route_checkboxes

    @_route_checkboxes.setter
    def _route_checkboxes(self, value) -> None:
        self.route_panel_state.route_checkboxes = value

    @property
    def _route_widgets_by_category(self):
        return self.route_panel_state.route_widgets_by_category

    @_route_widgets_by_category.setter
    def _route_widgets_by_category(self, value) -> None:
        self.route_panel_state.route_widgets_by_category = value

    @property
    def _route_sections(self):
        return self.route_panel_state.route_sections

    @_route_sections.setter
    def _route_sections(self, value) -> None:
        self.route_panel_state.route_sections = value

    @property
    def _route_section_expanded(self):
        return self.route_panel_state.route_section_expanded

    @_route_section_expanded.setter
    def _route_section_expanded(self, value) -> None:
        self.route_panel_state.route_section_expanded = value

    @property
    def _active_route_rename_item(self):
        return self.route_panel_state.active_route_rename_item

    @_active_route_rename_item.setter
    def _active_route_rename_item(self, value) -> None:
        self.route_panel_state.active_route_rename_item = value

    @property
    def _adding_category(self) -> bool:
        return self.route_panel_state.adding_category

    @_adding_category.setter
    def _adding_category(self, value: bool) -> None:
        self.route_panel_state.adding_category = value

    @property
    def _add_category_row(self):
        return self.route_panel_state.add_category_row

    @_add_category_row.setter
    def _add_category_row(self, value) -> None:
        self.route_panel_state.add_category_row = value

    @property
    def _add_category_input(self):
        return self.route_panel_state.add_category_input

    @_add_category_input.setter
    def _add_category_input(self, value) -> None:
        self.route_panel_state.add_category_input = value

    @property
    def _add_category_confirm_btn(self):
        return self.route_panel_state.add_category_confirm_btn

    @_add_category_confirm_btn.setter
    def _add_category_confirm_btn(self, value) -> None:
        self.route_panel_state.add_category_confirm_btn = value

    @property
    def _add_category_cancel_btn(self):
        return self.route_panel_state.add_category_cancel_btn

    @_add_category_cancel_btn.setter
    def _add_category_cancel_btn(self, value) -> None:
        self.route_panel_state.add_category_cancel_btn = value

    @property
    def _locked(self) -> bool:
        return self.tracking_state.locked

    @_locked.setter
    def _locked(self, value: bool) -> None:
        self.tracking_state.locked = value

    @property
    def _running(self) -> bool:
        return self.tracking_state.running

    @_running.setter
    def _running(self, value: bool) -> None:
        self.tracking_state.running = value

    @property
    def _latencies(self):
        return self.tracking_state.latencies

    @_latencies.setter
    def _latencies(self, value) -> None:
        self.tracking_state.latencies = value

    @property
    def _last_result(self):
        return self.tracking_state.last_result

    @_last_result.setter
    def _last_result(self, value) -> None:
        self.tracking_state.last_result = value

    @property
    def _last_player_xy(self):
        return self.tracking_state.last_player_xy

    @_last_player_xy.setter
    def _last_player_xy(self, value) -> None:
        self.tracking_state.last_player_xy = value

    @property
    def _latest_minimap(self):
        return self.tracking_state.latest_minimap

    @_latest_minimap.setter
    def _latest_minimap(self, value) -> None:
        self.tracking_state.latest_minimap = value

    @property
    def _tracking_attempts_paused(self) -> bool:
        return self.tracking_state.tracking_attempts_paused

    @_tracking_attempts_paused.setter
    def _tracking_attempts_paused(self, value: bool) -> None:
        self.tracking_state.tracking_attempts_paused = value

    @property
    def _tracking_paused_state(self):
        return self.tracking_state.tracking_paused_state

    @_tracking_paused_state.setter
    def _tracking_paused_state(self, value) -> None:
        self.tracking_state.tracking_paused_state = value

    @property
    def _jump_anomaly_count(self) -> int:
        return self.tracking_state.jump_anomaly_count

    @_jump_anomaly_count.setter
    def _jump_anomaly_count(self, value: int) -> None:
        self.tracking_state.jump_anomaly_count = value

    @property
    def _preferred_locked(self) -> bool:
        return self.tracking_state.preferred_locked

    @_preferred_locked.setter
    def _preferred_locked(self, value: bool) -> None:
        self.tracking_state.preferred_locked = value

    @property
    def _lock_state_before_lost(self):
        return self.tracking_state.lock_state_before_lost

    @_lock_state_before_lost.setter
    def _lock_state_before_lost(self, value) -> None:
        self.tracking_state.lock_state_before_lost = value

    @property
    def _restore_lock_after_relocate(self):
        return self.tracking_state.restore_lock_after_relocate

    @_restore_lock_after_relocate.setter
    def _restore_lock_after_relocate(self, value) -> None:
        self.tracking_state.restore_lock_after_relocate = value

    @property
    def _tracking_bootstrap_pending(self) -> bool:
        return self.tracking_state.tracking_bootstrap_pending

    @_tracking_bootstrap_pending.setter
    def _tracking_bootstrap_pending(self, value: bool) -> None:
        self.tracking_state.tracking_bootstrap_pending = value

    @property
    def _hotkey_listener(self):
        return self.hotkey_state.listener

    @_hotkey_listener.setter
    def _hotkey_listener(self, value) -> None:
        self.hotkey_state.listener = value

    @property
    def _hotkey_thread(self):
        return self.hotkey_state.thread

    @_hotkey_thread.setter
    def _hotkey_thread(self, value) -> None:
        self.hotkey_state.thread = value

    @property
    def _hotkey_thread_id(self):
        return self.hotkey_state.thread_id

    @_hotkey_thread_id.setter
    def _hotkey_thread_id(self, value) -> None:
        self.hotkey_state.thread_id = value

    @property
    def _last_hotkey_at(self) -> float:
        return self.hotkey_state.last_hotkey_at

    @_last_hotkey_at.setter
    def _last_hotkey_at(self, value: float) -> None:
        self.hotkey_state.last_hotkey_at = value

    @property
    def _alt_pressed(self) -> bool:
        return self.hotkey_state.alt_pressed

    @_alt_pressed.setter
    def _alt_pressed(self, value: bool) -> None:
        self.hotkey_state.alt_pressed = value

    @property
    def _hotkeys_suspended(self) -> bool:
        return self.hotkey_state.suspended

    @_hotkeys_suspended.setter
    def _hotkeys_suspended(self, value: bool) -> None:
        self.hotkey_state.suspended = bool(value)

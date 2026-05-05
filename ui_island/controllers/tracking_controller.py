"""Tracking loop and tracking-state UI helpers."""

from __future__ import annotations

import time

import mss
import numpy as np

from ui_island.state.tracking import TrackResult, TrackState


class TrackingController:
    def __init__(self, window) -> None:
        self.window = window

    def _stable_family(self):
        mode_enum = self.window._mode.__class__
        return (mode_enum.TRACKING_STABLE, mode_enum.TRACKING_INERTIAL)

    def tracker_state_to_mode(self, state: TrackState):
        mode_enum = self.window._mode.__class__
        if state == TrackState.LOCKED:
            return mode_enum.TRACKING_STABLE
        if state == TrackState.INERTIAL:
            return mode_enum.TRACKING_INERTIAL
        return mode_enum.TRACKING_LOST

    def current_refresh_ms(self) -> int:
        return self.window.settings_gateway.get_tracker_refresh_rate(self.window.tracker)

    def paused_track_result(self) -> TrackResult:
        x = y = None
        if self.window._tracking_paused_state == TrackState.INERTIAL and self.window._last_player_xy is not None:
            x, y = self.window._last_player_xy
        return TrackResult(self.window._tracking_paused_state, x=x, y=y, latency_ms=0.0)

    def clear_tracker_anchor(self) -> None:
        for attr in ("_last_x", "_last_y"):
            if hasattr(self.window.tracker, attr):
                setattr(self.window.tracker, attr, None)
        if hasattr(self.window.tracker, "_lost_frames"):
            setattr(self.window.tracker, "_lost_frames", 0)

    def enter_lost_mode(self) -> None:
        mode_enum = self.window._mode.__class__
        stable_family = self._stable_family()
        if self.window._mode == mode_enum.TRACKING_LOST:
            return
        if self.window._mode in stable_family:
            self.window._lock_state_before_lost = self.window._preferred_locked
        self.window.window_mode_controller.enter_mode(mode_enum.TRACKING_LOST)
        self.window._update_lock_button_visibility()

    def exit_lost_mode(self, clear_saved_lock_state: bool = True) -> None:
        mode_enum = self.window._mode.__class__
        if self.window._mode != mode_enum.TRACKING_LOST:
            return
        if clear_saved_lock_state:
            self.window._lock_state_before_lost = None
        self.window._update_lock_button_visibility()

    def restore_lock_state_after_lost(self) -> None:
        desired_locked = self.window._preferred_locked
        self.exit_lost_mode(clear_saved_lock_state=False)
        self.window._lock_state_before_lost = None
        if self.window._locked != desired_locked:
            self.window._set_locked_state(desired_locked)
        self.window._update_lock_button_visibility()

    def resume_tracking_attempts(self) -> None:
        self.window._tracking_attempts_paused = False
        self.window._tracking_paused_state = TrackState.SEARCHING
        self.window._jump_anomaly_count = 0
        self.window.window_mode_controller.apply_sidebar_state()
        self.window._update_lock_button_visibility()

    def start_navigation(self) -> None:
        if not self.window.route_panel_controller.confirm_exit_route_drawing():
            return
        mode_enum = self.window._mode.__class__
        self.window._mode_before_max = None
        self.window._lock_state_before_lost = None
        self.window._tracking_bootstrap_pending = True
        self.window.window_mode_controller.sync_normal_minimum_height()
        self.window.setMinimumHeight(self.window._normal_minimum_height)
        self.resume_tracking_attempts()
        self.window.window_mode_controller.enter_mode(mode_enum.TRACKING_STABLE)
        self.window._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def pause_navigation(self) -> None:
        mode_enum = self.window._mode.__class__
        self.window._mode_before_max = None
        self.window._restore_lock_after_relocate = None
        self.window._lock_state_before_lost = None
        self.window._tracking_paused_state = TrackState.SEARCHING
        self.window._tracking_bootstrap_pending = False
        self.window.window_mode_controller.enter_mode(mode_enum.PAUSED)
        self.window._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))

    def set_alert_mode(self, enabled: bool, message: str = "", allow_terminate: bool = False) -> None:
        if enabled:
            if message:
                self.window.alert_message.setText(message)
            self.window.alert_terminate_btn.setVisible(allow_terminate)
            self.window.window_mode_controller.apply_compact_constraints(True)
            self.window.state_hint_label.setVisible(False)
        else:
            self.window.window_mode_controller.apply_compact_constraints(False)
            self.window.alert_terminate_btn.setVisible(False)
            self.window.state_hint_label.setVisible(True)
            pure_active = getattr(self.window, "_is_pure_navigation_active", None)
            if callable(pure_active) and pure_active():
                apply_pure_navigation_ui = getattr(self.window, "_apply_pure_navigation_ui", None)
                if callable(apply_pure_navigation_ui):
                    apply_pure_navigation_ui()
                sync_pure_height = getattr(self.window.window_mode_controller, "sync_pure_navigation_minimum_height", None)
                if callable(sync_pure_height):
                    sync_pure_height()
                    self.window.setMinimumHeight(self.window._pure_navigation_minimum_height)

    def set_header_action_visibility(self, visible: bool) -> None:
        pure_active = getattr(self.window, "_is_pure_navigation_active", None)
        if callable(pure_active) and pure_active():
            self.window.relocate_btn.setVisible(False)
            self.window.reset_view_btn.setVisible(False)
            self.window.sidebar_toggle_btn.setVisible(False)
            return
        mode_enum = self.window._mode.__class__
        is_paused = self.window._mode in (mode_enum.PAUSED, mode_enum.MAXIMIZED)
        is_lost = self.window._mode == mode_enum.TRACKING_LOST
        self.window.relocate_btn.setVisible(visible or is_paused or is_lost)
        self.window.reset_view_btn.setVisible((visible or is_paused) and not is_lost)
        self.window.sidebar_toggle_btn.setVisible(visible and not is_paused and not is_lost)

    def apply_state_feedback(self, state: TrackState) -> None:
        mode_enum = self.window._mode.__class__
        stable_family = self._stable_family()
        if state != TrackState.SEARCHING:
            self.window._tracking_bootstrap_pending = False

        if self.window._mode in (mode_enum.PAUSED, mode_enum.MAXIMIZED):
            self.window._lock_state_before_lost = None
            self.window._update_lock_button_visibility()
            self.set_alert_mode(False)
            drawing = getattr(self.window, "route_drawing_state", None)
            if drawing is not None and drawing.active:
                self.window.state_hint_label.setVisible(True)
                self.window.state_hint_label.setText(f"纯净绘制中：{drawing.name}")
                self.window.state_hint_label.setStyleSheet("")
                return
            if self.window._mode == mode_enum.PAUSED:
                self.window.state_hint_label.setText("暂停定位")
                self.window.state_hint_label.setStyleSheet("")
            return

        if state == TrackState.SEARCHING:
            if self.window._mode == mode_enum.TRACKING_LOST:
                target_mode = mode_enum.TRACKING_LOST
            elif self.window._mode in stable_family:
                target_mode = self.window._mode
            else:
                target_mode = mode_enum.TRACKING_STABLE
        else:
            target_mode = self.tracker_state_to_mode(state)

        if target_mode != self.window._mode:
            if target_mode in stable_family and self.window._mode == mode_enum.TRACKING_LOST:
                self.restore_lock_state_after_lost()
            if target_mode == mode_enum.TRACKING_LOST:
                self.enter_lost_mode()
            else:
                self.window.window_mode_controller.enter_mode(target_mode)

        if state == TrackState.LOCKED:
            self.set_alert_mode(False)
            self.window.state_hint_label.setVisible(True)
            self.window.state_hint_label.setText("定位稳定")
            self.window.state_hint_label.setStyleSheet("")
        elif state == TrackState.INERTIAL:
            self.set_alert_mode(False)
            self.window.state_hint_label.setVisible(True)
            self.window.state_hint_label.setText("定位暂时不稳定，沿用上一帧位置。")
            self.window.state_hint_label.setStyleSheet("")
        elif state == TrackState.SEARCHING:
            self.window._jump_anomaly_count = 0
            if self.window._mode == mode_enum.TRACKING_LOST:
                self.set_alert_mode(True, "正在搜索目标，请稍候…", allow_terminate=True)
            else:
                self.set_alert_mode(False)
                self.window.state_hint_label.setVisible(True)
                self.window.state_hint_label.setText("正在搜索目标，请稍候…")
                self.window.state_hint_label.setStyleSheet("")
        else:
            self.set_alert_mode(True, "目标丢失，正在持续尝试重新定位。", allow_terminate=True)

    def tracker_loop(self) -> None:
        while self.window._running:
            if not getattr(self.window.tracker, "map_available", True):
                self.window._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))
                time.sleep(self.current_refresh_ms() / 1000.0)
                continue

            if self.window.isMaximized():
                self.window._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))
                time.sleep(self.current_refresh_ms() / 1000.0)
                continue

            if self.window._tracking_attempts_paused:
                self.window._frame_ready.emit(self.paused_track_result())
                time.sleep(self.current_refresh_ms() / 1000.0)
                continue

            with mss.mss() as sct:
                while self.window._running and not self.window.isMaximized() and not self.window._tracking_attempts_paused:
                    refresh_ms = self.current_refresh_ms()
                    started_at = time.time()
                    try:
                        shot = sct.grab(self.window._minimap_region)
                        minimap_bgr = np.array(shot)[:, :, :3]
                    except Exception:
                        time.sleep(0.1)
                        continue

                    self.window._latest_minimap = minimap_bgr
                    result = self.window.tracker.step(minimap_bgr)
                    self.window._frame_ready.emit(result)

                    elapsed_ms = (time.time() - started_at) * 1000.0
                    wait_seconds = max(0.0, (refresh_ms - elapsed_ms) / 1000.0)
                    time.sleep(wait_seconds)

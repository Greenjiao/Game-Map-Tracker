"""Top-of-screen island overlay with interactive map and route tools."""

from __future__ import annotations

import sys
import threading
import traceback
from collections import deque
from enum import Enum

import config
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

from base import BaseTracker, TrackResult, TrackState
from route_manager import RouteManager

from ..design import button_specs, qss, strings, theme
from ..dialogs import toast, toast_persistent
from ..dialogs.settings_dialog import (
    format_app_update_message,
    format_update_progress_message,
    styled_confirm,
    styled_info,
)
from ..services import SettingsGateway, WindowPrefsStore
from ..services.app_updater import (
    APP_STATUS_DISABLED,
    APP_STATUS_NOTICE,
    AppUpdateCheckResult,
    AppUpdateInstallResult,
    DEFAULT_APP_STATUS_MESSAGE,
    app_notice_ack_key,
    check_app_update,
    cleanup_staging,
    download_changed_files,
    install_non_restart_update,
    should_show_app_notice,
    should_show_startup_update_prompt,
    start_restart_update,
)
from ..services.annotation_preferences import normalize_type_ids
from ..services.hotkey_config import hotkey_label, qt_event_matches_hotkey
from ..state import HotkeyState, RouteDrawingState, RoutePanelState, TrackingState, WindowLayoutPrefs, WindowModeState
from ..widgets import RestoreIcon
from ..platform.win_overlay import apply_overlay_flags, set_click_through
from ..controllers import HotkeyController, InteractionController, MapInteractionController, RoutePanelController, TrackingController, WindowModeController
from .window_state_bridge import WindowStateBridgeMixin
from .window_view import build_window_ui


class WindowMode(Enum):
    PAUSED = "paused"
    TRACKING_STABLE = "tracking_stable"
    TRACKING_INERTIAL = "tracking_inertial"
    TRACKING_LOST = "tracking_lost"
    MAXIMIZED = "maximized"


_STABLE_FAMILY = {WindowMode.TRACKING_STABLE, WindowMode.TRACKING_INERTIAL}


class IslandWindow(WindowStateBridgeMixin, QWidget):
    _frame_ready = Signal(object)
    _toggle_lock_requested = Signal()
    _annotation_refresh_finished = Signal(int, str)
    _startup_update_check_finished = Signal(object)
    _startup_update_install_finished = Signal(object)
    _startup_update_progress_changed = Signal(str)

    _NATIVE_HOTKEY_ID_ALT_GRAVE = 1
    _HOTKEY_DEBOUNCE_SEC = 0.35
    _AUTO_RECENTER_MOVE_THRESHOLD = 3
    _RESIZE_MARGIN = 6
    _SIDEBAR_RESIZE_MARGIN = 6
    _SIDEBAR_MIN_WIDTH = 200
    _HEADER_ICON_SWITCH_WIDTH = 600

    def __init__(self, tracker: BaseTracker, route_mgr: RouteManager) -> None:
        super().__init__(None)
        qss.ensure_tooltip_style()
        self.tracker = tracker
        self.route_mgr = route_mgr
        self.settings_gateway = SettingsGateway()
        self.window_prefs_store = WindowPrefsStore(self.settings_gateway)
        self.window_mode_state = WindowModeState()
        self.window_layout_prefs = WindowLayoutPrefs()
        self.route_panel_state = RoutePanelState()
        self.route_drawing_state = RouteDrawingState()
        self.tracking_state = TrackingState()
        self.hotkey_state = HotkeyState()
        self.route_panel_controller = RoutePanelController(self)
        self.window_mode_controller = WindowModeController(self)
        self.tracking_controller = TrackingController(self)
        self.interaction_controller = InteractionController(self)
        self.map_interaction_controller = MapInteractionController(self)
        self.hotkey_controller = HotkeyController(self)

        self.tracking_state.locked = False
        self.tracking_state.running = True
        self.tracking_state.latencies = deque(maxlen=30)
        self.tracking_state.last_result = None
        self.tracking_state.last_player_xy = None
        self.tracking_state.latest_minimap = None

        self._is_windows = sys.platform.startswith("win")
        self._window_margin = 0 if self._is_windows else 10
        self._shadow_enabled = not self._is_windows

        self.route_panel_state.route_checkboxes = {}
        self._tracked_route_progress_signature: tuple[tuple[str, bool], ...] = ()
        self.route_panel_state.route_widgets_by_category = {}
        self.route_panel_state.route_sections = {}
        self.route_panel_state.route_section_expanded = self.window_prefs_store.load_route_section_expanded()
        self.route_panel_state.active_route_rename_item = None
        self.route_panel_state.adding_category = False
        self.route_panel_state.add_category_row = None
        self.route_panel_state.add_category_input = None
        self.route_panel_state.add_category_confirm_btn = None
        self.route_panel_state.add_category_cancel_btn = None
        self.annotation_type_ids = self.window_prefs_store.load_annotation_type_ids()
        self.annotation_group_expanded = self.window_prefs_store.load_annotation_group_expanded()
        self.route_mgr.set_annotation_type_ids(self.annotation_type_ids)

        saved_collapsed = self.window_prefs_store.load_sidebar_collapsed()
        saved_sidebar_w = self.window_prefs_store.load_sidebar_width()
        self.window_layout_prefs.sidebar_collapsed = bool(saved_collapsed) if saved_collapsed is not None else False
        try:
            tracking_sidebar_width = max(120, int(saved_sidebar_w)) if saved_sidebar_w is not None else 320
        except (TypeError, ValueError):
            tracking_sidebar_width = 320
        saved_paused_sidebar_w = self.window_prefs_store.load_paused_sidebar_width()
        try:
            self.window_layout_prefs.paused_sidebar_width = (
                max(120, int(saved_paused_sidebar_w))
                if saved_paused_sidebar_w is not None
                else tracking_sidebar_width
            )
        except (TypeError, ValueError):
            self.window_layout_prefs.paused_sidebar_width = tracking_sidebar_width
        self.window_layout_prefs.sidebar_width = self.window_layout_prefs.paused_sidebar_width

        self.window_layout_prefs.normal_minimum_width = theme.WINDOW_MIN_W + self._window_margin * 2
        self.window_layout_prefs.normal_minimum_height = max(
            theme.WINDOW_MIN_H,
            theme.TRACKING_WINDOW_MIN_H,
        ) + self._window_margin * 2
        self.tracking_state.tracking_attempts_paused = False
        self.tracking_state.tracking_paused_state = TrackState.SEARCHING
        self.tracking_state.jump_anomaly_count = 0
        self.tracking_state.preferred_locked = False
        self.tracking_state.lock_state_before_lost = None
        self.tracking_state.restore_lock_after_relocate = None
        self.tracking_state.tracking_bootstrap_pending = False

        self._mode = WindowMode.PAUSED
        self.window_mode_state.mode_before_max = None
        self.window_layout_prefs.geometry_before_max = None
        self.window_mode_state.applying_mode = False
        self.window_mode_state.preferred_right_edge = None
        self.window_layout_prefs.sidebar_collapsed_before_pause = bool(self._sidebar_collapsed)
        self.window_layout_prefs.sidebar_width_before_pause = tracking_sidebar_width
        self.window_layout_prefs.sidebar_collapsed_before_max = None
        self.window_layout_prefs.sidebar_width_before_max = None
        self.window_layout_prefs.sidebar_expand_restore_geometry = None
        paused_w = theme.EXPANDED_W + self._window_margin * 2
        paused_h = theme.EXPANDED_H + self._window_margin * 2
        self.window_layout_prefs.size_prefs = {
            WindowMode.PAUSED: (paused_w, paused_h),
        }

        saved_stable = self.window_prefs_store.load_locked_view_size()
        if isinstance(saved_stable, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_stable["width"]))
                h = max(self._normal_minimum_height, int(saved_stable["height"]))
                self.window_layout_prefs.size_prefs[WindowMode.TRACKING_STABLE] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass
        saved_paused = self.window_prefs_store.load_paused_view_size()
        if isinstance(saved_paused, dict):
            try:
                w = max(self._normal_minimum_width, int(saved_paused["width"]))
                h = max(self._normal_minimum_height, int(saved_paused["height"]))
                self.window_layout_prefs.size_prefs[WindowMode.PAUSED] = (w, h)
            except (KeyError, TypeError, ValueError):
                pass

        self._stable_size_save_timer = QTimer(self)
        self._stable_size_save_timer.setSingleShot(True)
        self._stable_size_save_timer.setInterval(300)
        self._stable_size_save_timer.timeout.connect(self.window_mode_controller.flush_stable_size_to_config)
        self._paused_size_save_timer = QTimer(self)
        self._paused_size_save_timer.setSingleShot(True)
        self._paused_size_save_timer.setInterval(300)
        self._paused_size_save_timer.timeout.connect(self.window_mode_controller.flush_paused_size_to_config)

        self._move_dragging = False
        self._move_drag_offset = None
        self._edge_cursor_active = False
        self._system_resize_edges = Qt.Edges()
        self._sidebar_resizing = False
        self._sidebar_resize_start_x = 0
        self._sidebar_resize_start_width = self._sidebar_width
        self._header_buttons_icon_only = False
        self._mini_icon = None
        self._annotation_refresh_running = False
        self._annotation_refresh_toast = None
        self._startup_update_check_running = False
        self._startup_update_install_running = False
        self._startup_update_progress_toast = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)

        build_window_ui(self)
        self._refresh_hotkey_hint()
        self.window_mode_controller.sync_normal_minimum_height()
        self.window_mode_controller.sync_compact_minimum_height()
        self.setMinimumSize(self._normal_minimum_width, self._normal_minimum_height)
        self.interaction_controller.install_resize_filters(self.root)
        self.installEventFilter(self)
        self.window_mode_controller.restore_or_center()
        self.window_mode_controller.enter_mode(WindowMode.PAUSED)
        self._apply_configured_window_opacity()
        QTimer.singleShot(0, self._paint_default_map)

        self._toggle_lock_requested.connect(self.toggle_lock, Qt.QueuedConnection)
        self._annotation_refresh_finished.connect(self._on_annotation_refresh_finished, Qt.QueuedConnection)
        self._startup_update_check_finished.connect(self._on_startup_update_check_finished, Qt.QueuedConnection)
        self._startup_update_install_finished.connect(self._on_startup_update_install_finished, Qt.QueuedConnection)
        self._startup_update_progress_changed.connect(self._on_startup_update_progress_changed, Qt.QueuedConnection)
        self._frame_ready.connect(self._on_frame)
        self.map_view.add_point_requested.connect(self.map_interaction_controller.on_add_point_requested)
        self.map_view.add_annotation_requested.connect(self.map_interaction_controller.add_annotation_point)
        self.map_view.delete_point_requested.connect(self.map_interaction_controller.on_delete_point_requested)
        self.map_view.mark_point_visited_requested.connect(self.map_interaction_controller.mark_point_visited)
        self.map_view.change_point_annotation_requested.connect(self.map_interaction_controller.change_point_annotation)
        self.map_view.delete_point_annotation_requested.connect(self.map_interaction_controller.delete_point_annotation)
        self.map_view.change_point_node_type_requested.connect(self.map_interaction_controller.change_point_node_type)
        self.map_view.change_annotation_requested.connect(self.map_interaction_controller.change_map_annotation)
        self.map_view.add_annotation_to_route_requested.connect(self.map_interaction_controller.add_annotation_to_route)
        self.map_view.delete_annotation_requested.connect(self.map_interaction_controller.delete_map_annotation)
        self.map_view.guide_hint_changed.connect(self._on_route_guide_hint_changed)
        self.map_view.drawing_point_requested.connect(self.route_panel_controller.append_drawing_point)
        self.map_view.drawing_undo_requested.connect(self.route_panel_controller.undo_route_drawing)
        self.annotation_toggle_btn.clicked.connect(lambda _checked=False: self._toggle_annotation_panel())
        self.annotation_panel.set_group_expanded_state(
            self.annotation_group_expanded,
            self._on_annotation_group_expanded_changed,
        )
        self.annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
        self.annotation_panel.set_preferences(self.annotation_type_ids)
        self.annotation_panel.selection_changed.connect(self._on_annotation_selection_changed)
        self.annotation_panel.plan_route_requested.connect(self._on_annotation_plan_route_requested)
        self.annotation_panel.panel_hidden.connect(lambda: self.annotation_toggle_btn.setChecked(False))

        self._minimap_region = self.settings_gateway.get_minimap()
        self.hotkey_controller.start_listener()

        self._thread = threading.Thread(target=self.tracking_controller.tracker_loop, daemon=True)
        self._thread.start()
        QTimer.singleShot(2000, self._start_startup_update_check)

    def _start_startup_update_check(self) -> None:
        if self._startup_update_check_running:
            return
        self._startup_update_check_running = True

        def worker() -> None:
            result = check_app_update()
            try:
                self._startup_update_check_finished.emit(result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_startup_update_check_finished(self, result: object) -> None:
        self._startup_update_check_running = False
        if not isinstance(result, AppUpdateCheckResult):
            return
        if self._handle_startup_app_status(result):
            return
        last_prompted = str(getattr(config, "APP_UPDATE_LAST_PROMPTED_VERSION", "") or "")
        if not should_show_startup_update_prompt(result, last_prompted):
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
                self._start_startup_restart_update(result)
                return
            self._remember_startup_update_prompt(result.latest_version)
            return

        confirmed = styled_confirm(
            self,
            "发现资源更新",
            format_app_update_message(result).replace("<br>", "\n"),
            confirm_text="下载并更新",
            cancel_text="稍后",
        )
        if confirmed:
            self._start_startup_non_restart_update(result)
            return
        self._remember_startup_update_prompt(result.latest_version)

    def _handle_startup_app_status(self, result: AppUpdateCheckResult) -> bool:
        status = str(getattr(result, "app_status", "") or "").strip().lower()
        if status not in {APP_STATUS_NOTICE, APP_STATUS_DISABLED}:
            return False
        message = str(getattr(result, "app_status_message", "") or "").strip() or DEFAULT_APP_STATUS_MESSAGE
        if status == APP_STATUS_NOTICE:
            force_notice = bool(getattr(result, "app_notice_force_prompt", False))
            last_ack_key = str(getattr(config, "APP_NOTICE_LAST_ACK_KEY", "") or "")
            if not should_show_app_notice(
                status,
                message,
                force_prompt=force_notice,
                last_ack_key=last_ack_key,
            ):
                return False
            styled_info(self, "公告", message)
            self._remember_startup_notice_ack(message)
            return False
        if status == APP_STATUS_DISABLED:
            styled_info(self, "程序已停用", message)
            QApplication.quit()
            return True

    @staticmethod
    def _remember_startup_update_prompt(version: str) -> None:
        if not version:
            return
        try:
            config.save_config({"APP_UPDATE_LAST_PROMPTED_VERSION": version})
        except Exception:
            pass

    @staticmethod
    def _remember_startup_notice_ack(message: str) -> None:
        try:
            config.save_config({"APP_NOTICE_LAST_ACK_KEY": app_notice_ack_key(message)})
        except Exception:
            pass

    def _start_startup_non_restart_update(self, result: AppUpdateCheckResult) -> None:
        if self._startup_update_install_running:
            return
        self._startup_update_install_running = True
        self._show_startup_update_progress("正在准备更新...")

        def worker() -> None:
            staging = None
            try:
                progress = self._make_startup_update_progress_callback()
                staging = download_changed_files(result, progress_callback=progress)
                self._startup_update_progress_changed.emit("正在安装更新...")
                install_result = install_non_restart_update(result, staging)
            except Exception as exc:
                install_result = AppUpdateInstallResult(ok=False, version=result.latest_version, error=str(exc))
            finally:
                if staging is not None:
                    cleanup_staging(staging)
            try:
                self._startup_update_install_finished.emit(install_result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _start_startup_restart_update(self, result: AppUpdateCheckResult) -> None:
        if self._startup_update_install_running:
            return
        self._startup_update_install_running = True
        self._show_startup_update_progress("正在准备更新...")

        def worker() -> None:
            staging = None
            try:
                progress = self._make_startup_update_progress_callback()
                staging = download_changed_files(result, progress_callback=progress)
                self._startup_update_progress_changed.emit("正在启动更新器...")
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
                self._startup_update_install_finished.emit(install_result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_startup_update_progress(self, message: str) -> None:
        if self._startup_update_progress_toast is None:
            self._startup_update_progress_toast = toast_persistent(self, message)
            return
        try:
            self._startup_update_progress_toast.update_message(message)
        except RuntimeError:
            self._startup_update_progress_toast = toast_persistent(self, message)

    def _on_startup_update_progress_changed(self, message: str) -> None:
        self._show_startup_update_progress(str(message or "正在更新..."))

    def _clear_startup_update_progress(self) -> None:
        if self._startup_update_progress_toast is None:
            return
        try:
            self._startup_update_progress_toast.dismiss()
        except RuntimeError:
            pass
        self._startup_update_progress_toast = None

    def _make_startup_update_progress_callback(self):
        last_percent = {"value": -1}

        def callback(downloaded: int, total: int, path: str) -> None:
            if total > 0:
                percent = min(100, int(max(0, downloaded) * 100 / total))
                if percent == last_percent["value"]:
                    return
                last_percent["value"] = percent
            self._startup_update_progress_changed.emit(format_update_progress_message(downloaded, total, path))

        return callback

    def _on_startup_update_install_finished(self, result: object) -> None:
        self._startup_update_install_running = False
        self._clear_startup_update_progress()
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

    def _refresh_updated_resources(self) -> None:
        try:
            self.route_mgr._annotation_points_cache = None
            self.route_mgr._point_icon_cache.clear()
            self.route_mgr._annotation_icon_cache.clear()
        except Exception:
            pass
        try:
            self.route_panel_controller.reload_route_list()
        except Exception:
            pass
        try:
            self.annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
            self.annotation_panel.set_preferences(self.annotation_type_ids)
        except Exception:
            pass
        try:
            self.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def _handle_manual_map_navigation(self) -> None:
        self.map_view.set_center_locked(False)

    def _toggle_annotation_panel(self) -> None:
        if self.annotation_panel.isVisible():
            self.annotation_panel.hide()
            self.annotation_toggle_btn.setChecked(False)
            return
        self.annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
        self.annotation_panel.set_preferences(self.annotation_type_ids)
        self._position_annotation_panel()
        self.annotation_panel.show()
        self.annotation_toggle_btn.setChecked(True)

    def _position_annotation_panel(self) -> None:
        if self.isMaximized():
            self.annotation_panel.set_compact_hint(True)
            sidebar_pos = self.sidebar_shell.mapToGlobal(QPoint(0, 0))
            sidebar_width = max(0, self.sidebar_shell.width())
            inset = 8 if sidebar_width >= 336 else 0
            panel_width = max(320, sidebar_width - inset * 2)
            if sidebar_width > 0:
                panel_width = min(panel_width, sidebar_width - inset * 2 if inset else sidebar_width)
            self.annotation_panel.setFixedWidth(panel_width)
            self.annotation_panel.move(sidebar_pos.x() + inset, sidebar_pos.y() + 8)
            self.annotation_panel.raise_()
            return

        self.annotation_panel.set_compact_hint(False)
        global_pos = self.mapToGlobal(QPoint(0, self.height()))
        panel_width = max(320, min(720, self.width()))
        self.annotation_panel.setFixedWidth(panel_width)
        self.annotation_panel.move(global_pos.x(), global_pos.y())

    def _on_annotation_selection_changed(self, type_ids: list) -> None:
        self.annotation_type_ids = normalize_type_ids(type_ids)
        self.route_mgr.set_annotation_type_ids(self.annotation_type_ids)
        self.window_prefs_store.save_annotation_preferences(self.annotation_type_ids)
        try:
            self.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def _on_annotation_group_expanded_changed(self, expanded: dict[str, bool]) -> None:
        if expanded is not self.annotation_group_expanded:
            self.annotation_group_expanded = {str(name): bool(value) for name, value in expanded.items()}
            self.annotation_panel.sync_group_expanded_state(
                self.annotation_group_expanded,
                self._on_annotation_group_expanded_changed,
            )
        else:
            self.annotation_panel.sync_group_expanded_state(
                self.annotation_group_expanded,
                self._on_annotation_group_expanded_changed,
            )
        self.window_prefs_store.save_annotation_group_expanded(dict(self.annotation_group_expanded))

    def _on_annotation_plan_route_requested(self, type_id: str, type_name: str) -> None:
        try:
            result = self.route_mgr.create_optimized_annotation_route(type_id, type_name)
        except ValueError as exc:
            is_empty_points = "点位" in str(exc)
            styled_info(
                self,
                strings.ANNOTATION_PLAN_ROUTE_EMPTY_TITLE if is_empty_points else strings.ANNOTATION_PLAN_ROUTE_FAILED_TITLE,
                strings.ANNOTATION_PLAN_ROUTE_EMPTY_BODY.format(name=type_name or type_id)
                if is_empty_points
                else strings.ANNOTATION_PLAN_ROUTE_FAILED_BODY_FMT.format(name=type_name or type_id, error=exc),
            )
            return
        except Exception as exc:
            styled_info(
                self,
                strings.ANNOTATION_PLAN_ROUTE_FAILED_TITLE,
                strings.ANNOTATION_PLAN_ROUTE_FAILED_BODY_FMT.format(name=type_name or type_id, error=exc),
            )
            return

        self.route_panel_controller.reload_route_list()
        toast(self, strings.ANNOTATION_PLAN_ROUTE_SUCCESS_FMT.format(name=result["name"]))

    def _on_annotation_refresh_requested(self) -> None:
        if self._annotation_refresh_running:
            return
        confirmed = styled_confirm(
            self,
            strings.ANNOTATION_REFRESH_CONFIRM_TITLE,
            strings.ANNOTATION_REFRESH_CONFIRM_BODY,
            confirm_text=strings.ANNOTATION_REFRESH_CONFIRM,
            cancel_text=strings.DELETE_POINT_CANCEL,
        )
        if not confirmed:
            return

        self._annotation_refresh_running = True
        self._annotation_refresh_toast = toast_persistent(self, strings.ANNOTATION_REFRESH_RUNNING)

        def worker() -> None:
            code = 1
            error = ""
            try:
                from tools import fetch_17173_all_points, fetch_17173_icons

                icon_code = int(fetch_17173_icons.main(["--refresh"]))
                if icon_code != 0:
                    code = icon_code
                    error = "图标拉取失败"
                else:
                    code = int(fetch_17173_all_points.main(["--refresh"]))
                    if code != 0:
                        error = "点位拉取失败"
            except Exception:
                code = 1
                error = traceback.format_exc(limit=3)
            self._annotation_refresh_finished.emit(code, error)

        threading.Thread(target=worker, daemon=True).start()

    def _on_annotation_refresh_finished(self, code: int, error: str) -> None:
        self._annotation_refresh_running = False
        if self._annotation_refresh_toast is not None:
            try:
                self._annotation_refresh_toast.dismiss()
            except RuntimeError:
                pass
            self._annotation_refresh_toast = None
        if int(code) != 0:
            styled_info(
                self,
                strings.ANNOTATION_REFRESH_FAILED_TITLE,
                strings.ANNOTATION_REFRESH_FAILED_BODY_FMT.format(code=code, error=error or ""),
            )
            return

        self.route_mgr._annotation_points_cache = None
        try:
            self.route_mgr._point_icon_cache.clear()
            self.route_mgr._annotation_icon_cache.clear()
        except Exception:
            pass
        self.annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
        self.annotation_panel.set_preferences(self.annotation_type_ids)
        try:
            self.map_view._refresh_from_last_frame()
        except Exception:
            pass
        toast(self, strings.ANNOTATION_REFRESH_SUCCESS)

    def _reset_map_view(self) -> None:
        self.map_view.reset_view()

    def _clear_route_guide_hint(self) -> None:
        label = getattr(self, "tracked_guide_hint_label", None)
        if label is None:
            return
        label.clear()
        label.setMinimumWidth(0)
        label.setMaximumWidth(16777215)
        label.setVisible(False)

    def _fit_route_guide_hint_width(self) -> None:
        label = getattr(self, "tracked_guide_hint_label", None)
        header = getattr(self, "tracked_routes_header", None)
        title = getattr(self, "tracked_routes_title", None)
        layout = getattr(self, "tracked_routes_header_layout", None)
        toggle_btn = getattr(self, "tracked_routes_toggle_btn", None)
        if label is None or header is None or title is None or layout is None or not label.text():
            return

        margins = layout.contentsMargins()
        title_width = max(title.sizeHint().width(), title.fontMetrics().horizontalAdvance(title.text()))
        header_width = header.width()

        card = getattr(self, "tracked_routes_card", None)
        card_width = card.width() if card is not None else 0
        layout_margins = self.tracked_routes_layout.contentsMargins()
        card_content_width = card_width - layout_margins.left() - layout_margins.right()
        header_width = max(header_width, card_content_width, header.sizeHint().width())

        toggle_width = 0
        if toggle_btn is not None and toggle_btn.isVisible():
            toggle_width = max(toggle_btn.sizeHint().width(), toggle_btn.width()) + layout.spacing()
        available_width = (
            header_width
            - title_width
            - toggle_width
            - (layout.spacing() * 2)
            - margins.left()
            - margins.right()
        )
        available_width = max(80, available_width)
        content_width = label.fontMetrics().horizontalAdvance(label.text()) + 20
        target_width = min(content_width, available_width)
        label.setMinimumWidth(target_width)
        label.setMaximumWidth(target_width)
        label.updateGeometry()

    def _on_route_guide_hint_changed(self, hint: object) -> None:
        label = getattr(self, "tracked_guide_hint_label", None)
        if label is None:
            return
        mode_enum = self._mode.__class__
        if self._mode == mode_enum.TRACKING_LOST or not isinstance(hint, dict):
            self._clear_route_guide_hint()
            self.route_panel_controller.sync_tracked_routes_height(len(self.route_mgr.visible_routes()))
            self.window_mode_controller.schedule_layout_refresh()
            return

        distance_label = str(hint.get("distance_label") or "").strip()
        teleport_label = str(hint.get("teleport_label") or "").strip()
        if not distance_label:
            self._clear_route_guide_hint()
            self.route_panel_controller.sync_tracked_routes_height(len(self.route_mgr.visible_routes()))
            self.window_mode_controller.schedule_layout_refresh()
            return

        text = f"目标约 {distance_label}"
        if teleport_label:
            text += f" ｜ 最近传送点：{teleport_label}"
        label.setText(text)
        label.setVisible(True)
        self._fit_route_guide_hint_width()
        QTimer.singleShot(0, self._fit_route_guide_hint_width)
        self.route_panel_controller.sync_tracked_routes_height(len(self.route_mgr.visible_routes()))
        self.window_mode_controller.schedule_layout_refresh()

    def _paint_default_map(self) -> None:
        cx = self.tracker.map_width // 2
        cy = self.tracker.map_height // 2
        self.map_view.preview_relocate(cx, cy, TrackState.SEARCHING)

    def _open_settings(self) -> None:
        from ..dialogs.settings_dialog import close_active_settings_dialog, has_active_settings_dialog, open_settings_dialog

        if has_active_settings_dialog():
            close_active_settings_dialog()
            self.settings_btn.setChecked(False)
            return
        self.settings_btn.setChecked(True)
        open_settings_dialog(
            self,
            on_applied=self._on_settings_applied,
            on_closed=lambda: self.settings_btn.setChecked(False),
            on_annotation_refresh_requested=self._on_annotation_refresh_requested,
        )

    def _on_settings_applied(self) -> None:
        self._minimap_region = self.settings_gateway.get_minimap()
        self.route_panel_controller.refresh_route_checkbox_colors()
        self._refresh_hotkey_hint()
        self.hotkey_controller.stop_listener()
        self.hotkey_controller.start_listener()
        self._apply_configured_window_opacity()
        self.map_view._refresh_from_last_frame()

    def _collapse_to_icon(self) -> None:
        if self._mini_icon is not None:
            return
        toolbar = getattr(self, "route_drawing_toolbar", None)
        if toolbar is not None:
            toolbar.hide()
        geom = self.frameGeometry()
        anchor = geom.topLeft()
        self._mini_icon = RestoreIcon(self, self._restore_from_icon, self._close_app_from_icon)
        last = getattr(self, "_last_result", None)
        if last is not None:
            self._mini_icon.set_state(last.state)
        self._mini_icon.set_coord(self.coord_label.text())
        self._mini_icon.place_at(anchor)
        self._mini_icon.show()
        self.hide()

    def _restore_from_icon(self) -> None:
        if self._mini_icon is not None:
            self._mini_icon.close()
            self._mini_icon = None
        self.showNormal()
        self.raise_()
        self.activateWindow()
        drawing = getattr(self, "route_drawing_state", None)
        if drawing is not None and drawing.active:
            QTimer.singleShot(0, self.route_panel_controller._sync_route_drawing_ui)
            QTimer.singleShot(60, self.route_panel_controller.position_route_drawing_toolbar)

    def _close_app_from_icon(self) -> None:
        if self._mini_icon is not None:
            self._mini_icon.close()
            self._mini_icon = None
        self._quit_entire_app()

    def _quit_entire_app(self) -> None:
        self._running = False
        self.hotkey_controller.stop_listener()
        try:
            self.route_mgr.save_progress()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is not self:
                    widget.close()
            app.quit()
        self.close()

    def _update_window_controls(self) -> None:
        self.max_btn.setText("❐" if self.isMaximized() else "▢")
        self._update_header_button_labels()
        self._update_lock_button_visibility()

    def _set_header_button_presentation(
        self,
        button,
        *,
        text: str,
        icon_text: str,
        tooltip: str,
        compact_width: int = 34,
    ) -> None:
        button_specs.apply_header_button_presentation(
            button,
            icon_only=self._header_buttons_icon_only,
            spec=button_specs.HeaderButtonSpec(
                text=text,
                icon_text=icon_text,
                tooltip=tooltip,
                compact_width=compact_width,
            ),
        )

    def _update_header_button_labels(self) -> None:
        if self.window_mode_controller.is_pause_mode():
            sidebar_text = "开始导航"
            sidebar_icon = "导"
        elif self._sidebar_collapsed:
            sidebar_text = "展开侧边栏"
            sidebar_icon = "展"
        else:
            sidebar_text = "隐藏侧边栏"
            sidebar_icon = "隐"

        lock_text = "解锁" if self._locked else "锁定"
        lock_icon = "🔓" if self._locked else "🔒"
        is_paused = self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED)
        action_text = "开始导航" if is_paused else "重定位"
        action_icon = "导" if is_paused else "⌖"

        specs = [
            {"button": self.relocate_btn, "text": action_text, "icon_text": action_icon, "tooltip": action_text, "compact_width": 34},
            {"button": self.reset_view_btn, "text": "重置视图", "icon_text": "↺", "tooltip": "重置视图", "compact_width": 34},
            {"button": self.sidebar_toggle_btn, "text": sidebar_text, "icon_text": sidebar_icon, "tooltip": sidebar_text, "compact_width": 34},
            {"button": self.terminate_nav_btn, "text": "终止导航", "icon_text": "止", "tooltip": "终止导航", "compact_width": 34},
            {"button": self.lock_btn, "text": lock_text, "icon_text": lock_icon, "tooltip": lock_text, "compact_width": 34},
        ]

        self._header_buttons_icon_only = self.width() < self._HEADER_ICON_SWITCH_WIDTH
        for spec in specs:
            self._set_header_button_presentation(
                spec["button"],
                text=spec["text"],
                icon_text=spec["icon_text"],
                tooltip=spec["tooltip"],
                compact_width=spec["compact_width"],
            )

    def _update_lock_button_visibility(self) -> None:
        visible = self._mode in _STABLE_FAMILY
        self.terminate_nav_btn.setVisible(visible)
        self.lock_btn.setVisible(visible)

    def _can_toggle_lock(self) -> bool:
        return self._mode in _STABLE_FAMILY

    def _set_locked_state(self, locked: bool) -> None:
        self._locked = locked
        self.lock_btn.setChecked(self._locked)
        self._update_header_button_labels()
        self._refresh_hotkey_hint()
        self.unlock_hint_label.setVisible(self._locked)
        if self._locked:
            set_click_through(self, True)
        else:
            set_click_through(self, False)
        self._apply_configured_window_opacity()

    def _apply_configured_window_opacity(self) -> None:
        if self._locked:
            self.setWindowOpacity(self.settings_gateway.get_window_locked_opacity())
        else:
            self.setWindowOpacity(self.settings_gateway.get_window_normal_opacity())

    def _refresh_hotkey_hint(self) -> None:
        if not hasattr(self, "unlock_hint_label"):
            return
        label = hotkey_label(self.settings_gateway.get_toggle_lock_hotkey())
        self.unlock_hint_label.setText(f"快捷键 {label} 解锁")

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            target_area = self.interaction_controller.nested_sidebar_scroll_area(
                watched if isinstance(watched, QWidget) else None
            )
            if target_area is not None:
                self.interaction_controller.consume_inner_scroll(target_area, event)
                return True

        if (
            self._active_route_rename_item is not None
            and event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
        ):
            local_pos = self._active_route_rename_item.mapFromGlobal(event.globalPosition().toPoint())
            if not self._active_route_rename_item.rect().contains(local_pos):
                self.route_panel_controller.cancel_active_route_rename()

        if (
            self._adding_category
            and event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
            and self._add_category_row is not None
        ):
            local_pos = self._add_category_row.mapFromGlobal(event.globalPosition().toPoint())
            if not self._add_category_row.rect().contains(local_pos):
                self.route_panel_controller.cancel_add_category()

        if event.type() == QEvent.MouseButtonPress and hasattr(event, "globalPosition") and event.button() == Qt.LeftButton:
            if self.interaction_controller.sidebar_resize_hit(event.globalPosition().toPoint()):
                self._sidebar_resizing = True
                self._sidebar_resize_start_x = event.globalPosition().toPoint().x()
                self._sidebar_resize_start_width = self._sidebar_width
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return True

        if event.type() == QEvent.MouseMove and hasattr(event, "globalPosition"):
            if self._sidebar_resizing:
                self.interaction_controller.resize_sidebar(event.globalPosition().toPoint().x())
                return True
            if self.interaction_controller.sidebar_resize_hit(event.globalPosition().toPoint()):
                self.setCursor(QCursor(Qt.SizeHorCursor))
                self._edge_cursor_active = True
                return False

        if event.type() == QEvent.MouseButtonRelease and self._sidebar_resizing:
            self._sidebar_resizing = False
            return True

        if event.type() == QEvent.MouseButtonRelease and hasattr(event, "button") and event.button() == Qt.LeftButton:
            self._system_resize_edges = Qt.Edges()

        if watched is self.title_drag_area:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and not self.isMaximized():
                self._move_dragging = True
                self._move_drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and self._move_dragging and event.buttons() & Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._move_drag_offset)
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._move_dragging = False
                self._move_drag_offset = None
                return True

        if event.type() == QEvent.MouseMove and hasattr(event, "globalPosition"):
            self.interaction_controller.update_resize_cursor(event.globalPosition().toPoint())
        elif event.type() == QEvent.Leave and not self._move_dragging and self._edge_cursor_active:
            self.unsetCursor()
            self._edge_cursor_active = False

        if (
            event.type() == QEvent.MouseButtonPress
            and hasattr(event, "globalPosition")
            and event.button() == Qt.LeftButton
            and not self.isMaximized()
        ):
            edges = self.interaction_controller.resize_edges_at(event.globalPosition().toPoint())
            if edges and self.windowHandle() is not None and self.windowHandle().startSystemResize(edges):
                self._system_resize_edges = edges
                return True

        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if qt_event_matches_hotkey(event, self.settings_gateway.get_toggle_lock_hotkey()):
            if self._can_toggle_lock():
                self.toggle_lock()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_controls()
        self.window_mode_controller.position_sidebar_overlay()
        self.route_panel_controller.position_route_drawing_toolbar()

        if self.isMaximized() or self._applying_mode:
            return

        if self._mode in _STABLE_FAMILY and not self._tracking_bootstrap_pending:
            self._size_prefs[WindowMode.TRACKING_STABLE] = (self.width(), self.height())
            self._stable_size_save_timer.start()
        elif self._mode == WindowMode.TRACKING_LOST:
            return
        elif self._mode == WindowMode.PAUSED:
            self._size_prefs[WindowMode.PAUSED] = (self.width(), self.height())
            self._paused_size_save_timer.start()

        if self._system_resize_edges & Qt.RightEdge and not (self._system_resize_edges & Qt.LeftEdge):
            self._preferred_right_edge = self.x() + self.width()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.route_panel_controller.position_route_drawing_toolbar()
        if not self._applying_mode and not self.isMaximized():
            self._preferred_right_edge = self.x() + self.width()
        if (
            getattr(self, "annotation_panel", None) is not None
            and self.annotation_panel.isVisible()
            and not self.isMaximized()
        ):
            self._position_annotation_panel()

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_flags(self)

    def closeEvent(self, event):
        if not self.route_panel_controller.confirm_exit_route_drawing():
            event.ignore()
            return
        self._running = False
        self.hotkey_controller.stop_listener()
        self.route_panel_controller.save_route_section_expanded()
        self.route_mgr.save_visibility()
        self.route_mgr.save_progress()
        self.window_mode_controller.save_window_geometry()
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is not self:
                    widget.close()
            app.quit()
        super().closeEvent(event)

    def toggle_lock(self) -> None:
        if not self._can_toggle_lock():
            return
        self._preferred_locked = not self._locked
        self._set_locked_state(self._preferred_locked)

    def _prompt_relocate(self) -> None:
        if self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED):
            if not self.route_panel_controller.confirm_exit_route_drawing():
                return
            self.tracking_controller.start_navigation()
            return

        self._restore_lock_after_relocate = self._preferred_locked
        if self._mode == WindowMode.TRACKING_LOST:
            self.tracking_controller.exit_lost_mode()
        self.tracking_controller.resume_tracking_attempts()
        if self._mode == WindowMode.TRACKING_LOST:
            self.tracking_controller.set_alert_mode(True, "正在搜索目标，请稍候…", allow_terminate=True)
            self.tracking_controller.set_header_action_visibility(False)
            self.state_hint_label.setVisible(False)
        else:
            self.setMinimumHeight(self._normal_minimum_height)
            self.tracking_controller.set_alert_mode(False)
            self.tracking_controller.set_header_action_visibility(True)
            self.state_hint_label.setVisible(True)
            self.state_hint_label.setText("正在搜索目标，请稍候…")
            self.state_hint_label.setStyleSheet("")
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, latency_ms=0.0))
        self.map_view.preview_relocate(
            self.tracker.map_width // 2,
            self.tracker.map_height // 2,
            TrackState.SEARCHING,
        )

    def _on_relocate(self, x: int, y: int) -> None:
        self.tracker.set_anchor(x, y)
        self.map_view.preview_relocate(x, y, TrackState.SEARCHING)
        self.coord_label.setText(f"{x} , {y}")
        self._last_player_xy = (x, y)

        if self._mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED):
            return

        self.tracking_controller.resume_tracking_attempts()
        if self._restore_lock_after_relocate is not None:
            self._set_locked_state(self._restore_lock_after_relocate)
            self._restore_lock_after_relocate = None
            self._update_lock_button_visibility()
        self._frame_ready.emit(TrackResult(TrackState.SEARCHING, x=x, y=y, latency_ms=0.0))

    def _on_frame(self, result: TrackResult) -> None:
        state = TrackState.SEARCHING if self.isMaximized() else result.state
        if (
            not self.isMaximized()
            and not self._tracking_attempts_paused
            and state == TrackState.LOCKED
            and result.x is not None
            and result.y is not None
        ):
            if self._last_player_xy is not None:
                jump = max(
                    abs(result.x - self._last_player_xy[0]),
                    abs(result.y - self._last_player_xy[1]),
                )
                if jump >= theme.TRACK_JUMP_DETECT_THRESHOLD:
                    self._jump_anomaly_count += 1
                else:
                    self._jump_anomaly_count = 0

                if self._jump_anomaly_count >= theme.TRACK_JUMP_DETECT_LIMIT:
                    self._jump_anomaly_count = 0
                    self.tracking_controller.clear_tracker_anchor()
                    self._last_player_xy = None
                    state = TrackState.LOST
                    result = TrackResult(TrackState.LOST, latency_ms=result.latency_ms)
            else:
                self._jump_anomaly_count = 0
        elif state != TrackState.LOCKED:
            self._jump_anomaly_count = 0

        self._last_result = result
        self.dot.set_state(state)
        mini = self._mini_icon
        if mini is not None:
            mini.set_state(state)
        self.tracking_controller.apply_state_feedback(state)
        self._latencies.append(result.latency_ms)

        avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        fps = 1000.0 / avg_latency if avg_latency > 0 else 0.0

        if not self.isMaximized() and result.x is not None and result.y is not None:
            coord_text = f"{result.x} , {result.y}"
            self.coord_label.setText(coord_text)
            if self._last_player_xy is not None:
                dx = abs(result.x - self._last_player_xy[0])
                dy = abs(result.y - self._last_player_xy[1])
                if max(dx, dy) >= self._AUTO_RECENTER_MOVE_THRESHOLD:
                    self.map_view.set_center_locked(True)
            self._last_player_xy = (result.x, result.y)
            self.map_view.update_frame(result.state, result.x, result.y, self._latest_minimap)
            progress_signature = self.route_panel_controller.build_tracked_route_progress_signature()
            if progress_signature != self._tracked_route_progress_signature:
                self.route_panel_controller.refresh_tracked_routes()
        else:
            coord_text = "-- , --"
            self.coord_label.setText(coord_text)

        if mini is not None:
            mini.set_coord(coord_text)

        self.stat_label.setText(f"{avg_latency:4.0f} ms · {fps:4.1f} fps")

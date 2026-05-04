"""Window geometry, sidebar, and maximize helpers."""

from __future__ import annotations

import config
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from ..design import theme
from ..platform.win_overlay import apply_overlay_flags


class WindowModeController:
    def __init__(self, window) -> None:
        self.window = window

    def _stable_family(self):
        mode_enum = self.window._mode.__class__
        return (mode_enum.TRACKING_STABLE, mode_enum.TRACKING_INERTIAL)

    def _tracking_modes(self):
        mode_enum = self.window._mode.__class__
        return (
            mode_enum.TRACKING_STABLE,
            mode_enum.TRACKING_INERTIAL,
            mode_enum.TRACKING_LOST,
        )

    def window_geometry(self) -> QRect:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        total_width = theme.EXPANDED_W + self.window._window_margin * 2
        total_height = theme.EXPANDED_H + self.window._window_margin * 2
        x = screen.x() + (screen.width() - total_width) // 2
        y = screen.y() + theme.TOP_MARGIN
        return QRect(x, y, total_width, total_height)

    def place_on_top_center(self) -> None:
        self.window.setGeometry(self.window_geometry())

    def restore_or_center(self) -> None:
        mode_enum = self.window._mode.__class__
        saved = self.window.window_prefs_store.load_window_geometry()
        if saved is None or not self.geometry_is_visible(saved):
            self.place_on_top_center()
            return
        size = self.window._size_prefs.get(mode_enum.PAUSED, (saved["width"], saved["height"]))
        self.window.setGeometry(saved["x"], saved["y"], size[0], size[1])

    def toggle_sidebar(self) -> None:
        self.set_sidebar_collapsed(not self.window._sidebar_collapsed, restore_size=True)

    def handle_sidebar_action(self) -> None:
        if self.is_pause_mode():
            self.window.tracking_controller.start_navigation()
            return
        self.toggle_sidebar()

    def sync_normal_minimum_height(self) -> None:
        for layout in (
            self.window.root.layout(),
            self.window.body_container.layout(),
            self.window.map_shell.layout(),
            self.window.tracked_routes_layout,
        ):
            if layout is not None:
                layout.activate()

        root_layout = self.window.root.layout()
        if root_layout is None:
            return

        header_item = root_layout.itemAt(0)
        header_height = header_item.sizeHint().height() if header_item is not None else 0
        body_height = self.window.body_container.minimumSizeHint().height()
        margins = root_layout.contentsMargins()
        spacing = root_layout.spacing()
        computed_height = (
            self.window._window_margin * 2
            + margins.top()
            + margins.bottom()
            + header_height
            + body_height
            + spacing * 2
        )
        self.window._normal_minimum_height = max(self.window._normal_minimum_height, computed_height)

    def sync_compact_minimum_height(self) -> None:
        root_layout = self.window.root.layout()
        if root_layout is None:
            return

        root_layout.activate()
        header_item = root_layout.itemAt(0)
        header_height = header_item.sizeHint().height() if header_item is not None else 0
        margins = root_layout.contentsMargins()
        spacing = root_layout.spacing()
        visible_spacing = spacing if header_height > 0 else 0
        self.window._compact_minimum_height = (
            self.window._window_margin * 2
            + margins.top()
            + margins.bottom()
            + header_height
            + visible_spacing
            + theme.COMPACT_ALERT_HEIGHT
        )

    def apply_compact_constraints(self, enabled: bool) -> None:
        clear_hint = getattr(self.window, "_clear_route_guide_hint", None)
        if enabled and callable(clear_hint):
            clear_hint()

        self.sync_compact_minimum_height()
        maximum = 16777215
        root = self.window.root
        body = self.window.body_container
        map_shell = self.window.map_shell
        tracked_card = self.window.tracked_routes_card
        tracked_scroll = self.window.tracked_routes_scroll
        alert = self.window.alert_card

        if enabled:
            root_height = max(0, self.window._compact_minimum_height - self.window._window_margin * 2)
            root.setMinimumHeight(root_height)
            root.setMaximumHeight(root_height)
            body.hide()
            body.setMinimumHeight(0)
            body.setMaximumHeight(0)
            map_shell.setMinimumHeight(0)
            map_shell.setMaximumHeight(0)
            tracked_card.setMinimumHeight(0)
            tracked_card.setMaximumHeight(0)
            tracked_scroll.setMinimumHeight(0)
            tracked_scroll.setMaximumHeight(0)
            alert.setMinimumHeight(theme.COMPACT_ALERT_HEIGHT)
            alert.setMaximumHeight(theme.COMPACT_ALERT_HEIGHT)
            self.window.alert_message.setMaximumHeight(theme.COMPACT_ALERT_HEIGHT)
            self.window.alert_terminate_btn.setFixedHeight(theme.ALERT_ACTION_HEIGHT)
            alert.show()
            self.window.setMinimumHeight(self.window._compact_minimum_height)
            self.window.setMaximumHeight(self.window._compact_minimum_height)
        else:
            root.setMinimumHeight(0)
            root.setMaximumHeight(maximum)
            self.window.setMaximumHeight(maximum)
            body.setMaximumHeight(maximum)
            map_shell.setMaximumHeight(maximum)
            tracked_scroll.setMaximumHeight(theme.TRACKED_ROUTES_MAX_HEIGHT)
            alert.setMinimumHeight(0)
            alert.setMaximumHeight(maximum)
            self.window.alert_message.setMaximumHeight(maximum)
            self.window.alert_terminate_btn.setFixedHeight(theme.ALERT_ACTION_HEIGHT)
            alert.hide()
            body.show()
            self.window.setMinimumHeight(self.window._normal_minimum_height)
            sync_routes = getattr(self.window.route_panel_controller, "sync_tracked_routes_height", None)
            if callable(sync_routes):
                sync_routes(len(self.window.route_mgr.visible_routes()))

        for layout in (
            self.window.root.layout(),
            self.window.body_container.layout(),
            self.window.map_shell.layout(),
            self.window.tracked_routes_layout,
        ):
            if layout is not None:
                layout.invalidate()
                layout.activate()

    def schedule_layout_refresh(self) -> None:
        QTimer.singleShot(0, self.refresh_layout_constraints)

    def refresh_layout_constraints(self) -> None:
        mode_enum = self.window._mode.__class__
        if self.window._mode == mode_enum.TRACKING_LOST:
            self.sync_compact_minimum_height()
            self.window.setMinimumWidth(self.window._normal_minimum_width)
            self.window.setMinimumHeight(self.window._compact_minimum_height)
            self.window.setMaximumHeight(self.window._compact_minimum_height)
            return

        self.sync_normal_minimum_height()
        self.sync_compact_minimum_height()
        self.window.setMaximumHeight(16777215)
        self.window.setMinimumWidth(self.window._normal_minimum_width)

        self.window.setMinimumHeight(self.window._normal_minimum_height)

        if self.window.isMaximized() or self.window._applying_mode:
            return

        if self.window.height() < self.window._normal_minimum_height:
            self.apply_geometry_for_mode((self.window.width(), self.window._normal_minimum_height))

    def is_pause_mode(self) -> bool:
        mode_enum = self.window._mode.__class__
        return self.window._mode in (mode_enum.PAUSED, mode_enum.MAXIMIZED)

    def set_sidebar_collapsed(self, collapsed: bool, restore_size: bool) -> None:
        if collapsed == self.window._sidebar_collapsed:
            self.apply_sidebar_state()
            return
        self.window._sidebar_collapsed = collapsed
        self.window._sidebar_expand_restore_geometry = None
        self.apply_sidebar_state()

    def _horizontal_layout_metrics(self) -> tuple[int, int]:
        root_layout = self.window.root.layout()
        body_layout = self.window.body_container.layout()
        root_margins = root_layout.contentsMargins() if root_layout is not None else None
        body_margins = body_layout.contentsMargins() if body_layout is not None else None
        horizontal_padding = self.window._window_margin * 2
        if root_margins is not None:
            horizontal_padding += root_margins.left() + root_margins.right()
        if body_margins is not None:
            horizontal_padding += body_margins.left() + body_margins.right()
        body_spacing = body_layout.spacing() if body_layout is not None else 0
        return horizontal_padding, body_spacing

    def width_for_sidebar_width(self, sidebar_width: int) -> int:
        horizontal_padding, body_spacing = self._horizontal_layout_metrics()
        return max(
            self.window._normal_minimum_width,
            self.window.map_view.minimumWidth()
            + max(self.window._SIDEBAR_MIN_WIDTH, int(sidebar_width))
            + body_spacing
            + horizontal_padding,
        )

    def expanded_layout_minimum_width(self) -> int:
        return self.width_for_sidebar_width(self.window._sidebar_width)

    def max_sidebar_width_for_current_window(self) -> int:
        horizontal_padding, body_spacing = self._horizontal_layout_metrics()
        available = self.window.width() - self.window.map_view.minimumWidth() - body_spacing - horizontal_padding
        return max(self.window._SIDEBAR_MIN_WIDTH, available)

    def set_sidebar_in_body_layout(self, in_layout: bool) -> None:
        body_layout = self.window.body_container.layout()
        if body_layout is None:
            return
        index = body_layout.indexOf(self.window.sidebar_shell)
        if in_layout and index < 0:
            body_layout.addWidget(self.window.sidebar_shell, stretch=4)
            body_layout.setStretch(0, 7)
            body_layout.setStretch(1, 4)
        elif not in_layout and index >= 0:
            body_layout.removeWidget(self.window.sidebar_shell)
            self.window.sidebar_shell.setParent(self.window.body_container)

    def position_sidebar_overlay(self) -> None:
        mode_enum = self.window._mode.__class__
        if self.window._mode in (mode_enum.PAUSED, mode_enum.MAXIMIZED):
            return
        if self.window._sidebar_collapsed or not self.window.sidebar_shell.isVisible():
            return
        target_width = max(self.window._SIDEBAR_MIN_WIDTH, self.window._sidebar_width)
        body_rect = self.window.body_container.rect()
        x = max(0, body_rect.width() - target_width)
        self.window.sidebar_shell.setGeometry(x, 0, target_width, body_rect.height())
        self.window.sidebar_shell.raise_()

    def sync_window_minimum_width(self) -> None:
        mode_enum = self.window._mode.__class__
        if self.window._mode in (mode_enum.PAUSED, mode_enum.MAXIMIZED):
            self.window.setMinimumWidth(self.expanded_layout_minimum_width())
        else:
            self.window.setMinimumWidth(self.window._normal_minimum_width)

    def apply_sidebar_state(self) -> None:
        target_width = max(self.window._SIDEBAR_MIN_WIDTH, self.window._sidebar_width)
        if self.is_pause_mode():
            self.set_sidebar_in_body_layout(True)
            self.window.sidebar_shell.setVisible(True)
            self.window.side_scroll.setVisible(True)
            self.window.sidebar_shell.setMinimumWidth(target_width)
            self.window.sidebar_shell.setMaximumWidth(target_width)
            self.sync_window_minimum_width()
            self.window._update_header_button_labels()
            return

        if self.window._sidebar_collapsed:
            self.set_sidebar_in_body_layout(False)
            self.window.sidebar_shell.setVisible(False)
        else:
            self.set_sidebar_in_body_layout(False)
            self.window.sidebar_shell.setVisible(True)
            self.window.side_scroll.setVisible(True)
            self.window.sidebar_shell.setMinimumWidth(target_width)
            self.window.sidebar_shell.setMaximumWidth(target_width)
            self.position_sidebar_overlay()
        self.sync_window_minimum_width()
        self.window._update_header_button_labels()

    def enter_mode(self, new_mode) -> None:
        if self.window._applying_mode:
            return
        self.window._applying_mode = True
        try:
            mode_enum = self.window._mode.__class__
            stable_family = self._stable_family()
            tracking_modes = self._tracking_modes()
            old_mode = self.window._mode
            self.window._mode = new_mode
            if new_mode not in stable_family:
                self.window._sidebar_expand_restore_geometry = None

            entering_compact = new_mode == mode_enum.TRACKING_LOST
            leaving_compact = old_mode == mode_enum.TRACKING_LOST and new_mode != mode_enum.TRACKING_LOST
            if entering_compact:
                self.apply_compact_constraints(True)
            elif leaving_compact:
                self.apply_compact_constraints(False)

            if new_mode == mode_enum.MAXIMIZED:
                if old_mode != mode_enum.MAXIMIZED:
                    self.window._geometry_before_max = QRect(self.window.geometry())
                    self.window._sidebar_collapsed_before_max = self.window._sidebar_collapsed
                    self.window._sidebar_width_before_max = self.window._sidebar_width
                self.window._sidebar_collapsed = False
                self.window._sidebar_width = theme.MAXIMIZED_SIDEBAR_WIDTH
                self.apply_sidebar_state()
                if not self.window.isMaximized():
                    self.window.showMaximized()
            else:
                if old_mode == mode_enum.MAXIMIZED:
                    if self.window._sidebar_width_before_max is not None:
                        self.window._sidebar_width = self.window._sidebar_width_before_max
                        self.window._sidebar_width_before_max = None
                    if self.window._sidebar_collapsed_before_max is not None:
                        self.window._sidebar_collapsed = self.window._sidebar_collapsed_before_max
                        self.window._sidebar_collapsed_before_max = None
                if self.window.isMaximized():
                    self.window.setWindowState(self.window.windowState() & ~Qt.WindowMaximized)

                if new_mode == mode_enum.PAUSED:
                    if old_mode != mode_enum.PAUSED:
                        self.window._sidebar_collapsed_before_pause = self.window._sidebar_collapsed
                        self.window._sidebar_width_before_pause = self.window._sidebar_width
                    self.window._sidebar_width = self.window._paused_sidebar_width
                    if self.window._sidebar_collapsed:
                        self.window._sidebar_collapsed = False
                elif old_mode == mode_enum.PAUSED:
                    self.window._paused_sidebar_width = self.window._sidebar_width
                    if self.window._sidebar_width_before_pause is not None:
                        self.window._sidebar_width = self.window._sidebar_width_before_pause
                    if self.window._sidebar_collapsed_before_pause is not None:
                        self.window._sidebar_collapsed = self.window._sidebar_collapsed_before_pause
                        self.window._sidebar_collapsed_before_pause = None

                self.apply_sidebar_state()

                same_family_shift = old_mode in stable_family and new_mode in stable_family
                if not same_family_shift:
                    self.apply_geometry_for_mode(self.size_for_mode(new_mode))
                else:
                    self.window.setMinimumHeight(self.window._normal_minimum_height)

            self.apply_mode_ui(new_mode, old_mode, tracking_modes)
            if new_mode == mode_enum.TRACKING_LOST and not self.window.isMaximized():
                self.apply_compact_constraints(True)
                self.apply_geometry_for_mode(self.size_for_mode(new_mode))
                QTimer.singleShot(0, lambda: self.apply_geometry_for_mode(self.size_for_mode(new_mode)))
            self.schedule_layout_refresh()
            QTimer.singleShot(0, self.window.route_panel_controller.position_route_drawing_toolbar)
            QTimer.singleShot(60, self.window.route_panel_controller.position_route_drawing_toolbar)
        finally:
            self.window._applying_mode = False

    def size_for_mode(self, mode) -> tuple[int, int]:
        mode_enum = self.window._mode.__class__
        if mode == mode_enum.PAUSED:
            return self.window._size_prefs[mode_enum.PAUSED]

        stable_size = self.window._size_prefs.get(
            mode_enum.TRACKING_STABLE,
            self.window._size_prefs[mode_enum.PAUSED],
        )

        if mode in self._stable_family():
            return stable_size

        if mode == mode_enum.TRACKING_LOST:
            compact_h = getattr(
                self.window,
                "_compact_minimum_height",
                theme.COMPACT_ALERT_HEIGHT + self.window._window_margin * 2,
            )
            return (stable_size[0], compact_h)

        return stable_size

    def apply_geometry_for_mode(self, size: tuple[int, int]) -> None:
        w, h = size
        w = max(self.window.minimumWidth(), self.window._normal_minimum_width, w)

        mode_enum = self.window._mode.__class__
        if self.window._mode == mode_enum.TRACKING_LOST:
            compact_minimum_height = getattr(
                self.window,
                "_compact_minimum_height",
                theme.COMPACT_ALERT_HEIGHT + self.window._window_margin * 2,
            )
            self.window.setMinimumHeight(compact_minimum_height)
            self.window.setMaximumHeight(compact_minimum_height)
            h = compact_minimum_height
        else:
            self.window.setMaximumHeight(16777215)
            self.window.setMinimumHeight(self.window._normal_minimum_height)
            h = max(self.window._normal_minimum_height, h)

        geom = self.window.geometry()
        if self.window._preferred_right_edge is None:
            self.window._preferred_right_edge = geom.x() + geom.width()

        new_x = self.window._preferred_right_edge - w
        new_y = geom.y()
        screen_geo = self.current_screen_available_geometry()
        if screen_geo is not None:
            new_x = max(screen_geo.left(), new_x)
            if new_x + w > screen_geo.right():
                new_x = max(screen_geo.left(), screen_geo.right() - w)

        self.window.setGeometry(new_x, new_y, w, h)

    def apply_mode_ui(self, new_mode, old_mode, tracking_modes) -> None:
        mode_enum = self.window._mode.__class__
        stable_family = self._stable_family()
        pause_family = (mode_enum.PAUSED, mode_enum.MAXIMIZED)
        in_alert = new_mode == mode_enum.TRACKING_LOST
        self.window.tracking_controller.set_alert_mode(in_alert)

        if new_mode in pause_family:
            self.window._tracking_attempts_paused = True
            self.window._restore_lock_after_relocate = None
            self.window._lock_state_before_lost = None
            self.window._jump_anomaly_count = 0
            self.window.tracking_controller.set_header_action_visibility(False)
            self.window.state_hint_label.setVisible(False)
        else:
            if old_mode in pause_family:
                self.window._tracking_attempts_paused = False
                self.window._jump_anomaly_count = 0
            header_visible = new_mode != mode_enum.MAXIMIZED and new_mode != mode_enum.TRACKING_LOST
            self.window.tracking_controller.set_header_action_visibility(header_visible)
            if new_mode in tracking_modes and old_mode != new_mode:
                if new_mode == mode_enum.TRACKING_LOST:
                    self.window.state_hint_label.setVisible(False)
                else:
                    self.window.state_hint_label.setVisible(True)
                    if old_mode == mode_enum.PAUSED:
                        self.window.state_hint_label.setText("正在搜索目标，请稍候…")
                        self.window.state_hint_label.setStyleSheet("")

            if new_mode in stable_family and old_mode in pause_family:
                if not bool(getattr(config, "WINDOW_LOCK_FOLLOWS_GUIDE", False)):
                    desired_locked = bool(self.window._preferred_locked)
                    if self.window._locked != desired_locked:
                        self.window._set_locked_state(desired_locked)

        self.window._update_lock_button_visibility()
        self.window._update_header_button_labels()
        sync_route_point_drag = getattr(self.window, "_sync_route_point_drag_enabled", None)
        if callable(sync_route_point_drag):
            sync_route_point_drag()

    def flush_stable_size_to_config(self) -> None:
        mode_enum = self.window._mode.__class__
        size = self.window._size_prefs.get(mode_enum.TRACKING_STABLE)
        if size is None:
            return
        try:
            self.window.window_prefs_store.save_payload({
                "LOCKED_VIEW_SIZE": {
                    "width": int(size[0]),
                    "height": int(size[1]),
                }
            })
        except Exception as e:
            print(f"保存稳定态尺寸失败：{e}")

    def flush_paused_size_to_config(self) -> None:
        mode_enum = self.window._mode.__class__
        size = self.window._size_prefs.get(mode_enum.PAUSED)
        if size is None:
            return
        try:
            self.window.window_prefs_store.save_payload({
                "PAUSED_VIEW_SIZE": {
                    "width": int(size[0]),
                    "height": int(size[1]),
                }
            })
        except Exception as e:
            print(f"保存暂停态尺寸失败：{e}")

    def current_screen_available_geometry(self) -> QRect | None:
        screen = self.window.screen() if hasattr(self.window, "screen") else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    @staticmethod
    def geometry_is_visible(g: dict) -> bool:
        screens = QGuiApplication.screens() or []
        if not screens:
            return True
        saved = QRect(g["x"], g["y"], g["width"], g["height"])
        for screen in screens:
            if screen.availableGeometry().intersects(saved):
                return True
        return False

    def sync_view_prefs_before_persist(self) -> None:
        mode_enum = self.window._mode.__class__
        stable_family = self._stable_family()
        if self.window._stable_size_save_timer.isActive():
            self.window._stable_size_save_timer.stop()
        if self.window._paused_size_save_timer.isActive():
            self.window._paused_size_save_timer.stop()

        if self.window.isMaximized():
            base_geom = QRect(self.window._geometry_before_max or self.window.geometry())
            source_mode = self.window._mode_before_max or mode_enum.PAUSED
        else:
            base_geom = QRect(self.window.geometry())
            source_mode = self.window._mode

        if source_mode == mode_enum.PAUSED:
            self.window._size_prefs[mode_enum.PAUSED] = (
                max(self.window._normal_minimum_width, int(base_geom.width())),
                max(self.window._normal_minimum_height, int(base_geom.height())),
            )
            if self.window.isMaximized():
                if self.window._sidebar_width_before_max is not None:
                    self.window._paused_sidebar_width = int(self.window._sidebar_width_before_max)
            else:
                self.window._paused_sidebar_width = int(self.window._sidebar_width)
        elif source_mode in stable_family:
            self.window._size_prefs[mode_enum.TRACKING_STABLE] = (
                max(self.window._normal_minimum_width, int(base_geom.width())),
                max(self.window._normal_minimum_height, int(base_geom.height())),
            )

    def startup_geometry_to_persist(self, base_geom: QRect) -> QRect:
        mode_enum = self.window._mode.__class__
        paused_size = self.window._size_prefs.get(
            mode_enum.PAUSED,
            (int(base_geom.width()), int(base_geom.height())),
        )
        width = max(self.window._normal_minimum_width, int(paused_size[0]))
        height = max(self.window._normal_minimum_height, int(paused_size[1]))
        right_edge = self.window._preferred_right_edge
        if right_edge is None:
            right_edge = int(base_geom.x() + base_geom.width())

        x = int(right_edge - width)
        y = int(base_geom.y())
        screen_geo = self.current_screen_available_geometry()
        if screen_geo is not None:
            x = max(screen_geo.left(), x)
            if x + width > screen_geo.right():
                x = max(screen_geo.left(), screen_geo.right() - width)
            y = max(screen_geo.top(), y)
            if y + height > screen_geo.bottom():
                y = max(screen_geo.top(), screen_geo.bottom() - height)

        return QRect(x, y, width, height)

    def save_window_geometry(self) -> None:
        mode_enum = self.window._mode.__class__
        self.sync_view_prefs_before_persist()
        g = QRect(self.window.geometry())
        if self.window._mode == mode_enum.PAUSED:
            tracking_sidebar_collapsed = bool(
                self.window._sidebar_collapsed_before_pause
                if self.window._sidebar_collapsed_before_pause is not None
                else self.window._sidebar_collapsed
            )
            tracking_sidebar_width = int(
                self.window._sidebar_width_before_pause
                if self.window._sidebar_width_before_pause is not None
                else self.window._sidebar_width
            )
            paused_sidebar_width = int(self.window._sidebar_width)
        elif self.window._mode == mode_enum.MAXIMIZED:
            if self.window._geometry_before_max is not None:
                g = QRect(self.window._geometry_before_max)
            source_mode = self.window._mode_before_max or mode_enum.PAUSED
            if source_mode == mode_enum.PAUSED:
                tracking_sidebar_collapsed = bool(
                    self.window._sidebar_collapsed_before_pause
                    if self.window._sidebar_collapsed_before_pause is not None
                    else config.SIDEBAR_COLLAPSED
                )
                tracking_sidebar_width = int(
                    self.window._sidebar_width_before_pause
                    if self.window._sidebar_width_before_pause is not None
                    else config.SIDEBAR_WIDTH
                )
                paused_sidebar_width = int(
                    self.window._sidebar_width_before_max
                    if self.window._sidebar_width_before_max is not None
                    else self.window._paused_sidebar_width
                )
            else:
                tracking_sidebar_collapsed = bool(
                    self.window._sidebar_collapsed_before_max
                    if self.window._sidebar_collapsed_before_max is not None
                    else self.window._sidebar_collapsed
                )
                tracking_sidebar_width = int(
                    self.window._sidebar_width_before_max
                    if self.window._sidebar_width_before_max is not None
                    else self.window._sidebar_width
                )
                paused_sidebar_width = int(self.window._paused_sidebar_width)
        else:
            tracking_sidebar_collapsed = bool(self.window._sidebar_collapsed)
            tracking_sidebar_width = int(self.window._sidebar_width)
            paused_sidebar_width = int(self.window._paused_sidebar_width)
        startup_geom = self.startup_geometry_to_persist(g)
        payload: dict = {
            "WINDOW_GEOMETRY": {
                "x": int(startup_geom.x()),
                "y": int(startup_geom.y()),
                "width": int(startup_geom.width()),
                "height": int(startup_geom.height()),
            },
            "SIDEBAR_COLLAPSED": tracking_sidebar_collapsed,
            "SIDEBAR_WIDTH": tracking_sidebar_width,
            "PAUSED_SIDEBAR_WIDTH": paused_sidebar_width,
        }
        stable = self.window._size_prefs.get(mode_enum.TRACKING_STABLE)
        if stable is not None:
            payload["LOCKED_VIEW_SIZE"] = {
                "width": int(stable[0]),
                "height": int(stable[1]),
            }
        paused = self.window._size_prefs.get(mode_enum.PAUSED)
        if paused is not None:
            payload["PAUSED_VIEW_SIZE"] = {
                "width": int(paused[0]),
                "height": int(paused[1]),
            }
        try:
            self.window.window_prefs_store.save_payload(payload)
        except Exception as e:
            print(f"保存窗口几何失败：{e}")

    def toggle_maximize_restore(self) -> None:
        mode_enum = self.window._mode.__class__
        if self.window.isMaximized():
            target = self.window._mode_before_max or mode_enum.PAUSED
            if target not in (mode_enum.PAUSED, mode_enum.MAXIMIZED):
                if not self.window.route_panel_controller.confirm_exit_route_drawing():
                    return
            self.window._mode_before_max = None
            self.enter_mode(target)
        else:
            self.window._mode_before_max = self.window._mode
            self.enter_mode(mode_enum.MAXIMIZED)
        self.window._update_window_controls()
        apply_overlay_flags(self.window)
        QTimer.singleShot(0, self.window.route_panel_controller.position_route_drawing_toolbar)
        QTimer.singleShot(60, self.window.route_panel_controller.position_route_drawing_toolbar)
        QTimer.singleShot(0, self.window.map_view._refresh_from_last_frame)
        QTimer.singleShot(60, self.window.map_view._refresh_from_last_frame)

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui_island.app.window import IslandWindow, WindowMode
from ui_island.controllers.tracking_controller import TrackingController
from ui_island.controllers.window_mode_controller import WindowModeController
from ui_island.state.tracking import TrackResult, TrackState


_TRACKING_MODES = (
    WindowMode.TRACKING_STABLE,
    WindowMode.TRACKING_INERTIAL,
    WindowMode.TRACKING_LOST,
)


class _Widget:
    def __init__(self) -> None:
        self.visible: bool | None = None
        self.texts: list[str] = []

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def isVisible(self) -> bool:
        return self.visible is not False

    def hide(self) -> None:
        self.setVisible(False)

    def show(self) -> None:
        self.setVisible(True)

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def setStyleSheet(self, _style: str) -> None:
        pass


class _Layout:
    def __init__(self) -> None:
        self.margins: tuple[int, int, int, int] | None = None
        self.spacing: int | None = None
        self.invalidated = 0
        self.activated = 0

    def setContentsMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        self.margins = (left, top, right, bottom)

    def setSpacing(self, spacing: int) -> None:
        self.spacing = int(spacing)

    def invalidate(self) -> None:
        self.invalidated += 1

    def activate(self) -> None:
        self.activated += 1


class _Margins:
    def __init__(self, left: int = 0, right: int = 0) -> None:
        self._left = left
        self._right = right

    def left(self) -> int:
        return self._left

    def right(self) -> int:
        return self._right


class _Container(_Widget):
    def __init__(self, layout: _Layout | None = None) -> None:
        super().__init__()
        self._layout = layout

    def layout(self):
        return self._layout


class _Size:
    def __init__(self, width: int = 0, height: int = 0) -> None:
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FontMetrics:
    def horizontalAdvance(self, text: str) -> int:
        return len(str(text)) * 10


class _HintLabel(_Widget):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.minimum_width: int | None = None
        self.maximum_width: int | None = None

    def text(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""

    def fontMetrics(self) -> _FontMetrics:
        return _FontMetrics()

    def setMinimumWidth(self, width: int) -> None:
        self.minimum_width = int(width)

    def setMaximumWidth(self, width: int) -> None:
        self.maximum_width = int(width)

    def updateGeometry(self) -> None:
        pass


class _HeaderWidget(_Widget):
    def __init__(self, width: int = 0, size_width: int = 0, text: str = "") -> None:
        super().__init__()
        self._width = width
        self._size_width = size_width
        self._text = text

    def width(self) -> int:
        return self._width

    def sizeHint(self) -> _Size:
        return _Size(self._size_width)

    def text(self) -> str:
        return self._text

    def fontMetrics(self) -> _FontMetrics:
        return _FontMetrics()


class _HeaderLayout:
    def __init__(self, spacing: int = 8) -> None:
        self._spacing = spacing

    def contentsMargins(self) -> _Margins:
        return _Margins()

    def spacing(self) -> int:
        return self._spacing


class _TrackedLayout:
    def contentsMargins(self) -> _Margins:
        return _Margins(12, 12)


class _HeaderButton(_Widget):
    def __init__(self, width: int, visible: bool = True) -> None:
        super().__init__()
        self.visible = visible
        self._width = width

    def width(self) -> int:
        return self._width

    def sizeHint(self) -> _Size:
        return _Size(self._width)


class _FrameReady:
    def __init__(self) -> None:
        self.results: list[TrackResult] = []

    def emit(self, result: TrackResult) -> None:
        self.results.append(result)


class _RoutePanelController:
    def __init__(self, confirm: bool = True) -> None:
        self.confirm = confirm

    def confirm_exit_route_drawing(self) -> bool:
        return self.confirm


class _WindowModeHarness:
    def __init__(self, window) -> None:
        self.window = window
        self.ui_controller = WindowModeController(window)
        self.sidebar_applied = 0
        self.compact_calls: list[bool] = []
        self.synced_minimum_height = 0

    def enter_mode(self, new_mode: WindowMode) -> None:
        old_mode = self.window._mode
        self.window._mode = new_mode
        self.ui_controller.apply_mode_ui(new_mode, old_mode, _TRACKING_MODES)

    def apply_sidebar_state(self) -> None:
        self.sidebar_applied += 1

    def apply_compact_constraints(self, enabled: bool) -> None:
        self.compact_calls.append(bool(enabled))

    def sync_normal_minimum_height(self) -> None:
        self.synced_minimum_height += 1


class _PureWindowModeHarness:
    def __init__(self) -> None:
        self.sidebar_applied = 0

    def apply_sidebar_state(self) -> None:
        self.sidebar_applied += 1


class _SettingsGateway:
    def __init__(self, pure: bool) -> None:
        self.pure = pure

    def get_pure_navigation_mode(self) -> bool:
        return self.pure


class _FakeWindow:
    _is_unlock_only_lock_mode = IslandWindow._is_unlock_only_lock_mode
    _can_toggle_lock = IslandWindow._can_toggle_lock
    toggle_lock = IslandWindow.toggle_lock

    def __init__(
        self,
        *,
        mode: WindowMode = WindowMode.PAUSED,
        locked: bool = False,
        preferred_locked: bool = False,
    ) -> None:
        self._mode = mode
        self._locked = locked
        self._preferred_locked = preferred_locked
        self._mode_before_max = None
        self._restore_lock_after_relocate = None
        self._lock_state_before_lost = None
        self._tracking_paused_state = TrackState.SEARCHING
        self._tracking_attempts_paused = False
        self._tracking_bootstrap_pending = False
        self._jump_anomaly_count = 0
        self._normal_minimum_height = 300
        self.lock_changes: list[bool] = []
        self.lock_visibility_updates = 0
        self.header_visibility: list[bool] = []
        self.minimum_heights: list[int] = []

        self.route_panel_controller = _RoutePanelController()
        self.tracking_controller = TrackingController(self)
        self.window_mode_controller = _WindowModeHarness(self)
        self._frame_ready = _FrameReady()
        self.route_drawing_state = SimpleNamespace(active=False)

        self.alert_message = _Widget()
        self.alert_terminate_btn = _Widget()
        self.state_hint_label = _Widget()
        self.relocate_btn = _Widget()
        self.reset_view_btn = _Widget()
        self.sidebar_toggle_btn = _Widget()

    def _set_locked_state(self, locked: bool) -> None:
        self._locked = bool(locked)
        self.lock_changes.append(self._locked)

    def _update_lock_button_visibility(self) -> None:
        self.lock_visibility_updates += 1

    def _update_header_button_labels(self) -> None:
        pass

    def _sync_route_point_drag_enabled(self) -> None:
        pass

    def setMinimumHeight(self, height: int) -> None:
        self.minimum_heights.append(int(height))


class _PureWindow:
    _is_pure_navigation_active = IslandWindow._is_pure_navigation_active
    _apply_pure_navigation_ui = IslandWindow._apply_pure_navigation_ui
    _update_lock_button_visibility = IslandWindow._update_lock_button_visibility

    def __init__(self, mode: WindowMode, pure: bool) -> None:
        self._mode = mode
        self.settings_gateway = _SettingsGateway(pure)
        self.root_layout = _Layout()
        self.map_layout = _Layout()
        self.body_layout = _Layout()
        self.tracked_routes_layout = _Layout()
        self.root = _Container(self.root_layout)
        self.map_shell = _Container(self.map_layout)
        self.body_container = _Container(self.body_layout)
        self._root_layout_margins = (12, 8, 12, 10)
        self._root_layout_spacing = 8
        self._pure_root_layout_margins = (8, 8, 8, 8)
        self._pure_root_layout_spacing = 0
        self._map_layout_spacing = 10
        self._pure_map_layout_spacing = 0
        self._pure_navigation_active = False
        self.cleared_hint = 0

        self.title_drag_area = _Widget()
        self.settings_btn = _Widget()
        self.min_btn = _Widget()
        self.max_btn = _Widget()
        self.close_btn = _Widget()
        self.relocate_btn = _Widget()
        self.reset_view_btn = _Widget()
        self.sidebar_toggle_btn = _Widget()
        self.terminate_nav_btn = _Widget()
        self.lock_btn = _Widget()
        self.tracked_routes_card = _Widget()
        self.sidebar_shell = _Widget()

        self.window_mode_controller = _PureWindowModeHarness()
        self.tracking_controller = TrackingController(self)

    def _clear_route_guide_hint(self) -> None:
        self.cleared_hint += 1

    def _update_header_button_labels(self) -> None:
        pass


class _HintWindow:
    _fit_route_guide_hint_width = IslandWindow._fit_route_guide_hint_width

    def __init__(self, *, clear_visible: bool) -> None:
        self.tracked_guide_hint_label = _HintLabel("目标线 99m → 最近传送点：很长很长很长很长很长的名字")
        self.tracked_routes_header = _HeaderWidget(width=420, size_width=420)
        self.tracked_routes_title = _HeaderWidget(text="当前追踪路线 (2)")
        self.tracked_routes_header_layout = _HeaderLayout(spacing=8)
        self.tracked_routes_toggle_btn = _HeaderButton(26, visible=True)
        self.tracked_routes_clear_progress_btn = _HeaderButton(26, visible=clear_visible)
        self.tracked_routes_card = _HeaderWidget(width=420)
        self.tracked_routes_layout = _TrackedLayout()


class TrackingLockStateTests(unittest.TestCase):
    def test_enabled_lock_flow_applies_user_preference_in_lost_and_paused(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.TRACKING_STABLE,
            locked=False,
            preferred_locked=True,
        )

        with patch("config.WINDOW_LOCK_FOLLOWS_GUIDE", True, create=True):
            window.tracking_controller.enter_lost_mode()
            self.assertEqual(window._mode, WindowMode.TRACKING_LOST)
            self.assertTrue(window._locked)
            self.assertTrue(window._preferred_locked)
            self.assertTrue(window._lock_state_before_lost)
            self.assertEqual(window.lock_changes, [True])

            window.tracking_controller.pause_navigation()

        self.assertEqual(window._mode, WindowMode.PAUSED)
        self.assertTrue(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertIsNone(window._lock_state_before_lost)

    def test_disabled_lock_flow_forces_lost_and_paused_unlocked(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.TRACKING_STABLE,
            locked=True,
            preferred_locked=True,
        )

        with patch("config.WINDOW_LOCK_FOLLOWS_GUIDE", False, create=True):
            window.tracking_controller.enter_lost_mode()

        self.assertEqual(window._mode, WindowMode.TRACKING_LOST)
        self.assertFalse(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertTrue(window._lock_state_before_lost)
        self.assertEqual(window.lock_changes, [False])

        window._locked = True
        window.lock_changes.clear()
        with patch("config.WINDOW_LOCK_FOLLOWS_GUIDE", False, create=True):
            window.tracking_controller.pause_navigation()

        self.assertEqual(window._mode, WindowMode.PAUSED)
        self.assertFalse(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertIsNone(window._lock_state_before_lost)
        self.assertEqual(window.lock_changes, [False])

    def test_paused_feedback_does_not_force_unlock(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.PAUSED,
            locked=True,
            preferred_locked=True,
        )
        window._lock_state_before_lost = True

        window.tracking_controller.apply_state_feedback(TrackState.SEARCHING)

        self.assertTrue(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertIsNone(window._lock_state_before_lost)
        self.assertNotIn(False, window.lock_changes)

    def test_start_navigation_applies_saved_locked_preference(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.PAUSED,
            locked=False,
            preferred_locked=True,
        )

        with patch("config.WINDOW_LOCK_FOLLOWS_GUIDE", False, create=True):
            window.tracking_controller.start_navigation()

        self.assertEqual(window._mode, WindowMode.TRACKING_STABLE)
        self.assertTrue(window._locked)
        self.assertEqual(window.lock_changes[-1], True)
        self.assertEqual(window._frame_ready.results[-1].state, TrackState.SEARCHING)

    def test_start_navigation_applies_user_preference_when_flow_enabled(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.PAUSED,
            locked=False,
            preferred_locked=True,
        )

        with patch("config.WINDOW_LOCK_FOLLOWS_GUIDE", True, create=True):
            window.tracking_controller.start_navigation()

        self.assertEqual(window._mode, WindowMode.TRACKING_STABLE)
        self.assertTrue(window._locked)
        self.assertEqual(window.lock_changes[-1], True)

    def test_pure_navigation_hides_chrome_in_stable_modes(self) -> None:
        window = _PureWindow(WindowMode.TRACKING_STABLE, pure=True)

        window._apply_pure_navigation_ui()

        self.assertFalse(window.title_drag_area.isVisible())
        self.assertFalse(window.settings_btn.isVisible())
        self.assertFalse(window.terminate_nav_btn.isVisible())
        self.assertFalse(window.lock_btn.isVisible())
        self.assertTrue(window.tracked_routes_card.isVisible())
        self.assertFalse(window.sidebar_shell.isVisible())
        self.assertEqual(window.cleared_hint, 0)
        self.assertEqual(window.root_layout.margins, (8, 8, 8, 8))
        self.assertEqual(window.root_layout.spacing, 0)
        self.assertEqual(window.map_layout.spacing, 0)

    def test_route_guide_hint_reserves_clear_progress_button_width(self) -> None:
        without_clear = _HintWindow(clear_visible=False)
        without_clear._fit_route_guide_hint_width()

        with_clear = _HintWindow(clear_visible=True)
        with_clear._fit_route_guide_hint_width()

        self.assertIsNotNone(without_clear.tracked_guide_hint_label.maximum_width)
        self.assertEqual(
            with_clear.tracked_guide_hint_label.maximum_width,
            without_clear.tracked_guide_hint_label.maximum_width - 34,
        )

    def test_pure_navigation_does_not_apply_to_lost_or_paused_modes(self) -> None:
        lost = _PureWindow(WindowMode.TRACKING_LOST, pure=True)
        lost._apply_pure_navigation_ui()

        self.assertTrue(lost.title_drag_area.isVisible())
        self.assertTrue(lost.settings_btn.isVisible())
        self.assertFalse(lost.tracked_routes_card.isVisible())
        self.assertEqual(lost.root_layout.margins, (12, 8, 12, 10))

        paused = _PureWindow(WindowMode.PAUSED, pure=True)
        paused._apply_pure_navigation_ui()

        self.assertTrue(paused.title_drag_area.isVisible())
        self.assertTrue(paused.tracked_routes_card.isVisible())
        self.assertTrue(paused.relocate_btn.isVisible())
        self.assertFalse(paused.sidebar_toggle_btn.isVisible())
        self.assertFalse(paused.terminate_nav_btn.isVisible())
        self.assertTrue(paused.lock_btn.isVisible())
        self.assertEqual(paused.window_mode_controller.sidebar_applied, 1)

    def test_start_navigation_keeps_unlocked_preference(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.PAUSED,
            locked=False,
            preferred_locked=False,
        )

        window.tracking_controller.start_navigation()

        self.assertEqual(window._mode, WindowMode.TRACKING_STABLE)
        self.assertFalse(window._locked)
        self.assertNotIn(True, window.lock_changes)

    def test_non_tracking_modes_can_toggle_lock_freely(self) -> None:
        for mode in (WindowMode.PAUSED, WindowMode.MAXIMIZED, WindowMode.TRACKING_LOST):
            with self.subTest(mode=mode):
                unlocked = _FakeWindow(mode=mode, locked=False, preferred_locked=False)
                self.assertTrue(unlocked._can_toggle_lock())
                unlocked.toggle_lock()
                self.assertTrue(unlocked._locked)
                self.assertTrue(unlocked._preferred_locked)
                self.assertEqual(unlocked.lock_changes, [True])

                locked = _FakeWindow(mode=mode, locked=True, preferred_locked=True)
                self.assertTrue(locked._can_toggle_lock())
                locked.toggle_lock()
                self.assertFalse(locked._locked)
                self.assertFalse(locked._preferred_locked)
                self.assertEqual(locked.lock_changes, [False])


if __name__ == "__main__":
    unittest.main()

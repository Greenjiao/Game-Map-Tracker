import unittest
from types import SimpleNamespace

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

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def setStyleSheet(self, _style: str) -> None:
        pass


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


class TrackingLockStateTests(unittest.TestCase):
    def test_lost_mode_keeps_locked_state(self) -> None:
        window = _FakeWindow(
            mode=WindowMode.TRACKING_STABLE,
            locked=True,
            preferred_locked=True,
        )

        window.tracking_controller.enter_lost_mode()
        self.assertEqual(window._mode, WindowMode.TRACKING_LOST)
        self.assertTrue(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertTrue(window._lock_state_before_lost)
        self.assertNotIn(False, window.lock_changes)

        window.tracking_controller.pause_navigation()
        self.assertEqual(window._mode, WindowMode.PAUSED)
        self.assertTrue(window._locked)
        self.assertTrue(window._preferred_locked)
        self.assertIsNone(window._lock_state_before_lost)

        window.tracking_controller.apply_state_feedback(TrackState.SEARCHING)
        self.assertTrue(window._locked)
        self.assertIsNone(window._lock_state_before_lost)
        self.assertNotIn(False, window.lock_changes)

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

        window.tracking_controller.start_navigation()

        self.assertEqual(window._mode, WindowMode.TRACKING_STABLE)
        self.assertTrue(window._locked)
        self.assertEqual(window.lock_changes[-1], True)
        self.assertEqual(window._frame_ready.results[-1].state, TrackState.SEARCHING)

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

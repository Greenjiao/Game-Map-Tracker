import unittest
from collections import deque
from enum import Enum
from types import SimpleNamespace

from ui_island.app.window import IslandWindow
from ui_island.state.models import TrackingState
from ui_island.state.tracking import TrackResult, TrackState


class _Mode(Enum):
    PAUSED = "paused"
    TRACKING_STABLE = "tracking_stable"
    TRACKING_INERTIAL = "tracking_inertial"
    TRACKING_LOST = "tracking_lost"
    MAXIMIZED = "maximized"


class _Dot:
    def __init__(self) -> None:
        self.states: list[TrackState] = []

    def set_state(self, state: TrackState) -> None:
        self.states.append(state)


class _Label:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def setText(self, text: str) -> None:
        self.texts.append(text)


class _MapView:
    def __init__(self) -> None:
        self.update_calls: list[dict] = []
        self.lock_calls: list[bool] = []

    def set_center_locked(self, locked: bool) -> None:
        self.lock_calls.append(bool(locked))

    def update_frame(
        self,
        state: TrackState,
        x: int,
        y: int,
        minimap=None,
        *,
        auto_visit: bool = True,
        snap_center: bool = False,
    ) -> None:
        self.update_calls.append(
            {
                "state": state,
                "x": x,
                "y": y,
                "minimap": minimap,
                "auto_visit": auto_visit,
                "snap_center": snap_center,
            }
        )


class _TrackingController:
    def __init__(self) -> None:
        self.states: list[TrackState] = []
        self.cleared_anchor = False

    def apply_state_feedback(self, state: TrackState) -> None:
        self.states.append(state)

    def clear_tracker_anchor(self) -> None:
        self.cleared_anchor = True


class _RoutePanelController:
    def __init__(self) -> None:
        self.signatures: list[tuple] = [()]
        self.refresh_count = 0

    def build_tracked_route_progress_signature(self):
        return self.signatures[-1]

    def refresh_tracked_routes(self) -> None:
        self.refresh_count += 1


class _FakeWindow:
    _AUTO_RECENTER_MOVE_THRESHOLD = IslandWindow._AUTO_RECENTER_MOVE_THRESHOLD
    _DISPLAY_LOCK_CONFIRM_FRAMES = IslandWindow._DISPLAY_LOCK_CONFIRM_FRAMES
    _DISPLAY_LOCK_CONFIRM_DISTANCE = IslandWindow._DISPLAY_LOCK_CONFIRM_DISTANCE

    _display_result_for_frame = IslandWindow._display_result_for_frame
    _on_frame = IslandWindow._on_frame

    def __init__(self) -> None:
        self.tracking_state = TrackingState()
        self.tracking_state.latencies = deque(maxlen=30)
        self._latencies = self.tracking_state.latencies
        self._last_player_xy = None
        self._last_result = None
        self._jump_anomaly_count = 0
        self._tracking_attempts_paused = False
        self._latest_minimap = object()
        self._tracked_route_progress_signature = ()
        self._mini_icon = None
        self._mode = _Mode.TRACKING_STABLE
        self.dot = _Dot()
        self.coord_label = _Label()
        self.stat_label = _Label()
        self.map_view = _MapView()
        self.tracking_controller = _TrackingController()
        self.route_panel_controller = _RoutePanelController()
        self.tracker = SimpleNamespace()

    def isMaximized(self) -> bool:
        return False


class TrackingDisplayStabilizerTests(unittest.TestCase):
    def test_inertial_freezes_last_stable_position_and_disables_auto_visit(self) -> None:
        window = _FakeWindow()
        window._on_frame(TrackResult(TrackState.LOCKED, 100, 100, latency_ms=10.0))

        window._on_frame(TrackResult(TrackState.INERTIAL, 160, 170, latency_ms=10.0))

        self.assertEqual(window.coord_label.texts[-1], "100 , 100")
        self.assertEqual(window._last_player_xy, (100, 100))
        self.assertEqual(window.map_view.update_calls[-1]["state"], TrackState.INERTIAL)
        self.assertEqual((window.map_view.update_calls[-1]["x"], window.map_view.update_calls[-1]["y"]), (100, 100))
        self.assertFalse(window.map_view.update_calls[-1]["auto_visit"])
        self.assertFalse(window.map_view.update_calls[-1]["snap_center"])
        self.assertEqual(window.tracking_controller.states[-1], TrackState.INERTIAL)

    def test_recovered_lock_waits_for_two_close_frames_then_snaps(self) -> None:
        window = _FakeWindow()
        window._on_frame(TrackResult(TrackState.LOCKED, 100, 100, latency_ms=10.0))
        window._on_frame(TrackResult(TrackState.INERTIAL, 140, 145, latency_ms=10.0))

        window._on_frame(TrackResult(TrackState.LOCKED, 300, 300, latency_ms=10.0))
        first_recovery_call = window.map_view.update_calls[-1]
        self.assertEqual(window.coord_label.texts[-1], "100 , 100")
        self.assertEqual(first_recovery_call["state"], TrackState.INERTIAL)
        self.assertFalse(first_recovery_call["auto_visit"])
        self.assertFalse(first_recovery_call["snap_center"])
        self.assertEqual(window._last_player_xy, (100, 100))
        self.assertEqual(window.tracking_controller.states[-1], TrackState.INERTIAL)

        window._on_frame(TrackResult(TrackState.LOCKED, 304, 302, latency_ms=10.0))
        confirmed_call = window.map_view.update_calls[-1]
        self.assertEqual(window.coord_label.texts[-1], "304 , 302")
        self.assertEqual(confirmed_call["state"], TrackState.LOCKED)
        self.assertTrue(confirmed_call["auto_visit"])
        self.assertTrue(confirmed_call["snap_center"])
        self.assertEqual(window._last_player_xy, (304, 302))
        self.assertEqual(window.tracking_state.display_stable_xy, (304, 302))
        self.assertEqual(window.tracking_controller.states[-1], TrackState.LOCKED)

    def test_unrelated_locked_frames_accept_without_confirmation(self) -> None:
        window = _FakeWindow()
        window._on_frame(TrackResult(TrackState.LOCKED, 100, 100, latency_ms=10.0))
        window._on_frame(TrackResult(TrackState.LOCKED, 104, 105, latency_ms=10.0))

        self.assertEqual(window.coord_label.texts[-1], "104 , 105")
        self.assertEqual(window._last_player_xy, (104, 105))
        self.assertEqual(window.map_view.update_calls[-1]["state"], TrackState.LOCKED)
        self.assertTrue(window.map_view.update_calls[-1]["auto_visit"])
        self.assertFalse(window.map_view.update_calls[-1]["snap_center"])

    def test_recovered_lock_after_lost_also_requires_confirmation(self) -> None:
        window = _FakeWindow()
        window._on_frame(TrackResult(TrackState.LOCKED, 100, 100, latency_ms=10.0))
        window._on_frame(TrackResult(TrackState.LOST, latency_ms=10.0))

        window._on_frame(TrackResult(TrackState.LOCKED, 500, 500, latency_ms=10.0))

        self.assertEqual(window.coord_label.texts[-1], "100 , 100")
        self.assertEqual(window.map_view.update_calls[-1]["state"], TrackState.INERTIAL)
        self.assertFalse(window.map_view.update_calls[-1]["auto_visit"])
        self.assertEqual(window.tracking_controller.states[-1], TrackState.INERTIAL)


if __name__ == "__main__":
    unittest.main()

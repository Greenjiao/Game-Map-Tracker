import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from ui_island.state.tracking import TrackState
from ui_island.views.map_view import MapView


class _RecordingRouteManager:
    def __init__(self) -> None:
        self.draw_calls: list[dict] = []

    def draw_on(self, canvas, vx1, vy1, view_size, player_x=None, player_y=None, **kwargs) -> None:
        self.draw_calls.append(
            {
                "shape": canvas.shape,
                "vx1": vx1,
                "vy1": vy1,
                "view_size": view_size,
                "player_x": player_x,
                "player_y": player_y,
                **kwargs,
            }
        )

    def guide_hint_for_view(self, *_args, **_kwargs):
        return None


class MapViewRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_full_map_zoom_renders_to_widget_sized_canvas(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.resize(200, 100)
        view.set_map(np.zeros((800, 800, 3), dtype=np.uint8))
        view._zoom = view._min_zoom_for_full_map()
        view._view_center = QPointF(400, 400)

        view.update_frame(TrackState.LOCKED, 400, 400)

        self.assertEqual(len(route_mgr.draw_calls), 1)
        call = route_mgr.draw_calls[0]
        self.assertLessEqual(call["shape"][1], view.width())
        self.assertLessEqual(call["shape"][0], view.height())
        self.assertEqual(call["viewport_width"], 800)
        self.assertEqual(call["viewport_height"], 800)
        self.assertGreaterEqual(call["map_pixels_per_screen_px"], 4.0)

    def test_mipmap_selection_prefers_half_resolution_for_far_zoom(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.resize(200, 200)
        base = np.zeros((1024, 1024, 3), dtype=np.uint8)
        view.set_map(base)

        divisor, image = view._mipmap_for_ratio(2.2)

        self.assertEqual(divisor, 2)
        self.assertEqual(image.shape[:2], (512, 512))

    def test_mipmap_selection_keeps_base_for_near_zoom(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.set_map(np.zeros((1024, 1024, 3), dtype=np.uint8))

        divisor, image = view._mipmap_for_ratio(1.4)

        self.assertEqual(divisor, 1)
        self.assertEqual(image.shape[:2], (1024, 1024))

    def test_update_frame_can_disable_auto_visit_and_preserves_it_on_refresh(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.resize(200, 200)
        view.set_map(np.zeros((800, 800, 3), dtype=np.uint8))

        view.update_frame(TrackState.INERTIAL, 400, 400, auto_visit=False)
        view._refresh_from_last_frame()

        self.assertEqual(len(route_mgr.draw_calls), 2)
        self.assertFalse(route_mgr.draw_calls[0]["auto_visit"])
        self.assertFalse(route_mgr.draw_calls[1]["auto_visit"])

    def test_snap_center_bypasses_smoothing_and_jump_damping(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.resize(200, 200)
        view.set_map(np.zeros((1000, 1000, 3), dtype=np.uint8))
        view._view_center = QPointF(100, 100)

        view.update_frame(TrackState.LOCKED, 500, 500, snap_center=True)

        self.assertEqual(view._view_center, QPointF(500, 500))

    def test_locked_large_jump_without_snap_is_damped(self) -> None:
        route_mgr = _RecordingRouteManager()
        view = MapView(route_mgr)
        view.resize(200, 200)
        view.set_map(np.zeros((1000, 1000, 3), dtype=np.uint8))
        view._view_center = QPointF(100, 100)

        view.update_frame(TrackState.LOCKED, 900, 900)

        self.assertNotEqual(view._view_center, QPointF(900, 900))


if __name__ == "__main__":
    unittest.main()

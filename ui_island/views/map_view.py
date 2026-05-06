"""Interactive local map panel with pan/zoom support."""
from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ui_island.services.route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL, RouteManager
from ui_island.state.tracking import TrackState
from ui_island.views.map_coordinates import MapCoordinateAdapter

from ..design import strings
from ..widgets.context_menu import ContextMenuItem, show_context_menu

_HIT_RADIUS_WIDGET_PX = 8


class MapView(QWidget):
    """Interactive crop of the big map with player marker and routes."""

    relocate_requested = Signal(int, int)
    manual_view_changed = Signal()
    add_point_requested = Signal(int, int)
    add_route_node_requested = Signal(int, int, object)
    add_annotation_requested = Signal(int, int)
    add_annotated_point_requested = Signal(int, int)
    delete_point_requested = Signal(str, int)
    mark_point_visited_requested = Signal(str, int, bool)
    change_point_annotation_requested = Signal(str, int)
    delete_point_annotation_requested = Signal(str, int)
    change_point_node_type_requested = Signal(str, int, object)
    change_point_order_requested = Signal(str, int)
    change_annotation_requested = Signal(str, int)
    add_annotation_to_route_requested = Signal(str, int)
    delete_annotation_requested = Signal(str, int)
    guide_hint_changed = Signal(object)
    drawing_point_requested = Signal(int, int)
    drawing_point_move_requested = Signal(int, int, int)
    drawing_point_move_finished = Signal(int, int, int, int, int)
    drawing_undo_requested = Signal()
    route_point_move_requested = Signal(str, int, int, int)
    route_point_move_finished = Signal(str, int, int, int, int, int)
    route_point_move_undo_requested = Signal()
    route_calibration_drag_delta_requested = Signal(float, float)

    _ABSOLUTE_MIN_ZOOM = 0.05
    _MAX_ZOOM = 3.5
    _ZOOM_STEP = 1.18

    # 视图中心平滑追踪：防止 tracker 不稳定时地图视图大幅跳动
    _VIEW_SMOOTH_ALPHA_LOCKED = 0.5      # LOCKED 时跟随响应快
    _VIEW_SMOOTH_ALPHA_INERTIAL = 0.15   # INERTIAL 时跟随更慢，防止预测位置抖动传到视图
    _VIEW_JUMP_DAMP_THRESHOLD = 80       # 单帧最大移动像素 — 超过此值会被限速

    def __init__(self, route_mgr: RouteManager, parent=None) -> None:
        super().__init__(parent)
        self.route_mgr = route_mgr
        self._coord_adapter = MapCoordinateAdapter.for_current_config()
        self._pixmap: QPixmap | None = None
        self._base_map: np.ndarray | None = None
        self._mipmaps: list[tuple[int, np.ndarray]] = []
        self._map_w = 0
        self._map_h = 0
        self._last_vx1 = 0
        self._last_vy1 = 0
        self._last_crop_size = (0, 0)
        self._last_draw_rect = QRectF()
        self._zoom = 1.0
        self._center_locked = True
        self._view_center: QPointF | None = None
        self._drag_last_pos: QPointF | None = None
        self._left_press_pos: QPointF | None = None
        self._left_press_map: tuple[float, float] | None = None
        self._left_dragging = False
        self._hover_map_pos: tuple[float, float] | None = None
        self._drawing_context: dict | None = None
        self._route_calibration_context: dict | None = None
        self._route_calibration_drag_last_map: tuple[float, float] | None = None
        self._drawing_drag_index: int | None = None
        self._drawing_drag_start_map: tuple[int, int] | None = None
        self._drawing_drag_current_map: tuple[int, int] | None = None
        self._route_point_drag_enabled = False
        self._route_point_move_undo_available = False
        self._route_point_drag_route_id: str | None = None
        self._route_point_drag_index: int | None = None
        self._route_point_drag_start_map: tuple[int, int] | None = None
        self._route_point_drag_current_map: tuple[int, int] | None = None
        self._last_player: tuple[int, int] | None = None
        self._last_state: TrackState | None = None
        self._last_auto_visit = True
        self._last_minimap: np.ndarray | None = None
        self._missing_map_notice_visible = False
        self._ARROW_HALF = 16   # 从小地图中心裁取 ±16px 的箭头区域
        self._arrow_alpha = self._build_arrow_alpha(self._ARROW_HALF)
        self.setMinimumSize(260, 60)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_map(self, base_map_bgr: np.ndarray) -> None:
        self._base_map = base_map_bgr
        self._mipmaps = [(1, base_map_bgr)]
        self._map_h, self._map_w = base_map_bgr.shape[:2]

    def set_missing_map_notice_visible(self, visible: bool) -> None:
        self._missing_map_notice_visible = bool(visible)
        self.update()

    def set_coordinate_adapter(self, adapter: MapCoordinateAdapter | None) -> None:
        self._coord_adapter = adapter or MapCoordinateAdapter.for_current_config()
        self._refresh_from_last_frame()

    def coordinate_adapter(self) -> MapCoordinateAdapter:
        return self._coord_adapter

    def set_center_locked(self, locked: bool) -> None:
        self._center_locked = locked
        if locked and self._last_player is not None:
            self._view_center = QPointF(float(self._last_player[0]), float(self._last_player[1]))
            self._refresh_from_last_frame()

    def set_route_point_drag_enabled(self, enabled: bool) -> None:
        self._route_point_drag_enabled = bool(enabled)
        if not self._route_point_drag_enabled:
            self._reset_route_point_drag()

    def set_route_point_move_undo_available(self, available: bool) -> None:
        self._route_point_move_undo_available = bool(available)

    def reset_view(self) -> None:
        self._zoom = 1.0
        self.set_center_locked(True)
        self._refresh_from_last_frame()

    def preview_relocate(self, x: int, y: int, state: TrackState, auto_visit: bool = False) -> None:
        self._last_player = (x, y)
        self._last_state = state
        self._last_auto_visit = bool(auto_visit)
        self._zoom = max(self._zoom, self._min_zoom_for_full_map())
        self._center_locked = True
        self._view_center = QPointF(float(x), float(y))
        self._render_frame(state, x, y, auto_visit=auto_visit)

    def focus_map_position(self, x: int, y: int) -> None:
        self._center_locked = False
        map_x, map_y = self._coord_adapter.to_current(float(x), float(y))
        self._view_center = QPointF(map_x, map_y)
        self._refresh_from_last_frame()

    def update_frame(
        self,
        state: TrackState,
        cx: int | None,
        cy: int | None,
        minimap_bgr: np.ndarray | None = None,
        *,
        auto_visit: bool = True,
        snap_center: bool = False,
    ) -> None:
        if self._base_map is None or cx is None or cy is None:
            return

        self._last_state = state
        self._last_player = (cx, cy)
        self._last_auto_visit = bool(auto_visit)
        if minimap_bgr is not None:
            self._last_minimap = minimap_bgr
        if self._center_locked or self._view_center is None:
            target_x = float(cx)
            target_y = float(cy)
            if snap_center or self._view_center is None:
                # 首次定位 — 直接设置，不需要逐渐拉到位
                self._view_center = QPointF(target_x, target_y)
            else:
                # 视图中心平滑追踪：EMA + 大跳阻尼
                cur_x = self._view_center.x()
                cur_y = self._view_center.y()
                dx = target_x - cur_x
                dy = target_y - cur_y
                dist = math.hypot(dx, dy)
                if dist > self._VIEW_JUMP_DAMP_THRESHOLD:
                    # 大跳：限速到阈值距离（防 anchor 重置/误判时视图甩飞）
                    scale = self._VIEW_JUMP_DAMP_THRESHOLD / dist
                    new_x = cur_x + dx * scale
                    new_y = cur_y + dy * scale
                else:
                    alpha = (
                        self._VIEW_SMOOTH_ALPHA_INERTIAL
                        if state == TrackState.INERTIAL
                        else self._VIEW_SMOOTH_ALPHA_LOCKED
                    )
                    new_x = cur_x + dx * alpha
                    new_y = cur_y + dy * alpha
                self._view_center = QPointF(new_x, new_y)

        self._render_frame(state, cx, cy, auto_visit=auto_visit)

    def _render_frame(self, state: TrackState, cx: int, cy: int, auto_visit: bool = True) -> None:
        if self._base_map is None or self._view_center is None:
            return

        crop_w, crop_h = self._crop_dimensions()
        vx1, vy1, vx2, vy2 = self._crop_bounds(crop_w, crop_h)
        viewport_w = max(1, vx2 - vx1)
        viewport_h = max(1, vy2 - vy1)
        render_w, render_h = self._render_dimensions(viewport_w, viewport_h)
        if render_w <= 0 or render_h <= 0:
            return
        map_pixels_per_screen_px = max(
            viewport_w / max(render_w, 1),
            viewport_h / max(render_h, 1),
        )
        mip_divisor, mipmap = self._mipmap_for_ratio(map_pixels_per_screen_px)
        mx1 = max(0, min(mipmap.shape[1] - 1, int(math.floor(vx1 / mip_divisor))))
        my1 = max(0, min(mipmap.shape[0] - 1, int(math.floor(vy1 / mip_divisor))))
        mx2 = max(mx1 + 1, min(mipmap.shape[1], int(math.ceil(vx2 / mip_divisor))))
        my2 = max(my1 + 1, min(mipmap.shape[0], int(math.ceil(vy2 / mip_divisor))))
        crop = cv2.resize(
            mipmap[my1:my2, mx1:mx2],
            (render_w, render_h),
            interpolation=cv2.INTER_AREA if map_pixels_per_screen_px >= 1.0 else cv2.INTER_LINEAR,
        )

        self._last_vx1, self._last_vy1 = vx1, vy1
        self._last_crop_size = (viewport_w, viewport_h)
        draw_x = (self.width() - render_w) / 2.0
        draw_y = (self.height() - render_h) / 2.0
        self._last_draw_rect = QRectF(draw_x, draw_y, float(render_w), float(render_h))

        drawing_route = self._drawing_route_payload()
        calibration_route = self._route_calibration_payload()
        overlay_route = drawing_route if drawing_route is not None else calibration_route
        overlay_active = overlay_route is not None
        annotation_calibration_active = bool(
            self._is_route_calibration_active()
            and isinstance(self._route_calibration_context, dict)
            and self._route_calibration_context.get("target_type") == "annotation"
        )
        drawing_active = drawing_route is not None
        draw_player_x = None if overlay_active else cx
        draw_player_y = None if overlay_active else cy
        scale_x = render_w / float(viewport_w)
        scale_y = render_h / float(viewport_h)
        self.route_mgr.draw_on(
            crop,
            vx1,
            vy1,
            max(crop_w, crop_h),
            draw_player_x,
            draw_player_y,
            drawing_route=overlay_route,
            auto_visit=auto_visit,
            coord_adapter=self._coord_adapter,
            viewport_width=viewport_w,
            viewport_height=viewport_h,
            scale_x=scale_x,
            scale_y=scale_y,
            map_pixels_per_screen_px=map_pixels_per_screen_px,
            skip_annotations=annotation_calibration_active,
        )
        if overlay_active:
            self.guide_hint_changed.emit(None)
        else:
            self.guide_hint_changed.emit(
                self.route_mgr.guide_hint_for_view(
                    cx,
                    cy,
                    vx1,
                    vy1,
                    viewport_w,
                    viewport_h,
                    coord_adapter=self._coord_adapter,
                )
            )

        local_x = int(round((cx - vx1) * scale_x))
        local_y = int(round((cy - vy1) * scale_y))
        if not overlay_active and 0 <= local_x < crop.shape[1] and 0 <= local_y < crop.shape[0]:
            if state == TrackState.INERTIAL:
                # 惯性态无新截图：黄圈降级显示
                cv2.circle(crop, (local_x, local_y), 10, (0, 255, 255), -1)
                cv2.circle(crop, (local_x, local_y), 12, (0, 150, 150), 2)
            else:
                # 精确锁定 / 搜索态：贴游戏原生箭头
                self._paste_minimap_arrow(crop, local_x, local_y)

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        height, width, _ = rgb.shape
        image = QImage(rgb.data, width, height, width * 3, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def _render_dimensions(self, viewport_w: int, viewport_h: int) -> tuple[int, int]:
        widget_w = max(1, self.width())
        widget_h = max(1, self.height())
        if viewport_w <= 0 or viewport_h <= 0:
            return widget_w, widget_h
        scale = min(widget_w / float(viewport_w), widget_h / float(viewport_h))
        return max(1, int(round(viewport_w * scale))), max(1, int(round(viewport_h * scale)))

    def _mipmap_for_ratio(self, map_pixels_per_screen_px: float) -> tuple[int, np.ndarray]:
        if self._base_map is None:
            raise RuntimeError("base map is not set")
        if not self._mipmaps:
            self._mipmaps = [(1, self._base_map)]

        target_divisor = 1
        while (
            target_divisor * 2 <= max(1.0, float(map_pixels_per_screen_px))
            and min(self._mipmaps[-1][1].shape[:2]) > 512
        ):
            target_divisor *= 2
            if self._mipmaps[-1][0] >= target_divisor:
                continue
            previous_divisor, previous = self._mipmaps[-1]
            if previous_divisor * 2 != target_divisor:
                break
            next_map = cv2.resize(
                previous,
                (max(1, previous.shape[1] // 2), max(1, previous.shape[0] // 2)),
                interpolation=cv2.INTER_AREA,
            )
            self._mipmaps.append((target_divisor, next_map))

        chosen = self._mipmaps[0]
        for divisor, image in self._mipmaps:
            if divisor <= max(1.0, float(map_pixels_per_screen_px)):
                chosen = (divisor, image)
            else:
                break
        return chosen

    def _crop_dimensions(self) -> tuple[int, int]:
        view_w = max(self.width(), 100)
        view_h = max(self.height(), 100)
        self._zoom = min(self._MAX_ZOOM, max(self._min_zoom_for_full_map(), self._zoom))
        crop_w = max(120, int(view_w / self._zoom))
        crop_h = max(120, int(view_h / self._zoom))
        return crop_w, crop_h

    def _min_zoom_for_full_map(self) -> float:
        if self._map_w <= 0 or self._map_h <= 0:
            return self._ABSOLUTE_MIN_ZOOM
        view_w = max(self.width(), 100)
        view_h = max(self.height(), 100)
        return max(
            self._ABSOLUTE_MIN_ZOOM,
            min(view_w / self._map_w, view_h / self._map_h),
        )

    def _crop_bounds(self, crop_w: int, crop_h: int) -> tuple[int, int, int, int]:
        assert self._view_center is not None

        center_x = self._view_center.x()
        center_y = self._view_center.y()
        half_w = crop_w / 2.0
        half_h = crop_h / 2.0

        max_vx1 = max(0, self._map_w - crop_w)
        max_vy1 = max(0, self._map_h - crop_h)
        vx1 = int(round(min(max(center_x - half_w, 0), max_vx1)))
        vy1 = int(round(min(max(center_y - half_h, 0), max_vy1)))
        vx2 = min(self._map_w, vx1 + crop_w)
        vy2 = min(self._map_h, vy1 + crop_h)

        self._view_center = QPointF(vx1 + (vx2 - vx1) / 2.0, vy1 + (vy2 - vy1) / 2.0)
        return vx1, vy1, vx2, vy2

    def _paste_minimap_arrow(self, crop: np.ndarray, local_x: int, local_y: int) -> None:
        """用径向正弦 alpha 遮罩把游戏小地图中央箭头贴到玩家位置，消除矩形硬边。"""
        half = self._ARROW_HALF
        if self._last_minimap is not None:
            mini = self._last_minimap
            mh, mw = mini.shape[:2]
            my1, my2 = mh // 2 - half, mh // 2 + half
            mx1, mx2 = mw // 2 - half, mw // 2 + half
            if my1 >= 0 and mx1 >= 0 and my2 <= mh and mx2 <= mw:
                arrow = mini[my1:my2, mx1:mx2]
                ay1, ax1 = local_y - half, local_x - half
                ay2, ax2 = ay1 + 2 * half, ax1 + 2 * half
                if ay1 >= 0 and ax1 >= 0 and ay2 <= crop.shape[0] and ax2 <= crop.shape[1]:
                    roi = crop[ay1:ay2, ax1:ax2]
                    alpha = self._arrow_alpha
                    blended = arrow.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
                    crop[ay1:ay2, ax1:ax2] = np.clip(blended, 0, 255).astype(np.uint8)
                    return
        # 降级：小地图不可用时画红圈
        cv2.circle(crop, (local_x, local_y), 8, (0, 0, 255), -1)
        cv2.circle(crop, (local_x, local_y), 10, (255, 255, 255), 2)

    @staticmethod
    def _build_arrow_alpha(half: int) -> np.ndarray:
        """(2*half, 2*half, 1) float32：内 55% 全覆盖，外圈 sin² 柔化到 0。"""
        size = 2 * half
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        cx = cy = half - 0.5
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        inner = half * 0.55
        t = np.clip((half - dist) / max(half - inner, 1e-6), 0.0, 1.0)
        alpha = np.where(dist <= inner, 1.0, np.sin(t * np.pi / 2.0) ** 2)
        return alpha.astype(np.float32)[..., None]

    def _refresh_from_last_frame(self) -> None:
        if self._last_state is None or self._last_player is None:
            return
        self._render_frame(
            self._last_state,
            self._last_player[0],
            self._last_player[1],
            auto_visit=self._last_auto_visit,
        )

    def _draw_rect(self) -> QRectF:
        if self._pixmap is None:
            return QRectF()
        x = (self.width() - self._pixmap.width()) / 2.0
        y = (self.height() - self._pixmap.height()) / 2.0
        return QRectF(x, y, float(self._pixmap.width()), float(self._pixmap.height()))

    def _widget_to_map(self, pos: QPointF) -> tuple[float, float] | None:
        if self._pixmap is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if not draw_rect.contains(pos):
            return None

        crop_w, crop_h = self._last_crop_size
        if crop_w <= 0 or crop_h <= 0:
            return None

        rel_x = (pos.x() - draw_rect.left()) / draw_rect.width()
        rel_y = (pos.y() - draw_rect.top()) / draw_rect.height()
        map_x = self._last_vx1 + rel_x * crop_w
        map_y = self._last_vy1 + rel_y * crop_h
        return map_x, map_y

    def _map_to_widget(self, map_x: float, map_y: float) -> QPointF | None:
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        crop_w, crop_h = self._last_crop_size
        if draw_rect.width() <= 0 or draw_rect.height() <= 0 or crop_w <= 0 or crop_h <= 0:
            return None
        rel_x = (map_x - self._last_vx1) / crop_w
        rel_y = (map_y - self._last_vy1) / crop_h
        return QPointF(
            draw_rect.left() + rel_x * draw_rect.width(),
            draw_rect.top() + rel_y * draw_rect.height(),
        )

    def _widget_to_internal_map(self, pos: QPointF) -> tuple[float, float] | None:
        mapped = self._widget_to_map(pos)
        if mapped is None:
            return None
        return self._coord_adapter.to_internal(mapped[0], mapped[1])

    def _internal_map_to_widget(self, map_x: float, map_y: float) -> QPointF | None:
        current_x, current_y = self._coord_adapter.to_current(map_x, map_y)
        return self._map_to_widget(current_x, current_y)

    def set_route_drawing_context(self, context: dict | None) -> None:
        self._drawing_context = dict(context) if isinstance(context, dict) else None
        if not self._is_drawing_active() or self._is_drawing_paused():
            self._reset_drawing_node_drag()
        if self._is_drawing_active():
            self._reset_route_point_drag()
        self._refresh_from_last_frame()

    def set_route_calibration_context(self, context: dict | None) -> None:
        previous_key = (
            self._route_calibration_context_key(self._route_calibration_context)
            if isinstance(self._route_calibration_context, dict)
            else ""
        )
        next_context = dict(context) if isinstance(context, dict) and context.get("active") else None
        next_key = self._route_calibration_context_key(next_context) if isinstance(next_context, dict) else ""
        self._route_calibration_context = next_context
        if next_context is None or next_key != previous_key:
            self._route_calibration_drag_last_map = None
        if self._route_calibration_context is not None:
            self._reset_route_point_drag()
        self._refresh_from_last_frame()

    @staticmethod
    def _route_calibration_context_key(context: dict | None) -> str:
        if not isinstance(context, dict):
            return ""
        target_type = str(context.get("target_type") or "route")
        if target_type == "annotation":
            return f"annotation:{context.get('annotation_path') or ''}"
        return f"route:{context.get('route_id') or ''}"

    def _is_drawing_active(self) -> bool:
        return bool(isinstance(self._drawing_context, dict) and self._drawing_context.get("active"))

    def _is_drawing_paused(self) -> bool:
        return bool(self._is_drawing_active() and self._drawing_context and self._drawing_context.get("paused"))

    def _is_route_calibration_active(self) -> bool:
        return bool(
            isinstance(self._route_calibration_context, dict)
            and self._route_calibration_context.get("active")
        )

    def _reset_drawing_node_drag(self) -> None:
        self._drawing_drag_index = None
        self._drawing_drag_start_map = None
        self._drawing_drag_current_map = None

    def _reset_route_point_drag(self) -> None:
        self._route_point_drag_route_id = None
        self._route_point_drag_index = None
        self._route_point_drag_start_map = None
        self._route_point_drag_current_map = None

    def _route_node_map_pos(self, route_id: str, index: int) -> tuple[int, int] | None:
        route = self.route_mgr.route_for_id(route_id)
        points = route.get("points") if isinstance(route, dict) else None
        if not isinstance(points, list) or not (0 <= index < len(points)):
            return None
        point = points[index]
        if not isinstance(point, dict):
            return None
        try:
            adapter = self._coord_adapter
            adapter_getter = getattr(self.route_mgr, "route_coordinate_adapter", None)
            if callable(adapter_getter):
                adapter = adapter_getter(route_id, self._coord_adapter) or self._coord_adapter
            x, y = adapter.to_current(float(point["x"]), float(point["y"]))
            return int(x), int(y)
        except (KeyError, TypeError, ValueError):
            return None

    def _draft_node_map_pos(self, index: int) -> tuple[int, int] | None:
        context = self._drawing_context if isinstance(self._drawing_context, dict) else None
        points = context.get("points") if context else None
        if not isinstance(points, list) or not (0 <= index < len(points)):
            return None
        point = points[index]
        if not isinstance(point, dict):
            return None
        try:
            route_id = str(context.get("route_id") or "") if context else ""
            adapter = self._coord_adapter
            if route_id:
                adapter_getter = getattr(self.route_mgr, "route_coordinate_adapter", None)
                if callable(adapter_getter):
                    adapter = adapter_getter(route_id, self._coord_adapter) or self._coord_adapter
            x, y = adapter.to_current(float(point["x"]), float(point["y"]))
            return int(x), int(y)
        except (KeyError, TypeError, ValueError):
            return None

    def _drawing_route_payload(self) -> dict | None:
        if not self._is_drawing_active() or not self._drawing_context:
            return None
        return {
            "id": self._drawing_context.get("route_id", ""),
            "display_name": self._drawing_context.get("name", ""),
            "points": self._drawing_context.get("points") or [],
            "loop": bool(self._drawing_context.get("loop")),
            "_hide_other_routes": bool(self._drawing_context.get("hide_other_routes")),
        }

    def _route_calibration_payload(self) -> dict | None:
        if not self._is_route_calibration_active() or not self._route_calibration_context:
            return None
        if self._route_calibration_context.get("target_type") == "annotation":
            points = self._route_calibration_context.get("annotation_points")
            if not isinstance(points, list):
                return None
            transform = self._route_calibration_context.get("coord_transform")
            return {
                "id": "__annotation_calibration__",
                "display_name": self._route_calibration_context.get("name") or "",
                "points": [dict(point) for point in points if isinstance(point, dict)],
                "coord_transform": dict(transform) if isinstance(transform, dict) else {},
                "_hide_other_routes": True,
                "_annotation_calibration": True,
            }
        route = self._route_calibration_context.get("route")
        if not isinstance(route, dict):
            return None
        copied = dict(route)
        transform = self._route_calibration_context.get("coord_transform")
        copied["coord_transform"] = dict(transform) if isinstance(transform, dict) else {}
        copied["_hide_other_routes"] = True
        return copied

    def _route_calibration_widget_bounds(self) -> QRectF | None:
        route = self._route_calibration_payload()
        if route is None:
            return None
        adapter = MapCoordinateAdapter.from_dict(route.get("coord_transform"))
        points: list[QPointF] = []
        for point in route.get("points") or []:
            if not isinstance(point, dict):
                continue
            try:
                x, y = adapter.to_current(float(point["x"]), float(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            widget_pos = self._map_to_widget(x, y)
            if widget_pos is not None:
                points.append(widget_pos)
        if not points:
            return None
        left = min(point.x() for point in points)
        right = max(point.x() for point in points)
        top = min(point.y() for point in points)
        bottom = max(point.y() for point in points)
        padding = 18.0
        return QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top)).adjusted(
            -padding,
            -padding,
            padding,
            padding,
        )

    def _route_calibration_hit(self, widget_pos: QPointF) -> bool:
        bounds = self._route_calibration_widget_bounds()
        return bool(bounds is not None and bounds.contains(widget_pos))

    def _draw_route_calibration_highlight(self, painter: QPainter) -> None:
        bounds = self._route_calibration_widget_bounds()
        if bounds is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(26, 210, 255, 42))
        painter.setPen(QPen(QColor(150, 235, 255, 210), 2))
        painter.drawRoundedRect(bounds, 12, 12)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.drawRoundedRect(bounds.adjusted(3, 3, -3, -3), 9, 9)
        painter.restore()

    def _draw_drawing_preview(self, painter: QPainter) -> None:
        if (
            not self._is_drawing_active()
            or self._is_drawing_paused()
            or self._drawing_drag_index is not None
            or not self._drawing_context
        ):
            return
        points = self._drawing_context.get("points") or []
        if not points or self._hover_map_pos is None:
            return
        last = points[-1]
        if not isinstance(last, dict):
            return
        try:
            start = self._internal_map_to_widget(float(last["x"]), float(last["y"]))
        except (KeyError, TypeError, ValueError):
            return
        end = self._internal_map_to_widget(self._hover_map_pos[0], self._hover_map_pos[1])
        if start is None or end is None:
            return
        node_type = str(self._drawing_context.get("node_type") or NODE_TYPE_COLLECT)
        pen = QPen(QColor(255, 255, 255), 2)
        if node_type == NODE_TYPE_TELEPORT:
            pen.setStyle(Qt.DashLine)
        elif node_type == NODE_TYPE_VIRTUAL:
            pen.setStyle(Qt.DotLine)
        painter.setPen(pen)
        painter.drawLine(start, end)

    def _disable_center_lock(self) -> None:
        if not self._center_locked:
            return
        self._center_locked = False
        self.manual_view_changed.emit()

    def _draw_missing_map_notice(self, painter: QPainter) -> None:
        if not self._missing_map_notice_visible:
            return
        font = QFont(painter.font())
        font.setPointSize(max(22, min(42, int(self.height() * 0.11))))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.rect(), Qt.AlignCenter, strings.MAP_MISSING_BASE_MAP_NOTICE)

    def paintEvent(self, _event):
        painter = QPainter(self)
        if self._pixmap is None:
            self._last_draw_rect = QRectF()
            self._draw_missing_map_notice(painter)
            return

        draw_rect = self._draw_rect()
        self._last_draw_rect = draw_rect
        painter.drawPixmap(int(draw_rect.left()), int(draw_rect.top()), self._pixmap)
        self._draw_route_calibration_highlight(painter)
        self._draw_drawing_preview(painter)
        self._draw_missing_map_notice(painter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._refresh_from_last_frame()

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_Z
            and event.modifiers() & Qt.ControlModifier
        ):
            if self._is_drawing_active():
                self.drawing_undo_requested.emit()
            elif self._route_point_move_undo_available:
                self.route_point_move_undo_requested.emit()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pixmap is not None:
            self.setFocus(Qt.MouseFocusReason)
            if self._is_route_calibration_active() and self._route_calibration_hit(event.position()):
                self._route_calibration_drag_last_map = self._widget_to_map(event.position())
                self._left_press_pos = event.position()
                self._left_press_map = None
                self._left_dragging = False
                self._drag_last_pos = None
                self._disable_center_lock()
                event.accept()
                return
            if self._is_drawing_active() and not self._is_drawing_paused():
                draft_hit = self._hit_test_draft_node(event.position())
                if draft_hit is not None:
                    start_map = self._draft_node_map_pos(draft_hit)
                    if start_map is not None:
                        self._drawing_drag_index = draft_hit
                        self._drawing_drag_start_map = start_map
                        self._drawing_drag_current_map = start_map
                        self._left_press_pos = event.position()
                        self._left_press_map = None
                        self._left_dragging = False
                        self._drag_last_pos = None
                        event.accept()
                        return
            if (
                self._route_point_drag_enabled
                and not self._is_drawing_active()
                and not self._is_route_calibration_active()
            ):
                route_hit = self._hit_test_node(event.position())
                if route_hit is not None:
                    route_id, point_index = route_hit
                    start_map = self._route_node_map_pos(route_id, point_index)
                    if start_map is not None:
                        self._route_point_drag_route_id = route_id
                        self._route_point_drag_index = point_index
                        self._route_point_drag_start_map = start_map
                        self._route_point_drag_current_map = start_map
                        self._left_press_pos = event.position()
                        self._left_press_map = None
                        self._left_dragging = False
                        self._drag_last_pos = None
                        event.accept()
                        return
            self._left_press_pos = event.position()
            self._left_press_map = self._widget_to_map(event.position())
            self._left_dragging = False
            self._drag_last_pos = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._hover_map_pos = self._widget_to_internal_map(event.position())

        if self._route_calibration_drag_last_map is not None:
            if self._left_press_pos is not None and not self._left_dragging:
                delta_from_press = event.position() - self._left_press_pos
                app = QApplication.instance()
                threshold = app.startDragDistance() if app is not None else QApplication.startDragDistance()
                threshold = max(1, int(threshold))
                if max(abs(delta_from_press.x()), abs(delta_from_press.y())) < threshold:
                    event.accept()
                    return
                self._left_dragging = True

            mapped = self._widget_to_map(event.position())
            if mapped is not None:
                last_x, last_y = self._route_calibration_drag_last_map
                dx = mapped[0] - last_x
                dy = mapped[1] - last_y
                if not math.isclose(dx, 0.0) or not math.isclose(dy, 0.0):
                    self._route_calibration_drag_last_map = mapped
                    self.route_calibration_drag_delta_requested.emit(dx, dy)
            event.accept()
            return

        if self._drawing_drag_index is not None:
            if self._left_press_pos is not None and not self._left_dragging:
                delta_from_press = event.position() - self._left_press_pos
                app = QApplication.instance()
                threshold = app.startDragDistance() if app is not None else QApplication.startDragDistance()
                threshold = max(1, int(threshold))
                if max(abs(delta_from_press.x()), abs(delta_from_press.y())) < threshold:
                    event.accept()
                    return
                self._left_dragging = True

            mapped = self._hover_map_pos
            if mapped is not None:
                current = (int(mapped[0]), int(mapped[1]))
                if current != self._drawing_drag_current_map:
                    self._drawing_drag_current_map = current
                    self.drawing_point_move_requested.emit(self._drawing_drag_index, current[0], current[1])
            event.accept()
            return

        if self._route_point_drag_route_id is not None and self._route_point_drag_index is not None:
            if self._left_press_pos is not None and not self._left_dragging:
                delta_from_press = event.position() - self._left_press_pos
                app = QApplication.instance()
                threshold = app.startDragDistance() if app is not None else QApplication.startDragDistance()
                threshold = max(1, int(threshold))
                if max(abs(delta_from_press.x()), abs(delta_from_press.y())) < threshold:
                    event.accept()
                    return
                self._left_dragging = True

            mapped = self._widget_to_map(event.position())
            if mapped is not None:
                current = (int(mapped[0]), int(mapped[1]))
                if current != self._route_point_drag_current_map:
                    self._route_point_drag_current_map = current
                    self.route_point_move_requested.emit(
                        self._route_point_drag_route_id,
                        self._route_point_drag_index,
                        current[0],
                        current[1],
                    )
            event.accept()
            return

        if self._is_drawing_active() and not self._is_drawing_paused():
            self.update()

        if self._drag_last_pos is None or self._view_center is None:
            super().mouseMoveEvent(event)
            return

        if self._left_press_pos is not None and not self._left_dragging:
            delta_from_press = event.position() - self._left_press_pos
            app = QApplication.instance()
            threshold = app.startDragDistance() if app is not None else QApplication.startDragDistance()
            threshold = max(1, int(threshold))
            if max(abs(delta_from_press.x()), abs(delta_from_press.y())) < threshold:
                event.accept()
                return
            self._left_dragging = True

        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        crop_w, crop_h = self._last_crop_size
        if draw_rect.width() <= 0 or draw_rect.height() <= 0 or crop_w <= 0 or crop_h <= 0:
            super().mouseMoveEvent(event)
            return

        delta = event.position() - self._drag_last_pos
        ratio_x = crop_w / draw_rect.width()
        ratio_y = crop_h / draw_rect.height()
        self._view_center = QPointF(
            self._view_center.x() - delta.x() * ratio_x,
            self._view_center.y() - delta.y() * ratio_y,
        )
        self._drag_last_pos = event.position()
        self._disable_center_lock()
        self._refresh_from_last_frame()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._route_calibration_drag_last_map is not None:
                self._route_calibration_drag_last_map = None
                self._drag_last_pos = None
                self._left_press_pos = None
                self._left_press_map = None
                self._left_dragging = False
                event.accept()
                return

            if self._drawing_drag_index is not None:
                index = self._drawing_drag_index
                before = self._drawing_drag_start_map
                after = self._drawing_drag_current_map
                self._reset_drawing_node_drag()
                self._drag_last_pos = None
                self._left_press_pos = None
                self._left_press_map = None
                self._left_dragging = False
                if before is not None and after is not None:
                    self.drawing_point_move_finished.emit(index, before[0], before[1], after[0], after[1])
                event.accept()
                return

            if self._route_point_drag_route_id is not None and self._route_point_drag_index is not None:
                route_id = self._route_point_drag_route_id
                index = self._route_point_drag_index
                before = self._route_point_drag_start_map
                after = self._route_point_drag_current_map
                self._reset_route_point_drag()
                self._drag_last_pos = None
                self._left_press_pos = None
                self._left_press_map = None
                self._left_dragging = False
                if before is not None and after is not None:
                    self.route_point_move_finished.emit(
                        route_id,
                        index,
                        before[0],
                        before[1],
                        after[0],
                        after[1],
                    )
                event.accept()
                return

            mapped = self._widget_to_internal_map(event.position())
            should_add = (
                self._is_drawing_active()
                and not self._is_drawing_paused()
                and not self._left_dragging
                and mapped is not None
                and self._left_press_map is not None
            )
            self._drag_last_pos = None
            self._left_press_pos = None
            self._left_press_map = None
            self._left_dragging = False
            if should_add:
                self.drawing_point_requested.emit(int(mapped[0]), int(mapped[1]))
                event.accept()
                return
        self._drag_last_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._pixmap is None:
            super().wheelEvent(event)
            return

        delta = self._wheel_zoom_delta(event)
        if delta == 0:
            return

        anchor_map = self._widget_to_map(event.position())
        old_zoom = self._zoom
        if delta > 0:
            self._zoom = min(self._MAX_ZOOM, self._zoom * self._ZOOM_STEP)
        else:
            self._zoom = max(self._min_zoom_for_full_map(), self._zoom / self._ZOOM_STEP)

        if math.isclose(self._zoom, old_zoom):
            return

        if anchor_map is not None:
            crop_w = max(120, int(max(self.width(), 100) / self._zoom))
            crop_h = max(120, int(max(self.height(), 100) / self._zoom))
            draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
            if draw_rect.width() > 0 and draw_rect.height() > 0:
                rel_x = (event.position().x() - draw_rect.left()) / draw_rect.width()
                rel_y = (event.position().y() - draw_rect.top()) / draw_rect.height()
                self._view_center = QPointF(
                    anchor_map[0] - (rel_x - 0.5) * crop_w,
                    anchor_map[1] - (rel_y - 0.5) * crop_h,
                )

        self._disable_center_lock()
        self._refresh_from_last_frame()
        event.accept()

    @staticmethod
    def _wheel_zoom_delta(event) -> int:
        angle_delta = event.angleDelta()
        delta = angle_delta.y()
        if delta != 0:
            return delta

        alt_pressed = bool(event.modifiers() & Qt.AltModifier)
        if alt_pressed and angle_delta.x() != 0:
            return angle_delta.x()

        pixel_delta = event.pixelDelta()
        delta = pixel_delta.y()
        if delta != 0:
            return delta
        if alt_pressed and pixel_delta.x() != 0:
            return pixel_delta.x()
        return 0

    def mouseDoubleClickEvent(self, event):
        if self._is_drawing_active() or self._is_route_calibration_active():
            event.accept()
            return
        mapped = self._widget_to_map(event.position())
        if mapped is None:
            return
        self.relocate_requested.emit(int(mapped[0]), int(mapped[1]))

    def _hit_test_node(self, widget_pos: QPointF) -> tuple[str, int] | None:
        mapped = self._widget_to_map(widget_pos)
        if mapped is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = max(6.0, _HIT_RADIUS_WIDGET_PX * ratio)
        try:
            return self.route_mgr.hit_test_point(mapped[0], mapped[1], map_threshold, coord_adapter=self._coord_adapter)
        except TypeError:
            return self.route_mgr.hit_test_point(mapped[0], mapped[1], map_threshold)

    def _hit_test_draft_node(self, widget_pos: QPointF) -> int | None:
        mapped = self._widget_to_internal_map(widget_pos)
        context = self._drawing_context if isinstance(self._drawing_context, dict) else None
        if mapped is None or not context:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = self._coord_adapter.threshold_to_internal(max(6.0, _HIT_RADIUS_WIDGET_PX * ratio))
        best: tuple[float, int] | None = None
        for index, point in enumerate(context.get("points") or []):
            if not isinstance(point, dict):
                continue
            try:
                px = float(point["x"])
                py = float(point["y"])
            except (KeyError, TypeError, ValueError):
                continue
            dist = math.hypot(px - mapped[0], py - mapped[1])
            if dist > map_threshold:
                continue
            if best is None or dist < best[0]:
                best = (dist, index)
        return None if best is None else best[1]

    def _hit_test_annotation(self, widget_pos: QPointF) -> dict | None:
        mapped = self._widget_to_map(widget_pos)
        if mapped is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = max(6.0, _HIT_RADIUS_WIDGET_PX * ratio)
        try:
            return self.route_mgr.hit_test_annotation_point(
                mapped[0],
                mapped[1],
                map_threshold,
                coord_adapter=self._coord_adapter,
            )
        except TypeError:
            return self.route_mgr.hit_test_annotation_point(mapped[0], mapped[1], map_threshold)

    def _route_point_undo_context_items(self) -> list[ContextMenuItem]:
        if self._is_drawing_active() or self._is_route_calibration_active() or not self._route_point_move_undo_available:
            return []
        return [
            ContextMenuItem(
                strings.UNDO_ROUTE_POINT_MOVE_MENU_LABEL,
                lambda: self.route_point_move_undo_requested.emit(),
            ),
            ContextMenuItem.separator_item(),
        ]

    def contextMenuEvent(self, event):
        pos = QPointF(event.pos())
        if self._is_route_calibration_active():
            event.accept()
            return
        if self._is_drawing_active():
            draft_hit = self._hit_test_draft_node(pos)
            if draft_hit is not None:
                route_id = str(self._drawing_context.get("route_id") or "") if self._drawing_context else ""
                point = (self._drawing_context.get("points") or [])[draft_hit] if self._drawing_context else {}
                has_annotation = bool(
                    isinstance(point, dict)
                    and (str(point.get("typeId") or "").strip() or str(point.get("type") or "").strip())
                )
                annotation_label = (
                    strings.CHANGE_POINT_ANNOTATION_MENU_LABEL
                    if has_annotation
                    else strings.ADD_POINT_ANNOTATION_MENU_LABEL
                )
                items = [
                    ContextMenuItem(
                        annotation_label,
                        lambda rid=route_id, idx=draft_hit: self.change_point_annotation_requested.emit(rid, idx),
                    ),
                    ContextMenuItem(
                        strings.CHANGE_POINT_NODE_TYPE_MENU_LABEL,
                        lambda rid=route_id, idx=draft_hit, gpos=QPoint(event.globalPos()):
                        self.change_point_node_type_requested.emit(rid, idx, gpos),
                    ),
                    ContextMenuItem(
                        strings.CHANGE_POINT_ORDER_MENU_LABEL,
                        lambda rid=route_id, idx=draft_hit: self.change_point_order_requested.emit(rid, idx),
                    ),
                ]
                if has_annotation:
                    items.append(
                        ContextMenuItem(
                            strings.DELETE_POINT_ANNOTATION_MENU_LABEL,
                            lambda rid=route_id, idx=draft_hit:
                            self.delete_point_annotation_requested.emit(rid, idx),
                        )
                    )
                items.extend(
                    [
                        ContextMenuItem.separator_item(),
                        ContextMenuItem(
                            strings.DELETE_POINT_MENU_LABEL,
                            lambda rid=route_id, idx=draft_hit: self.delete_point_requested.emit(rid, idx),
                        ),
                    ]
                )
                show_context_menu(
                    self,
                    event.globalPos(),
                    items,
                    object_name="MapNodeContextMenu",
                )
                event.accept()
                return

        hit = self._hit_test_node(pos)
        if hit is not None:
            route_id, point_index = hit
            visited = self.route_mgr.point_visited(route_id, point_index)
            has_annotation = self.route_mgr.route_point_has_annotation(route_id, point_index)
            annotation_label = (
                strings.CHANGE_POINT_ANNOTATION_MENU_LABEL
                if has_annotation
                else strings.ADD_POINT_ANNOTATION_MENU_LABEL
            )
            items = self._route_point_undo_context_items() + [
                ContextMenuItem(
                    strings.MARK_POINT_UNVISITED_MENU_LABEL if visited else strings.MARK_POINT_VISITED_MENU_LABEL,
                    lambda rid=route_id, idx=point_index, state=not bool(visited):
                    self.mark_point_visited_requested.emit(rid, idx, state),
                ),
                ContextMenuItem(
                    annotation_label,
                    lambda rid=route_id, idx=point_index: self.change_point_annotation_requested.emit(rid, idx),
                ),
                ContextMenuItem(
                    strings.CHANGE_POINT_NODE_TYPE_MENU_LABEL,
                    lambda rid=route_id, idx=point_index, gpos=QPoint(event.globalPos()):
                    self.change_point_node_type_requested.emit(rid, idx, gpos),
                ),
                ContextMenuItem(
                    strings.CHANGE_POINT_ORDER_MENU_LABEL,
                    lambda rid=route_id, idx=point_index: self.change_point_order_requested.emit(rid, idx),
                ),
            ]
            if has_annotation:
                items.append(
                    ContextMenuItem(
                        strings.DELETE_POINT_ANNOTATION_MENU_LABEL,
                        lambda rid=route_id, idx=point_index:
                        self.delete_point_annotation_requested.emit(rid, idx),
                    )
                )
            items.extend(
                [
                    ContextMenuItem.separator_item(),
                    ContextMenuItem(
                        strings.DELETE_POINT_MENU_LABEL,
                        lambda rid=route_id, idx=point_index: self.delete_point_requested.emit(rid, idx),
                    ),
                ]
            )
            show_context_menu(self, event.globalPos(), items, object_name="MapNodeContextMenu")
            event.accept()
            return

        annotation_hit = self._hit_test_annotation(pos)
        if annotation_hit is not None:
            type_id = str(annotation_hit.get("typeId") or "")
            point_index = int(annotation_hit.get("pointIndex"))
            show_context_menu(
                self,
                event.globalPos(),
                self._route_point_undo_context_items() + [
                    ContextMenuItem(
                        strings.MAP_CHANGE_ANNOTATION_MENU_LABEL,
                        lambda tid=type_id, idx=point_index: self.change_annotation_requested.emit(tid, idx),
                    ),
                    ContextMenuItem(
                        strings.MAP_ADD_ANNOTATION_TO_ROUTE_MENU_LABEL,
                        lambda tid=type_id, idx=point_index:
                        self.add_annotation_to_route_requested.emit(tid, idx),
                    ),
                    ContextMenuItem.separator_item(),
                    ContextMenuItem(
                        strings.MAP_DELETE_ANNOTATION_MENU_LABEL,
                        lambda tid=type_id, idx=point_index: self.delete_annotation_requested.emit(tid, idx),
                    ),
                ],
                object_name="MapAnnotationContextMenu",
            )
            event.accept()
            return

        mapped = self._widget_to_internal_map(pos)
        if mapped is None:
            event.ignore()
            return
        map_x = int(mapped[0])
        map_y = int(mapped[1])
        show_context_menu(
            self,
            event.globalPos(),
            self._route_point_undo_context_items() + [
                ContextMenuItem(
                    strings.MAP_ADD_ANNOTATION_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_annotation_requested.emit(x, y),
                ),
                ContextMenuItem(
                    strings.MAP_ADD_COLLECT_POINT_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_route_node_requested.emit(x, y, NODE_TYPE_COLLECT),
                ),
                ContextMenuItem(
                    strings.MAP_ADD_TELEPORT_POINT_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_route_node_requested.emit(x, y, NODE_TYPE_TELEPORT),
                ),
                ContextMenuItem(
                    strings.MAP_ADD_GUIDE_POINT_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_route_node_requested.emit(x, y, NODE_TYPE_VIRTUAL),
                ),
                ContextMenuItem(
                    strings.MAP_ADD_POINT_WITH_ANNOTATION_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_annotated_point_requested.emit(x, y),
                    visible=not self._is_drawing_active() and self._route_point_drag_enabled,
                ),
            ],
            object_name="MapBlankContextMenu",
        )
        event.accept()

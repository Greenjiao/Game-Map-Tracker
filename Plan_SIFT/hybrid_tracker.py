"""SiftTracker 之上的整合包装器。

吸收同学副本 RobustTracker 在草原大色块场景的核心精华：
  1. **外层自维护按真实 dt 的速度模型**——比底层 SiftTracker 按帧、有 confidence 衰减
     的运动模型更激进，在草原均匀纹理（底层匹配易失败/震荡）上能持续把位置推向玩家
     真实方向，而不是停在原地等下一次 LOCKED。
  2. **每帧把"平滑后位置"回灌为 sift._last_x/y 并清零 sift._lost_frames**——让底层
     `_SPATIAL_PRIOR` 过滤始终生效，且圆心永远使用更稳定的 HybridTracker 平滑位置
     而不是底层那个被噪声拉得抖动的 last。这是副本"草原稳"的真正机制（副本里
     `_verify_locally` 在 226×226 小地图配置下因模板>搜索区根本没真跑过）。
  3. **双层跳变抑制**：teleport 阈值（>300px 视为传送）/ max_jump 阈值（45–300px 视为
     SIFT 错乱），异常跳变用修复后的局部模板复核救场，否则强制走 predicted_pos。
  4. **输出 EMA 平滑**（α=0.25）让 UI 显示去抖。

对比同学副本的关键修正（保留草原优势的同时修掉海边失锁）：
  - 删除 `center_brightness > 200` 这条预校验——副本里它把亮蓝海面误判为载入屏导致反复
    挂起；我们只保留 `std<8` 和 `edge_density<0.012` 这两条对全黑/全白载入屏合理的规则。
  - `_verify_locally` 修掉模板尺寸大于搜索区导致 cv2 抛异常被裸 except 吞掉的 bug：
    模板先 resize 到 ≤100，搜索区再按模板大小动态扩展。
  - SIFT LOST 时不立即清空内部状态——用速度推演撑过短暂丢失，避免海岸线偶发失败导致
    重新初始化（副本会清空 current_pos，下一次 LOCKED 速度归零）。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ui_island.state.tracking import BaseTracker, TrackResult, TrackState

if TYPE_CHECKING:
    from .sift_tracker import SiftTracker


# 输出平滑：越小越平滑，与副本一致
OUTPUT_SMOOTHING_ALPHA = 0.25
# 速度更新学习率：新观测速度的权重，与副本一致
VELOCITY_LEARNING_RATE = 0.3
# dt 下限，防止首帧 / 卡顿后除零
MIN_DT_S = 0.001
# dt 上限，避免长时间暂停后突然推演飞出去
MAX_DT_S = 0.5

# 双层跳变抑制（副本核心机制之一）
MAX_JUMP_DISTANCE_PX = 45.0
TELEPORT_THRESHOLD_PX = 300.0

# 异常跳变时局部模板复核的接受门槛
LOCAL_VERIFY_MIN_CONF = 0.85
# 模板缩放后短边上限（副本未做这个缩放，因此 _verify_locally 在 226×226 配置下从未真跑）
LOCAL_VERIFY_TEMPLATE_MAX = 100
# 搜索区比模板半边大多少
LOCAL_VERIFY_PAD_PX = 50

# 载入屏 / 全黑画面快筛阈值（保守，避免误伤海面）
FRAME_VALID_MIN_EDGE_DENSITY = 0.012
FRAME_VALID_MIN_STD = 8.0

# SIFT LOST 时仍用速度推演撑住的最大帧数（超过则真清空状态）
LOST_BLIND_PUSH_MAX_FRAMES = 30


class HybridTracker(BaseTracker):
    def __init__(self, sift_tracker: "SiftTracker") -> None:
        self.sift = sift_tracker
        self.logic_map_bgr = sift_tracker.logic_map_bgr
        self.map_width = sift_tracker.map_width
        self.map_height = sift_tracker.map_height

        self._smooth_xy: np.ndarray | None = None
        self._velocity = np.zeros(2, dtype=np.float32)  # 像素/秒
        self._last_step_t: float = time.time()
        self._blind_push_frames = 0

    def set_anchor(self, x: int, y: int) -> None:
        self._smooth_xy = np.array([float(x), float(y)], dtype=np.float32)
        self._velocity[:] = 0.0
        self._blind_push_frames = 0
        self.sift.set_anchor(int(x), int(y))

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        now = time.time()
        dt = float(np.clip(now - self._last_step_t, MIN_DT_S, MAX_DT_S))
        self._last_step_t = now

        if self._frame_is_loading_screen(minimap_bgr):
            return TrackResult(TrackState.SEARCHING, latency_ms=0.0)

        # 每帧推演位置 = 当前平滑位置 + v * dt
        predicted_xy: np.ndarray | None = None
        if self._smooth_xy is not None:
            predicted_xy = self._smooth_xy + self._velocity * dt

        # 让底层 SIFT 跑——但先把"预测位置"回灌为 last_x/y 并清零 lost_frames，
        # 让底层 _SPATIAL_PRIOR 始终用我们的稳定圆心（这是副本草原优势的关键来源）。
        if predicted_xy is not None:
            self._inject_prior_to_sift(predicted_xy)

        sift_result = self.sift.step(minimap_bgr)

        if sift_result.state == TrackState.LOCKED and sift_result.x is not None and sift_result.y is not None:
            return self._on_sift_locked(sift_result, predicted_xy, minimap_bgr, dt)

        # SIFT 没 LOCKED（INERTIAL/LOST/SEARCHING）—— 只要还有平滑位置就用速度盲推
        if self._smooth_xy is not None and predicted_xy is not None:
            self._blind_push_frames += 1
            if self._blind_push_frames > LOST_BLIND_PUSH_MAX_FRAMES:
                # 推演太久没新观测，认输
                self._smooth_xy = None
                self._velocity[:] = 0.0
                self._blind_push_frames = 0
                return TrackResult(TrackState.LOST, latency_ms=sift_result.latency_ms)

            # 推演位置裁剪到地图范围内
            px = float(np.clip(predicted_xy[0], 0, self.map_width - 1))
            py = float(np.clip(predicted_xy[1], 0, self.map_height - 1))
            self._smooth_xy = np.array([px, py], dtype=np.float32)
            self._inject_prior_to_sift(self._smooth_xy)

            state = TrackState.INERTIAL if sift_result.state in (TrackState.INERTIAL, TrackState.SEARCHING) else TrackState.INERTIAL
            return TrackResult(
                state,
                int(self._smooth_xy[0]),
                int(self._smooth_xy[1]),
                sift_result.match_count,
                sift_result.latency_ms,
            )

        # 完全没有先验位置可用（首帧或长期 LOST 后）—— 透传底层结果
        return sift_result

    def _on_sift_locked(
        self,
        sift_result: TrackResult,
        predicted_xy: np.ndarray | None,
        minimap_bgr: np.ndarray,
        dt: float,
    ) -> TrackResult:
        raw_xy = np.array([float(sift_result.x), float(sift_result.y)], dtype=np.float32)
        self._blind_push_frames = 0

        # 首次 LOCKED 或上一次彻底 LOST 后重新锁定
        if self._smooth_xy is None:
            self._smooth_xy = raw_xy.copy()
            self._velocity[:] = 0.0
            self._inject_prior_to_sift(self._smooth_xy)
            return TrackResult(
                TrackState.LOCKED,
                int(raw_xy[0]),
                int(raw_xy[1]),
                sift_result.match_count,
                sift_result.latency_ms,
            )

        distance = float(np.linalg.norm(raw_xy - self._smooth_xy))
        observation = raw_xy
        reliable = True

        if distance > TELEPORT_THRESHOLD_PX:
            # 玩家传送——直接接受新观测，速度归零
            new_smooth = raw_xy.copy()
            self._velocity[:] = 0.0
            self._smooth_xy = new_smooth
            self._inject_prior_to_sift(self._smooth_xy)
            return TrackResult(
                TrackState.LOCKED,
                int(new_smooth[0]),
                int(new_smooth[1]),
                sift_result.match_count,
                sift_result.latency_ms,
            )

        if distance > MAX_JUMP_DISTANCE_PX:
            # 异常跳变：模板复核救场，否则不接受 raw 观测，走预测位置
            ref = predicted_xy if predicted_xy is not None else self._smooth_xy
            v_xy, v_conf = self._verify_locally(minimap_bgr, ref)
            if v_conf >= LOCAL_VERIFY_MIN_CONF and v_xy is not None:
                observation = v_xy
                reliable = True
            else:
                observation = predicted_xy if predicted_xy is not None else self._smooth_xy
                reliable = False

        # EMA 平滑
        new_smooth = (1.0 - OUTPUT_SMOOTHING_ALPHA) * self._smooth_xy + OUTPUT_SMOOTHING_ALPHA * observation

        if reliable:
            # 用平滑位置变化更新速度（按真实 dt）
            new_v = (new_smooth - self._smooth_xy) / dt
            self._velocity = (1.0 - VELOCITY_LEARNING_RATE) * self._velocity + VELOCITY_LEARNING_RATE * new_v
        else:
            # 不可信观测——速度衰减但不清零，保留运动惯性
            self._velocity *= 0.7

        self._smooth_xy = new_smooth.astype(np.float32, copy=False)
        self._inject_prior_to_sift(self._smooth_xy)

        return TrackResult(
            TrackState.LOCKED,
            int(self._smooth_xy[0]),
            int(self._smooth_xy[1]),
            sift_result.match_count,
            sift_result.latency_ms,
        )

    def _inject_prior_to_sift(self, xy: np.ndarray) -> None:
        """把 HybridTracker 的稳定位置注入底层，作为下一帧空间先验的圆心。

        关键：清零 _lost_frames 让底层的 `_SPATIAL_PRIOR_MAX_LOST_FRAMES=5` 始终生效。
        这是副本"草原大色块场景定位提升"的真实机制——不是它的 _verify_locally
        （那个在 226×226 配置下从未真跑），而是这条注入让底层的空间先验过滤
        始终用一个稳定的圆心去筛 dst 候选，避免被自相似纹理的散乱假匹配污染。
        """
        x = int(np.clip(xy[0], 0, self.map_width - 1))
        y = int(np.clip(xy[1], 0, self.map_height - 1))
        self.sift._last_x = x
        self.sift._last_y = y
        self.sift._lost_frames = 0

    @staticmethod
    def _frame_is_loading_screen(minimap_bgr: np.ndarray) -> bool:
        gray = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
        if float(np.std(gray)) < FRAME_VALID_MIN_STD:
            return True
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / float(edges.size)
        return edge_density < FRAME_VALID_MIN_EDGE_DENSITY

    def _verify_locally(
        self,
        minimap_bgr: np.ndarray,
        ref_xy: np.ndarray,
    ) -> tuple[np.ndarray | None, float]:
        try:
            gray = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
            short = min(gray.shape[:2])
            if short > LOCAL_VERIFY_TEMPLATE_MAX:
                scale = LOCAL_VERIFY_TEMPLATE_MAX / float(short)
                tmpl = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            else:
                tmpl = gray
            th, tw = tmpl.shape[:2]

            mask = np.zeros((th, tw), dtype=np.uint8)
            cv2.circle(mask, (tw // 2, th // 2), int(min(tw, th) * 0.45), 255, -1)
            cv2.circle(mask, (tw // 2, th // 2), int(min(tw, th) * 0.20), 0, -1)

            half = max(tw, th) // 2
            sr = half + LOCAL_VERIFY_PAD_PX
            rx, ry = int(ref_xy[0]), int(ref_xy[1])
            x1 = max(0, rx - sr)
            y1 = max(0, ry - sr)
            x2 = min(self.map_width, rx + sr)
            y2 = min(self.map_height, ry + sr)
            area = cv2.cvtColor(self.logic_map_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)

            if area.shape[0] <= th or area.shape[1] <= tw:
                return None, 0.0

            scores = cv2.matchTemplate(area, tmpl, cv2.TM_CCORR_NORMED, mask=mask)
            _, max_val, _, max_loc = cv2.minMaxLoc(scores)
            mx = x1 + max_loc[0] + tw // 2
            my = y1 + max_loc[1] + th // 2
            return np.array([float(mx), float(my)], dtype=np.float32), float(max_val)
        except (cv2.error, ValueError):
            return None, 0.0

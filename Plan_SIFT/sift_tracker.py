"""SIFT + FLANN + RANSAC tracking engine."""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

import config
from ui_island.services.image_io import imread_unicode
from ui_island.state.tracking import BaseTracker, TrackResult, TrackState

# Base map descriptor cache: avoids re-running 8192² SIFT on every startup.
# Cache is keyed by map filename + file size + mtime — any change to the
# base map automatically invalidates the cache. The CACHE_VERSION below
# should be bumped whenever the cached structure (kp fields, dtype, CLAHE
# pipeline) changes so old caches are ignored.
_CACHE_VERSION = 1
_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "sift"


_EDGE_GUARD_PX = 24
_EDGE_CONFIRM_DISTANCE_PX = 45.0
_EDGE_CONFIRM_HITS = 2
_MIN_INLIER_RATIO = 0.45
_EDGE_MIN_INLIER_COUNT = 10
_EDGE_MIN_INLIER_RATIO = 0.60
_HIGH_CONF_INLIER_COUNT = 14
_HIGH_CONF_INLIER_RATIO = 0.65
_LARGE_JUMP_RADIUS_FACTOR = 1.8

_STRICT_MATCH_RATIO_STEPS = (0.78, 0.86)
_MINIMAP_SCALE_TARGET = 220
_MINIMAP_MAX_SCALE = 2.0
_MINIMAP_CIRCLE_RATIO = 0.48
_MINIMAP_CENTER_MASK_RATIO = 0.075
_GLOBAL_RETRY_INTERVAL_FRAMES = 5


def _cache_signature(map_path: str) -> dict | None:
    """Identifying tuple for the base map file. None when path is unreadable."""
    try:
        st = os.stat(map_path)
    except OSError:
        return None
    return {
        "version": _CACHE_VERSION,
        "path": os.path.abspath(map_path),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "clahe": float(config.SIFT_CLAHE_LIMIT),
    }


def _cache_path_for(map_path: str) -> Path:
    base = Path(map_path).name
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
    return _CACHE_DIR / f"{safe}.v{_CACHE_VERSION}.npz"


def _load_descriptor_cache(
    map_path: str,
) -> tuple[list[cv2.KeyPoint], np.ndarray] | None:
    """Return (keypoints, descriptors) if a valid cache exists, else None."""
    sig = _cache_signature(map_path)
    if sig is None:
        return None
    cache_file = _cache_path_for(map_path)
    if not cache_file.is_file():
        return None
    try:
        with np.load(str(cache_file), allow_pickle=False) as npz:
            stored_path = str(npz["sig_path"])
            stored_size = int(npz["sig_size"])
            stored_mtime = int(npz["sig_mtime_ns"])
            stored_version = int(npz["sig_version"])
            stored_clahe = float(npz["sig_clahe"])
            if (
                stored_version != sig["version"]
                or stored_path != sig["path"]
                or stored_size != sig["size"]
                or stored_mtime != sig["mtime_ns"]
                or abs(stored_clahe - sig["clahe"]) > 1e-9
            ):
                return None
            kp_fields = npz["kp_fields"]  # (N, 7) float32
            des = npz["des"]              # (N, 128) float32
    except (OSError, ValueError, KeyError, EOFError):
        return None

    keypoints: list[cv2.KeyPoint] = []
    for x, y, size, angle, response, octave, class_id in kp_fields:
        keypoints.append(
            cv2.KeyPoint(
                x=float(x),
                y=float(y),
                size=float(size),
                angle=float(angle),
                response=float(response),
                octave=int(octave),
                class_id=int(class_id),
            )
        )
    return keypoints, des


def _save_descriptor_cache(
    map_path: str,
    keypoints: list[cv2.KeyPoint],
    descriptors: np.ndarray,
) -> None:
    """Persist keypoints+descriptors. Failures are non-fatal (logged only)."""
    sig = _cache_signature(map_path)
    if sig is None:
        return
    cache_file = _cache_path_for(map_path)
    # np.savez auto-appends ".npz" to the path argument, so write to a sibling
    # tmp path then atomically rename. Track the actual produced filename so
    # any partial output gets cleaned up on failure.
    tmp_base = cache_file.with_suffix("")  # strips ".npz"
    tmp_target = tmp_base.with_name(tmp_base.name + ".tmp")
    produced = Path(str(tmp_target) + ".npz")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        kp_fields = np.array(
            [
                (kp.pt[0], kp.pt[1], kp.size, kp.angle, kp.response, kp.octave, kp.class_id)
                for kp in keypoints
            ],
            dtype=np.float32,
        )
        np.savez(
            str(tmp_target),
            kp_fields=kp_fields,
            des=descriptors.astype(np.float32, copy=False),
            sig_path=np.array(sig["path"]),
            sig_size=np.array(sig["size"], dtype=np.int64),
            sig_mtime_ns=np.array(sig["mtime_ns"], dtype=np.int64),
            sig_version=np.array(sig["version"], dtype=np.int32),
            sig_clahe=np.array(sig["clahe"], dtype=np.float64),
        )
        os.replace(str(produced), str(cache_file))
    except OSError as exc:
        print(f"[SiftTracker] descriptor cache save failed: {exc}")
        # Clean up any partial tmp file so the cache dir doesn't accumulate junk.
        try:
            if produced.exists():
                produced.unlink()
        except OSError:
            pass


class SiftTracker(BaseTracker):
    def __init__(self) -> None:
        self.logic_map_bgr = imread_unicode(config.LOGIC_MAP_PATH)
        if self.logic_map_bgr is None:
            raise FileNotFoundError(f"Could not load logic map: {config.LOGIC_MAP_PATH}")

        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]

        self.clahe = cv2.createCLAHE(clipLimit=config.SIFT_CLAHE_LIMIT, tileGridSize=(8, 8))
        self.sift = cv2.SIFT_create()

        self.kp_big, self.des_big = self._load_or_compute_base_descriptors()
        if self.des_big is None:
            self.des_big = np.empty((0, 128), dtype=np.float32)
        self._kp_big_pts = np.array([kp.pt for kp in self.kp_big], dtype=np.float32)

        FLANN_INDEX_KDTREE = 1
        self.flann = cv2.FlannBasedMatcher(
            dict(algorithm=FLANN_INDEX_KDTREE, trees=5),
            dict(checks=50),
        )
        self.bf = cv2.BFMatcher(cv2.NORM_L2)

        self._global_train_idx = np.arange(len(self.kp_big), dtype=np.int64)
        self._local_radius = float(getattr(config, "SIFT_LOCAL_SEARCH_RADIUS", 400) or 400)
        self._last_x: int | None = None
        self._last_y: int | None = None
        self._lost_frames = 0
        self._max_lost = config.MAX_LOST_FRAMES
        self._pending_edge_xy: tuple[int, int] | None = None
        self._pending_edge_hits = 0

    def _load_or_compute_base_descriptors(
        self,
    ) -> tuple[list[cv2.KeyPoint], np.ndarray]:
        """Try cache first, fall back to recomputation. Always logs timing."""
        map_path = config.LOGIC_MAP_PATH
        t_start = time.time()

        cached = _load_descriptor_cache(map_path)
        if cached is not None:
            keypoints, descriptors = cached
            elapsed = (time.time() - t_start) * 1000.0
            print(
                f"[SiftTracker] base descriptors loaded from cache: "
                f"{len(keypoints)} keypoints in {elapsed:.0f}ms"
            )
            return keypoints, descriptors

        logic_gray = cv2.cvtColor(self.logic_map_bgr, cv2.COLOR_BGR2GRAY)
        logic_gray = self.clahe.apply(logic_gray)
        keypoints, descriptors = self.sift.detectAndCompute(logic_gray, None)
        if descriptors is None:
            descriptors = np.empty((0, 128), dtype=np.float32)
            keypoints = list(keypoints) if keypoints is not None else []
        else:
            keypoints = list(keypoints)
        elapsed = (time.time() - t_start) * 1000.0
        print(
            f"[SiftTracker] base descriptors computed: "
            f"{len(keypoints)} keypoints in {elapsed:.0f}ms (caching for next launch)"
        )
        _save_descriptor_cache(map_path, keypoints, descriptors)
        return keypoints, descriptors

    def set_anchor(self, x: int, y: int) -> None:
        self._last_x, self._last_y = int(x), int(y)
        self._lost_frames = 0
        self._pending_edge_xy = None
        self._pending_edge_hits = 0

    @staticmethod
    def _homography_quality(mask: np.ndarray | None, good_count: int) -> tuple[int, float]:
        if mask is None or good_count <= 0:
            return 0, 0.0
        inlier_count = int(np.count_nonzero(mask.ravel()))
        return inlier_count, inlier_count / float(good_count)

    def _near_map_edge(self, x: int, y: int) -> bool:
        return (
            x < _EDGE_GUARD_PX
            or y < _EDGE_GUARD_PX
            or x >= self.map_width - _EDGE_GUARD_PX
            or y >= self.map_height - _EDGE_GUARD_PX
        )

    def _is_large_jump(self, x: int, y: int) -> bool:
        if self._last_x is None or self._last_y is None:
            return False
        dist = float(np.hypot(x - self._last_x, y - self._last_y))
        return dist > self._local_radius * _LARGE_JUMP_RADIUS_FACTOR

    @staticmethod
    def _is_high_confidence(inlier_count: int, inlier_ratio: float) -> bool:
        return inlier_count >= _HIGH_CONF_INLIER_COUNT and inlier_ratio >= _HIGH_CONF_INLIER_RATIO

    def _accept_edge_candidate(self, x: int, y: int) -> bool:
        if self._pending_edge_xy is None:
            self._pending_edge_xy = (x, y)
            self._pending_edge_hits = 1
            return False

        dist = float(np.hypot(x - self._pending_edge_xy[0], y - self._pending_edge_xy[1]))
        if dist <= _EDGE_CONFIRM_DISTANCE_PX:
            self._pending_edge_xy = (x, y)
            self._pending_edge_hits += 1
        else:
            self._pending_edge_xy = (x, y)
            self._pending_edge_hits = 1
        return self._pending_edge_hits >= _EDGE_CONFIRM_HITS

    def _reset_edge_candidate(self) -> None:
        self._pending_edge_xy = None
        self._pending_edge_hits = 0

    @staticmethod
    def _ratio_steps() -> list[float]:
        try:
            user_ratio = float(config.SIFT_MATCH_RATIO)
        except (TypeError, ValueError):
            user_ratio = 0.9
        user_ratio = max(0.01, min(0.99, user_ratio))

        steps = [ratio for ratio in _STRICT_MATCH_RATIO_STEPS if ratio < user_ratio]
        steps.append(user_ratio)

        unique: list[float] = []
        for ratio in steps:
            if not unique or abs(unique[-1] - ratio) > 1e-6:
                unique.append(ratio)
        return unique

    @staticmethod
    def _good_matches(matches: tuple | list, ratio: float) -> list:
        return [
            m for pair in matches if len(pair) == 2
            for m, n in [pair]
            if m.distance < ratio * n.distance
        ]

    @staticmethod
    def _minimap_feature_mask(shape: tuple[int, int]) -> np.ndarray:
        h, w = shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        if h <= 0 or w <= 0:
            return mask

        cx, cy = w // 2, h // 2
        radius = max(1, int(min(w, h) * _MINIMAP_CIRCLE_RATIO))
        cv2.circle(mask, (cx, cy), radius, 255, -1)

        half = max(8, int(min(w, h) * _MINIMAP_CENTER_MASK_RATIO))
        cv2.rectangle(
            mask,
            (max(0, cx - half), max(0, cy - half)),
            (min(w - 1, cx + half), min(h - 1, cy + half)),
            0,
            -1,
        )
        return mask

    def _preprocess_minimap(self, minimap_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
        short_side = min(gray.shape[:2])
        if 0 < short_side < _MINIMAP_SCALE_TARGET:
            scale = min(_MINIMAP_MAX_SCALE, _MINIMAP_SCALE_TARGET / float(short_side))
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        gray = self.clahe.apply(gray)
        return gray, self._minimap_feature_mask(gray.shape)

    def _local_train_indices(self) -> np.ndarray | None:
        if (
            self._last_x is None
            or self._last_y is None
            or self._kp_big_pts.size <= 0
        ):
            return None

        dx = self._kp_big_pts[:, 0] - self._last_x
        dy = self._kp_big_pts[:, 1] - self._last_y
        mask = (dx * dx + dy * dy) <= (self._local_radius * self._local_radius)
        local_idx = np.nonzero(mask)[0]
        if local_idx.size < config.SIFT_MIN_MATCH_COUNT * 2:
            return None
        return local_idx

    def _should_run_global_match(self) -> bool:
        if self._last_x is None or self._last_y is None:
            return True
        return self._lost_frames % _GLOBAL_RETRY_INTERVAL_FRAMES == 0

    def _match_candidates(self, des_mini: np.ndarray) -> Iterator[tuple[list, np.ndarray]]:
        """Return local/global candidates from strict to user-allowed ratio."""
        if len(self.kp_big) <= 0 or self.des_big.size <= 0:
            return

        local_threshold = max(config.SIFT_MIN_MATCH_COUNT + 3, 8)
        global_threshold = max(config.SIFT_MIN_MATCH_COUNT, 6)
        local_idx = self._local_train_indices()

        local_matches = None
        if local_idx is not None:
            local_matches = self.bf.knnMatch(des_mini, self.des_big[local_idx], k=2)

        for ratio in self._ratio_steps():
            if local_matches is not None and local_idx is not None:
                good = self._good_matches(local_matches, ratio)
                if len(good) >= local_threshold:
                    yield good, local_idx

        if not self._should_run_global_match():
            return

        global_matches = self.flann.knnMatch(des_mini, self.des_big, k=2)
        for ratio in self._ratio_steps():
            good = self._good_matches(global_matches, ratio)
            if len(good) >= global_threshold:
                yield good, self._global_train_idx

    def _candidate_position(
        self,
        kp_mini: tuple | list,
        good: list,
        train_idx_map: np.ndarray,
        gray_shape: tuple[int, int],
    ) -> tuple[int, int, int, int, float, bool] | None:
        src = np.float32([kp_mini[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32(
            [self.kp_big[train_idx_map[m.trainIdx]].pt for m in good]
        ).reshape(-1, 1, 2)
        M, mask = cv2.findHomography(src, dst, cv2.RANSAC, config.SIFT_RANSAC_THRESHOLD)
        if M is None:
            return None

        good_count = len(good)
        inlier_count, inlier_ratio = self._homography_quality(mask, good_count)
        min_inliers = max(config.SIFT_MIN_MATCH_COUNT, 6)
        if inlier_count < min_inliers or inlier_ratio < _MIN_INLIER_RATIO:
            return None

        h, w = gray_shape
        center = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), M)
        tx, ty = int(center[0][0][0]), int(center[0][0][1])
        if not (0 <= tx < self.map_width and 0 <= ty < self.map_height):
            return None

        near_edge = self._near_map_edge(tx, ty)
        high_conf = self._is_high_confidence(inlier_count, inlier_ratio)
        edge_quality_ok = (
            inlier_count >= _EDGE_MIN_INLIER_COUNT
            and inlier_ratio >= _EDGE_MIN_INLIER_RATIO
        )
        large_jump_ok = (not self._is_large_jump(tx, ty)) or high_conf
        if not large_jump_ok or (near_edge and not edge_quality_ok):
            return None

        return tx, ty, good_count, inlier_count, inlier_ratio, near_edge

    def step(self, minimap_bgr: np.ndarray) -> TrackResult:
        t0 = time.time()
        gray, feature_mask = self._preprocess_minimap(minimap_bgr)

        kp_mini, des_mini = self.sift.detectAndCompute(gray, feature_mask)
        locked = False
        cx = cy = None
        good_count = 0
        accepted = None

        if des_mini is not None and len(kp_mini) >= 2:
            for good, train_idx_map in self._match_candidates(des_mini):
                good_count = max(good_count, len(good))
                candidate = self._candidate_position(
                    kp_mini,
                    good,
                    train_idx_map,
                    gray.shape,
                )
                if candidate is not None:
                    accepted = candidate
                    break

        if accepted is not None:
            tx, ty, accepted_good_count, _inlier_count, _inlier_ratio, near_edge = accepted
            edge_confirmed = (not near_edge) or self._accept_edge_candidate(tx, ty)
            if edge_confirmed:
                locked = True
                cx, cy = tx, ty
                good_count = accepted_good_count
                self._last_x, self._last_y = tx, ty
                self._lost_frames = 0
                self._reset_edge_candidate()

        latency = (time.time() - t0) * 1000.0

        if locked:
            return TrackResult(TrackState.LOCKED, cx, cy, good_count, latency)

        if self._last_x is not None and self._lost_frames < self._max_lost:
            self._lost_frames += 1
            return TrackResult(
                TrackState.INERTIAL, self._last_x, self._last_y, good_count, latency
            )

        self._last_x = None
        self._last_y = None
        self._reset_edge_candidate()
        return TrackResult(TrackState.LOST, latency_ms=latency)

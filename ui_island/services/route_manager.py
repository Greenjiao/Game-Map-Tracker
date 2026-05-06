"""Route loading, drawing, persistence, and filesystem operations."""

from __future__ import annotations

import colorsys
import glob
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import time
import uuid
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config
from ui_island.services import resource_metadata
from ui_island.services.image_io import imread_unicode
from tools.route_point_optimizer import best_insertion_index, optimize_route_points, total_route_length

_CLOSE_THRESHOLD = 20
_GUIDE_COLOR = (0, 0, 0)
_GUIDE_PLAYER_CLEARANCE = 18
_GUIDE_TARGET_CLEARANCE = 14
_GUIDE_HINT_BG = (245, 245, 245, 220)
_GUIDE_HINT_BORDER = (20, 20, 20, 185)
_GUIDE_HINT_PADDING_X = 8
_GUIDE_HINT_PADDING_Y = 5
_GUIDE_HINT_FONT_SIZE = 15
_PROGRESS_FILE = "progress.json"
_VISIBILITY_FILE = "selected_routes.json"
_ALGORITHM_CATEGORY = "算法生成"
_ALGORITHM_ROUTE_SUFFIX = "_路线(算法生成)"
_INVALID_FILE_NAME_CHARS = set('<>:"/\\|?*')
_POINT_ICON_SIZE = 24
_POINT_ICON_VISITED_ALPHA = 0.35
_ANNOTATION_ICON_SIZE = 20
_ANNOTATION_SPATIAL_CELL_SIZE = 256
_ANNOTATION_QUERY_PADDING_SCREEN_PX = 28
_ANNOTATION_CLUSTER_GRID_PX = 36
_ANNOTATION_CLUSTER_RATIO_THRESHOLD = 3.0
_ANNOTATION_CLUSTER_VISIBLE_THRESHOLD = 600
NODE_TYPE_COLLECT = "collect"
NODE_TYPE_TELEPORT = "teleport"
NODE_TYPE_VIRTUAL = "virtual"
NODE_TYPES = {NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL}
_NODE_TYPE_LABELS = {
    NODE_TYPE_COLLECT: "采集点",
    NODE_TYPE_TELEPORT: "传送点",
    NODE_TYPE_VIRTUAL: "引路点",
}
_AUTO_LABEL_PATTERN = re.compile(r"^.+\s+\d+$")
_SPECIAL_SEGMENT_COLOR = (255, 255, 255)
_DEFAULT_ROUTE_COLOR_HEX = "#1ad1ff"
_DEFAULT_SPECIAL_LINE_COLOR_HEX = "#ffffff"
_DEFAULT_POINTER_ARROW_COLOR_HEX = "#000000"
_UNSET = object()


@dataclass(frozen=True)
class _GuideTarget:
    xy: tuple[float, float]
    distance: float
    arrow_start_xy: tuple[float, float] | None = None
    arrow_target_xy: tuple[float, float] | None = None


@dataclass(frozen=True)
class _TeleportPoint:
    xy: tuple[float, float]
    label: str


@dataclass(frozen=True)
class _AnnotationSpatialEntry:
    type_id: str
    point_index: int
    point: dict
    xy: tuple[float, float]


def _color_for_key(key: str) -> tuple[int, int, int]:
    """Stable fallback color derived from a route key."""
    digest = hashlib.md5(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


def _route_color_from_hex(value: object) -> tuple[int, int, int]:
    return _color_from_hex(value, _DEFAULT_ROUTE_COLOR_HEX)


def _normalize_route_color_hex(value: object) -> str | None:
    raw = str(value or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return f"#{raw.casefold()}"


def _color_from_hex(value: object, default: str) -> tuple[int, int, int]:
    raw = str(value or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        raw = default[1:]
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        r = int(default[1:3], 16)
        g = int(default[3:5], 16)
        b = int(default[5:7], 16)
    return b, g, r


def _config_color(name: str, default: str) -> tuple[int, int, int]:
    return _color_from_hex(getattr(config, name, default), default)


def _special_lines_follow_route_color() -> bool:
    return bool(getattr(config, "ROUTE_SPECIAL_LINES_FOLLOW_ROUTE_COLOR", False))


def _pointer_arrow_visible() -> bool:
    return bool(getattr(config, "ROUTE_POINTER_ARROW_VISIBLE", True))


def _strict_guide_mode() -> bool:
    return bool(getattr(config, "ROUTE_STRICT_GUIDE_MODE", False))


def _line_color_for_style(style: str, route_color: tuple[int, int, int]) -> tuple[int, int, int]:
    if style == NODE_TYPE_TELEPORT:
        if _special_lines_follow_route_color():
            return route_color
        return _config_color("ROUTE_TELEPORT_LINE_COLOR", _DEFAULT_SPECIAL_LINE_COLOR_HEX)
    if style == NODE_TYPE_VIRTUAL:
        if _special_lines_follow_route_color():
            return route_color
        return _config_color("ROUTE_GUIDE_LINE_COLOR", _DEFAULT_SPECIAL_LINE_COLOR_HEX)
    return route_color


_best_insertion_index = best_insertion_index


def _config_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(getattr(config, name, default) or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def _config_bool(name: str, default: bool) -> bool:
    value = getattr(config, name, default)
    if value is None:
        return bool(default)
    return bool(value)


def _clamp_opacity(value: object, default: float) -> float:
    try:
        opacity = float(value)
    except (TypeError, ValueError):
        opacity = float(default)
    return max(0.0, min(1.0, opacity))


def _config_opacity(name: str, default: float) -> float:
    return _clamp_opacity(getattr(config, name, default), default)


def _project_root() -> str:
    return config.BASE_DIR


def _default_teleport_dir() -> str:
    return os.path.join(_project_root(), "tools", "points_get", "teleport")


def _default_point_icon_dir() -> str:
    return os.path.join(_project_root(), "tools", "points_icon")


def _default_annotation_points_file() -> str:
    return config.selected_annotation_path_from_settings()


def _ensure_route_metadata(payload: dict) -> dict:
    resource_metadata.ensure_metadata(
        payload,
        include_id=False,
        include_route_defaults=True,
    )
    return payload


def _ensure_existing_route_metadata(payload: dict) -> dict:
    resource_metadata.ensure_metadata(
        payload,
        include_id=False,
        include_route_defaults=True,
        preserve_format_version=True,
        enable_versions_policy="append_current_if_list",
    )
    return payload


def _ensure_annotation_metadata(payload: dict) -> dict:
    return resource_metadata.ensure_metadata(
        payload,
        include_id=True,
    )


_ROUTE_PAYLOAD_KEY_ORDER = (
    "id",
    "format_version",
    "enable_versions",
    "color",
    "name",
    "notes",
    "loop",
    "coord_transform",
    "points",
    "nodes",
)


def _ordered_route_payload(payload: dict) -> dict:
    ordered = {key: payload[key] for key in _ROUTE_PAYLOAD_KEY_ORDER if key in payload}
    ordered.update((key, value) for key, value in payload.items() if key not in ordered)
    return ordered


def _point_xy(point: dict) -> tuple[float, float] | None:
    try:
        return float(point["x"]), float(point["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _adapter_to_current(
    coord_adapter,
    xy: tuple[float, float],
) -> tuple[float, float]:
    if coord_adapter is None or getattr(coord_adapter, "is_identity", True):
        return xy
    return coord_adapter.to_current(float(xy[0]), float(xy[1]))


def _adapter_to_internal(
    coord_adapter,
    xy: tuple[float, float],
) -> tuple[float, float]:
    if coord_adapter is None or getattr(coord_adapter, "is_identity", True):
        return xy
    return coord_adapter.to_internal(float(xy[0]), float(xy[1]))


def _adapter_from_payload(payload: object, fallback_adapter=None):
    explicit = resource_metadata.coord_transform_from_payload(payload)
    if explicit is None:
        return fallback_adapter
    from ui_island.views.map_coordinates import MapCoordinateAdapter

    return MapCoordinateAdapter.from_dict(explicit, map_file=getattr(fallback_adapter, "map_file", None))


def _route_coord_adapter(route: dict | None, fallback_adapter=None):
    return _adapter_from_payload(route, fallback_adapter)


def _route_with_current_coords(route: dict, coord_adapter) -> dict:
    route_adapter = _route_coord_adapter(route, coord_adapter)
    if route_adapter is None or getattr(route_adapter, "is_identity", True):
        return route
    copied = dict(route)
    current_points: list[object] = []
    for point in route.get("points") or []:
        if not isinstance(point, dict):
            current_points.append(point)
            continue
        xy = _point_xy(point)
        if xy is None:
            current_points.append(point)
            continue
        current = dict(point)
        current["x"], current["y"] = route_adapter.to_current(xy[0], xy[1])
        current_points.append(current)
    copied["points"] = current_points
    return copied


def _map_to_canvas_point(
    xy: tuple[float, float],
    vx1: float,
    vy1: float,
    scale_x: float,
    scale_y: float,
) -> tuple[int, int]:
    return (
        int(round((xy[0] - vx1) * scale_x)),
        int(round((xy[1] - vy1) * scale_y)),
    )


def _map_rect_padding_for_screen(
    padding_px: float,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float]:
    return (
        padding_px / max(float(scale_x), 1e-6),
        padding_px / max(float(scale_y), 1e-6),
    )


def _current_rect_to_internal_bounds(
    coord_adapter,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[float, float, float, float]:
    if coord_adapter is None or getattr(coord_adapter, "is_identity", True):
        return x1, y1, x2, y2
    corners = (
        coord_adapter.to_internal(x1, y1),
        coord_adapter.to_internal(x1, y2),
        coord_adapter.to_internal(x2, y1),
        coord_adapter.to_internal(x2, y2),
    )
    xs = [xy[0] for xy in corners]
    ys = [xy[1] for xy in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _routes_with_current_coords(routes: Iterable[dict], coord_adapter) -> list[dict]:
    return [_route_with_current_coords(route, coord_adapter) for route in routes]


def _node_type(point: dict | None) -> str:
    if not isinstance(point, dict):
        return NODE_TYPE_COLLECT
    value = str(point.get("node_type") or NODE_TYPE_COLLECT).strip().casefold()
    return value if value in NODE_TYPES else NODE_TYPE_COLLECT


def _route_node_annotation(point: dict) -> tuple[str, str] | None:
    type_id = str(point.get("typeId") or "").strip()
    type_name = str(point.get("type") or "").strip()
    if not type_id and not type_name:
        return None
    return type_id or type_name, type_name or type_id


def _is_auto_route_node_label(value: object) -> bool:
    label = str(value or "").strip()
    return bool(label and _AUTO_LABEL_PATTERN.match(label))


def is_auto_route_node_label(value: object) -> bool:
    return _is_auto_route_node_label(value)


def _route_node_auto_label(point: dict, fallback_index: int, counters: dict[str, int]) -> str:
    annotation = _route_node_annotation(point)
    if annotation is not None:
        key, label = annotation
        count_key = f"annotation:{key}"
        counters[count_key] = counters.get(count_key, 0) + 1
        return f"{label} {counters[count_key]}"

    raw_node_type = str(point.get("node_type") or "").strip().casefold()
    if raw_node_type in NODE_TYPES:
        label = _NODE_TYPE_LABELS.get(raw_node_type, "节点")
        count_key = f"node_type:{raw_node_type}"
        counters[count_key] = counters.get(count_key, 0) + 1
        return f"{label} {counters[count_key]}"

    return f"节点 {fallback_index + 1}"


def route_node_auto_label(point: dict, fallback_index: int, counters: dict[str, int] | None = None) -> str:
    return _route_node_auto_label(point, fallback_index, counters if counters is not None else {})


def _apply_route_node_auto_labels(points: list[dict]) -> None:
    counters: dict[str, int] = {}
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            continue
        generated = _route_node_auto_label(point, index, counters)
        existing = str(point.get("label") or "").strip()
        if not existing or _is_auto_route_node_label(existing):
            point["label"] = generated


def apply_route_node_auto_labels(points: list[dict], *, copy: bool = False) -> list[dict]:
    target = [dict(point) for point in points if isinstance(point, dict)] if copy else points
    _apply_route_node_auto_labels(target)
    return target


def _new_route_point_id() -> str:
    return uuid.uuid4().hex


def _has_external_edges(payload: object) -> bool:
    return isinstance(payload, dict) and "edges" in payload


def _external_nodes_as_points(payload: dict) -> list[dict] | None:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _point_xy(node) is None:
            continue
        node["node_type"] = _node_type(node)
    return nodes


def _draw_styled_line(
    canvas: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    *,
    style: str,
    thickness: int = 2,
) -> None:
    if style == NODE_TYPE_COLLECT:
        cv2.line(canvas, start, end, color, thickness, cv2.LINE_AA)
        return

    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    distance = math.hypot(dx, dy)
    if distance <= 0:
        return

    if style == NODE_TYPE_TELEPORT:
        dash_len = 14.0
        gap_len = 8.0
    else:
        dash_len = 2.0
        gap_len = 7.0

    ux = dx / distance
    uy = dy / distance
    cursor = 0.0
    while cursor < distance:
        segment_end = min(distance, cursor + dash_len)
        p1 = (int(round(sx + ux * cursor)), int(round(sy + uy * cursor)))
        p2 = (int(round(sx + ux * segment_end)), int(round(sy + uy * segment_end)))
        cv2.line(canvas, p1, p2, color, thickness, cv2.LINE_AA)
        cursor += dash_len + gap_len


def _draw_circle_with_opacity(
    canvas: np.ndarray,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    thickness: int,
    opacity: float,
) -> None:
    alpha = _clamp_opacity(opacity, 1.0)
    if alpha <= 0:
        return
    if alpha >= 1.0:
        cv2.circle(canvas, center, radius, color, thickness, cv2.LINE_AA)
        return
    overlay = canvas.copy()
    cv2.circle(overlay, center, radius, color, thickness, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, canvas, 1.0 - alpha, 0, dst=canvas)


def _safe_route_stem(value: object, fallback: str) -> str:
    name = str(value or "").strip() or fallback
    cleaned = "".join("_" if char in _INVALID_FILE_NAME_CHARS else char for char in name)
    cleaned = cleaned.strip().rstrip(" .")
    return cleaned or fallback


def _load_teleport_points(folder: str | os.PathLike[str] | None = None) -> list[_TeleportPoint]:
    folder_path = os.fspath(folder) if folder is not None else _default_teleport_dir()
    if not os.path.isdir(folder_path):
        return []

    points: list[_TeleportPoint] = []
    for path in sorted(glob.glob(os.path.join(folder_path, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for index, point in enumerate(payload.get("points") or [], 1):
            if not isinstance(point, dict):
                continue
            xy = _point_xy(point)
            if xy is None:
                continue
            raw_label = point.get("label") or payload.get("name") or f"传送点 {index}"
            label = str(raw_label).strip()
            points.append(_TeleportPoint(xy=xy, label=label or f"传送点 {index}"))
    return points


def _load_point_icon_index(folder: str | os.PathLike[str] | None = None) -> dict[str, str]:
    folder_path = os.fspath(folder) if folder is not None else _default_point_icon_dir()
    index_path = os.path.join(folder_path, "icons.json")
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    result: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "")
        icon_path = str(item.get("iconPath") or "")
        if type_id and icon_path:
            result[type_id] = os.path.join(folder_path, icon_path)
    return result


def _load_annotation_points(path: str | os.PathLike[str] | None = None) -> dict[str, list[dict]]:
    file_path = os.fspath(path) if path is not None else _default_annotation_points_file()
    if not file_path:
        return {}
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    points_by_type = payload.get("pointsByType") if isinstance(payload, dict) else None
    if not isinstance(points_by_type, dict):
        return {}
    result: dict[str, list[dict]] = {}
    for type_id, points in points_by_type.items():
        if isinstance(points, list):
            result[str(type_id)] = [point for point in points if isinstance(point, dict) and _point_xy(point) is not None]
    return result


def _load_annotation_type_items(path: str | os.PathLike[str] | None = None) -> list[dict]:
    file_path = os.fspath(path) if path is not None else _default_annotation_points_file()
    if not file_path:
        return []
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception:
        return []
    types = payload.get("types") if isinstance(payload, dict) else None
    if not isinstance(types, list):
        return []
    result: list[dict] = []
    for item in types:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "")
        if not type_id:
            continue
        copied = dict(item)
        copied["typeId"] = type_id
        copied["type"] = str(copied.get("type") or type_id)
        result.append(copied)
    return result


def _overlay_bgra_icon(
    canvas: np.ndarray,
    icon: np.ndarray,
    center: tuple[int, int],
    *,
    opacity: float,
) -> None:
    if icon.size == 0:
        return
    x = int(center[0] - icon.shape[1] / 2)
    y = int(center[1] - icon.shape[0] / 2)
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(canvas.shape[1], x + icon.shape[1])
    y2 = min(canvas.shape[0], y + icon.shape[0])
    if x1 >= x2 or y1 >= y2:
        return

    icon_x1 = x1 - x
    icon_y1 = y1 - y
    icon_x2 = icon_x1 + (x2 - x1)
    icon_y2 = icon_y1 + (y2 - y1)
    icon_crop = icon[icon_y1:icon_y2, icon_x1:icon_x2]
    if icon_crop.shape[2] == 4:
        alpha = (icon_crop[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)
        rgb = icon_crop[:, :, :3].astype(np.float32)
    else:
        alpha = np.full(icon_crop.shape[:2] + (1,), float(opacity), dtype=np.float32)
        rgb = icon_crop[:, :, :3].astype(np.float32)
    roi = canvas[y1:y2, x1:x2].astype(np.float32)
    canvas[y1:y2, x1:x2] = (rgb * alpha + roi * (1.0 - alpha)).astype(np.uint8)


def _nearest_teleport_label(
    teleports: Iterable[_TeleportPoint],
    target_xy: tuple[float, float],
) -> str | None:
    best: tuple[float, str] | None = None
    tx, ty = target_xy
    for teleport in teleports:
        dist = math.hypot(teleport.xy[0] - tx, teleport.xy[1] - ty)
        if best is None or dist < best[0]:
            best = (dist, teleport.label)
    if best is None:
        return None
    return best[1]


def _distance_to_segment(
    point_xy: tuple[float, float],
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
) -> tuple[float, tuple[float, float]]:
    px, py = point_xy
    ax, ay = start_xy
    bx, by = end_xy
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return math.hypot(px - ax, py - ay), (ax, ay)

    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    proj = (ax + t * dx, ay + t * dy)
    return math.hypot(px - proj[0], py - proj[1]), proj


def _iter_route_segments(points: list[dict], loop: bool) -> Iterable[tuple[int, int, dict, dict]]:
    for index in range(len(points) - 1):
        yield index, index + 1, points[index], points[index + 1]
    if loop and len(points) > 2:
        yield len(points) - 1, 0, points[-1], points[0]


def _nearest_unvisited_node(
    routes: Iterable[dict],
    player_xy: tuple[float, float],
) -> tuple[float, tuple[float, float], dict, int] | None:
    best: tuple[float, tuple[float, float], dict, int] | None = None
    for route in routes:
        for index, point in enumerate(route.get("points") or []):
            if point.get("visited", False):
                continue
            xy = _point_xy(point)
            if xy is None:
                continue
            dist = math.hypot(xy[0] - player_xy[0], xy[1] - player_xy[1])
            if best is None or dist < best[0]:
                best = (dist, xy, route, index)
    return best


def _nearest_segment(
    routes: Iterable[dict],
    player_xy: tuple[float, float],
    threshold: float,
) -> tuple[float, dict, int, int, dict, dict, tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    best: tuple[float, dict, int, int, dict, dict, tuple[float, float], tuple[float, float], tuple[float, float]] | None = None
    for route in routes:
        points = route.get("points") or []
        for start_index, end_index, start, end in _iter_route_segments(points, bool(route.get("loop"))):
            start_xy = _point_xy(start)
            end_xy = _point_xy(end)
            if start_xy is None or end_xy is None:
                continue
            dist, projection = _distance_to_segment(player_xy, start_xy, end_xy)
            if dist > threshold:
                continue
            if best is None or dist < best[0]:
                best = (dist, route, start_index, end_index, start, end, projection, start_xy, end_xy)
    return best


def _first_unvisited_node(route: dict, player_xy: tuple[float, float]) -> tuple[int, tuple[float, float], float] | None:
    for index, point in enumerate(route.get("points") or []):
        if point.get("visited", False):
            continue
        xy = _point_xy(point)
        if xy is None:
            continue
        return index, xy, math.hypot(xy[0] - player_xy[0], xy[1] - player_xy[1])
    return None


def _segment_length_between(points: list[dict], start_index: int, end_index: int) -> float:
    start_xy = _point_xy(points[start_index])
    end_xy = _point_xy(points[end_index])
    if start_xy is None or end_xy is None:
        return math.inf
    return math.hypot(end_xy[0] - start_xy[0], end_xy[1] - start_xy[1])


def _route_distance_between_indices(route: dict, start_index: int, target_index: int) -> float:
    points = route.get("points") or []
    count = len(points)
    if start_index == target_index:
        return 0.0
    if not (0 <= start_index < count and 0 <= target_index < count):
        return math.inf

    if not bool(route.get("loop")):
        low = min(start_index, target_index)
        high = max(start_index, target_index)
        return sum(_segment_length_between(points, index, index + 1) for index in range(low, high))

    if count < 2:
        return math.inf
    edge_lengths = [
        _segment_length_between(points, index, (index + 1) % count)
        for index in range(count)
    ]
    forward = 0.0
    index = start_index
    while index != target_index:
        forward += edge_lengths[index]
        index = (index + 1) % count
    backward = 0.0
    index = target_index
    while index != start_index:
        backward += edge_lengths[index]
        index = (index + 1) % count
    return min(forward, backward)


def _route_index_hops(route: dict, start_index: int, target_index: int) -> int:
    points = route.get("points") or []
    count = len(points)
    if not (0 <= start_index < count and 0 <= target_index < count):
        return 10**9
    if bool(route.get("loop")) and count > 0:
        forward = (target_index - start_index) % count
        backward = (start_index - target_index) % count
        return min(forward, backward)
    return abs(start_index - target_index)


def _strict_arrow_target_for_segment(
    route: dict,
    start_index: int,
    end_index: int,
    target_index: int,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
) -> tuple[float, float]:
    start_distance = _route_distance_between_indices(route, start_index, target_index)
    end_distance = _route_distance_between_indices(route, end_index, target_index)
    if start_distance < end_distance:
        return start_xy
    if end_distance < start_distance:
        return end_xy

    start_hops = _route_index_hops(route, start_index, target_index)
    end_hops = _route_index_hops(route, end_index, target_index)
    if start_hops <= end_hops:
        return start_xy
    return end_xy


def _guide_target_for_player(
    routes: Iterable[dict],
    player_xy: tuple[float, float],
    node_distance: float,
    segment_distance: float,
    strict_mode: bool = False,
) -> _GuideTarget | None:
    route_list = list(routes)
    nearest_node = _nearest_unvisited_node(route_list, player_xy)
    nearest_segment = _nearest_segment(route_list, player_xy, segment_distance)

    if nearest_segment is not None:
        _dist, route, start_index, end_index, start, end, projection, start_xy, end_xy = nearest_segment
        if strict_mode:
            first_unvisited = _first_unvisited_node(route, player_xy)
            if first_unvisited is not None:
                target_index, target_xy, target_distance = first_unvisited
                arrow_target = _strict_arrow_target_for_segment(
                    route,
                    start_index,
                    end_index,
                    target_index,
                    start_xy,
                    end_xy,
                )
                return _GuideTarget(target_xy, target_distance, projection, arrow_target)

        start_visited = bool(start.get("visited", False))
        end_visited = bool(end.get("visited", False))
        if start_visited and not end_visited:
            return _GuideTarget(end_xy, math.hypot(end_xy[0] - player_xy[0], end_xy[1] - player_xy[1]), projection, end_xy)
        if not start_visited and end_visited:
            return _GuideTarget(start_xy, math.hypot(start_xy[0] - player_xy[0], start_xy[1] - player_xy[1]), projection, start_xy)
        if not start_visited and not end_visited:
            start_dist = math.hypot(start_xy[0] - projection[0], start_xy[1] - projection[1])
            end_dist = math.hypot(end_xy[0] - projection[0], end_xy[1] - projection[1])
            target_xy = start_xy if start_dist <= end_dist else end_xy
            return _GuideTarget(target_xy, math.hypot(target_xy[0] - player_xy[0], target_xy[1] - player_xy[1]), projection, target_xy)

    if nearest_node is not None and nearest_node[0] > node_distance:
        return _GuideTarget(nearest_node[1], nearest_node[0], player_xy, nearest_node[1])
    return None


def _target_in_crop(
    target_xy: tuple[float, float],
    *,
    vx1: int,
    vy1: int,
    width: int,
    height: int,
) -> bool:
    local_x = target_xy[0] - vx1
    local_y = target_xy[1] - vy1
    return 0 <= local_x < width and 0 <= local_y < height


def _guide_distance_label(
    target: _GuideTarget | None,
    *,
    vx1: int,
    vy1: int,
    width: int,
    height: int,
) -> str | None:
    if target is None:
        return None
    if _target_in_crop(target.xy, vx1=vx1, vy1=vy1, width=width, height=height):
        return None
    return f"{int(round(target.distance))}px"


_GUIDE_HINT_FONT: ImageFont.ImageFont | None = None


def _guide_hint_font() -> ImageFont.ImageFont:
    global _GUIDE_HINT_FONT
    if _GUIDE_HINT_FONT is not None:
        return _GUIDE_HINT_FONT

    candidates = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simhei.ttf"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),
    ]
    for path in candidates:
        try:
            _GUIDE_HINT_FONT = ImageFont.truetype(path, _GUIDE_HINT_FONT_SIZE)
            return _GUIDE_HINT_FONT
        except Exception:
            continue
    _GUIDE_HINT_FONT = ImageFont.load_default()
    return _GUIDE_HINT_FONT


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if max_width <= 0:
        return ""
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    ellipsis = "..."
    if _text_size(draw, ellipsis, font)[0] > max_width:
        return ""
    trimmed = text
    while trimmed:
        trimmed = trimmed[:-1]
        candidate = trimmed.rstrip() + ellipsis
        if _text_size(draw, candidate, font)[0] <= max_width:
            return candidate
    return ellipsis


def _draw_spaced_direction_arrows(
    canvas,
    start_xy: tuple[float, float],
    target_xy: tuple[float, float],
    *,
    vx1: float,
    vy1: float,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    spacing: int,
    size: int,
    color: tuple[int, int, int] = _GUIDE_COLOR,
) -> None:
    sx = (start_xy[0] - vx1) * scale_x
    sy = (start_xy[1] - vy1) * scale_y
    tx = (target_xy[0] - vx1) * scale_x
    ty = (target_xy[1] - vy1) * scale_y
    dx = tx - sx
    dy = ty - sy
    distance = math.hypot(dx, dy)
    if distance <= _GUIDE_PLAYER_CLEARANCE + _GUIDE_TARGET_CLEARANCE:
        return

    ux = dx / distance
    uy = dy / distance
    spacing = max(8, spacing)
    size = max(5, size)

    cursor = float(_GUIDE_PLAYER_CLEARANCE)
    last = distance - float(_GUIDE_TARGET_CLEARANCE)
    while cursor < last:
        tip = (int(round(sx + ux * cursor)), int(round(sy + uy * cursor)))
        tail = (
            int(round(sx + ux * max(0.0, cursor - size))),
            int(round(sy + uy * max(0.0, cursor - size))),
        )
        cv2.arrowedLine(
            canvas,
            tail,
            tip,
            color,
            2,
            cv2.LINE_AA,
            tipLength=0.65,
        )
        cursor += spacing


def _draw_guide_distance_label(
    canvas,
    player_xy: tuple[float, float],
    target: _GuideTarget,
    distance_label: str,
    *,
    vx1: int,
    vy1: int,
    teleport_label: str | None = None,
) -> None:
    sx = player_xy[0] - vx1
    sy = player_xy[1] - vy1
    tx = target.xy[0] - vx1
    ty = target.xy[1] - vy1
    dx = tx - sx
    dy = ty - sy
    distance = math.hypot(dx, dy)
    if distance <= 0:
        return

    ux = dx / distance
    uy = dy / distance
    anchor_distance = min(max(54.0, distance * 0.22), max(24.0, distance - _GUIDE_TARGET_CLEARANCE))
    anchor_x = sx + ux * anchor_distance
    anchor_y = sy + uy * anchor_distance

    canvas_h, canvas_w = canvas.shape[:2]
    if canvas_w <= 20 or canvas_h <= 20:
        return

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    font = _guide_hint_font()

    right_label = (teleport_label or "").strip()
    separator = "  |  " if right_label else ""
    left_w, left_h = _text_size(draw, distance_label, font)
    sep_w, sep_h = _text_size(draw, separator, font) if separator else (0, 0)
    max_box_w = max(80, min(canvas_w - 8, 360))
    max_right_w = max_box_w - left_w - sep_w - _GUIDE_HINT_PADDING_X * 2
    right_label = _fit_text_width(draw, right_label, font, max_right_w)
    separator = "  |  " if right_label else ""
    sep_w, sep_h = _text_size(draw, separator, font) if separator else (0, 0)
    right_w, right_h = _text_size(draw, right_label, font) if right_label else (0, 0)

    text_w = left_w + sep_w + right_w
    text_h = max(left_h, sep_h, right_h)
    box_w = text_w + _GUIDE_HINT_PADDING_X * 2
    box_h = text_h + _GUIDE_HINT_PADDING_Y * 2

    offset_x = -uy * 14.0
    offset_y = ux * 14.0
    x = int(round(anchor_x + offset_x))
    y = int(round(anchor_y + offset_y))
    x = max(4, min(canvas_w - box_w - 4, x))
    y = max(4, min(canvas_h - box_h - 4, y))

    try:
        draw.rounded_rectangle(
            (x, y, x + box_w, y + box_h),
            radius=5,
            fill=_GUIDE_HINT_BG,
            outline=_GUIDE_HINT_BORDER,
            width=1,
        )
    except AttributeError:
        draw.rectangle((x, y, x + box_w, y + box_h), fill=_GUIDE_HINT_BG, outline=_GUIDE_HINT_BORDER)

    text_x = x + _GUIDE_HINT_PADDING_X
    text_y = y + _GUIDE_HINT_PADDING_Y - 1
    draw.text((text_x, text_y), distance_label, font=font, fill=(0, 0, 0, 255))
    text_x += left_w
    if separator:
        draw.text((text_x, text_y), separator, font=font, fill=(80, 80, 80, 255))
        text_x += sep_w
        draw.text((text_x, text_y), right_label, font=font, fill=(0, 0, 0, 255))

    canvas[:] = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


class RouteManager:
    def __init__(self, base_folder: str = "routes") -> None:
        self.base_folder = base_folder if os.path.isabs(base_folder) else config.app_path(base_folder)
        self.categories: list[str] = []
        self.route_groups: dict[str, list[dict]] = {}
        self.visibility: dict[str, bool] = {}
        self._color_cache: dict[str, tuple[int, int, int]] = {}
        self._route_index_by_id: dict[str, dict] = {}
        self._category_by_route_id: dict[str, str] = {}
        self._generated_route_ids: set[str] = set()
        self._teleport_points_cache: list[_TeleportPoint] | None = None
        self._point_icon_index: dict[str, str] | None = None
        self._point_icon_cache: dict[str, np.ndarray | None] = {}
        self._annotation_icon_cache: dict[str, np.ndarray | None] = {}
        self._annotation_points_cache: dict[str, list[dict]] | None = None
        self._annotation_spatial_index: dict[tuple[int, int], list[_AnnotationSpatialEntry]] | None = None
        self._annotation_coord_transform_cache: object = _UNSET
        self._annotation_type_ids: set[str] = set()
        self._resource_warning_counts: dict[str, int] = {}
        self._resource_warning_examples: dict[str, list[str]] = {}

        self._discover_categories()
        self._ensure_route_ids()
        self._load_all_routes()
        self._assign_route_colors()
        self._load_visibility()
        self._load_progress()

    def _record_resource_warning(self, key: str, example: str = "") -> None:
        self._resource_warning_counts[key] = self._resource_warning_counts.get(key, 0) + 1
        if example:
            examples = self._resource_warning_examples.setdefault(key, [])
            if len(examples) < 5 and example not in examples:
                examples.append(example)

    def _validate_route_metadata(self, route: dict, display_name: str) -> None:
        if not isinstance(route, dict):
            return
        raw_enable_versions = route.get("enable_versions")
        enable_versions = resource_metadata.normalize_enable_versions(
            raw_enable_versions if isinstance(raw_enable_versions, list) else []
        )
        if resource_metadata.APP_FORMAT_VERSION not in enable_versions:
            self._record_resource_warning("route_incompatible_version", display_name)


    def annotation_metadata_warnings(self) -> list[str]:
        rel = config.selected_annotation_file_from_settings()
        path = config.selected_annotation_path_from_settings()
        if not rel:
            return []
        if not os.path.exists(path):
            return [f"未找到标注数据文件：{rel}"]
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception as exc:
            return [f"标注数据文件读取失败：{rel} ({exc})"]
        if not isinstance(payload, dict):
            return [f"标注数据文件格式无效：{rel}"]

        return []

    def route_metadata_warnings(self) -> list[str]:
        labels = {
            "route_incompatible_version": "路线格式版本不兼容或缺失",
        }
        warnings: list[str] = []
        for key, label in labels.items():
            count = self._resource_warning_counts.get(key, 0)
            if count <= 0:
                continue
            examples = self._resource_warning_examples.get(key, [])
            suffix = f"：{', '.join(examples)}" if examples else ""
            if count > len(examples):
                suffix += f" 等 {count} 条"
            warnings.append(f"{label}{suffix}")
        return warnings

    def color_for(self, key: str) -> tuple[int, int, int]:
        route = self.route_for_id(key) if hasattr(self, "_route_index_by_id") else None
        if route is not None:
            override = _normalize_route_color_hex(route.get("color"))
            if override is not None:
                return _route_color_from_hex(override)
        if not bool(getattr(config, "ROUTE_MULTI_COLOR_ENABLED", True)):
            return _route_color_from_hex(getattr(config, "ROUTE_DEFAULT_COLOR", _DEFAULT_ROUTE_COLOR_HEX))
        if key not in self._color_cache:
            self._color_cache[key] = _color_for_key(key)
        return self._color_cache[key]

    def pointer_arrow_color(self) -> tuple[int, int, int]:
        return _config_color("ROUTE_POINTER_ARROW_COLOR", _DEFAULT_POINTER_ARROW_COLOR_HEX)

    def pointer_arrow_visible(self) -> bool:
        return _pointer_arrow_visible()

    def route_line_color(self, style: str, route_color: tuple[int, int, int]) -> tuple[int, int, int]:
        return _line_color_for_style(style, route_color)

    def teleport_points(self) -> list[_TeleportPoint]:
        if self._teleport_points_cache is None:
            self._teleport_points_cache = _load_teleport_points()
        return self._teleport_points_cache

    def point_icon_for(self, type_id: object) -> np.ndarray | None:
        key = str(type_id or "")
        if not key:
            return None
        if self._point_icon_index is None:
            self._point_icon_index = _load_point_icon_index()
        if key in self._point_icon_cache:
            return self._point_icon_cache[key]
        path = self._point_icon_index.get(key)
        icon = None
        if path and os.path.exists(path):
            icon = imread_unicode(path, cv2.IMREAD_UNCHANGED)
            if icon is not None:
                size = _config_int("ROUTE_NODE_ICON_SIZE", _POINT_ICON_SIZE, 4)
                icon = cv2.resize(icon, (size, size), interpolation=cv2.INTER_AREA)
        self._point_icon_cache[key] = icon
        return icon

    def point_icon_path_for(self, type_id: object) -> str:
        key = str(type_id or "").strip()
        if not key:
            return ""
        if self._point_icon_index is None:
            self._point_icon_index = _load_point_icon_index()
        path = self._point_icon_index.get(key, "")
        return path if path and os.path.exists(path) else ""

    def annotation_icon_for(self, type_id: object) -> np.ndarray | None:
        key = str(type_id or "").strip()
        if not key:
            return None
        if key in self._annotation_icon_cache:
            return self._annotation_icon_cache[key]
        icon = self.point_icon_for(key)
        size = _config_int("ANNOTATION_ICON_SIZE", _ANNOTATION_ICON_SIZE, 4)
        if icon is None or icon.shape[0] == size:
            self._annotation_icon_cache[key] = icon
            return icon
        resized = cv2.resize(icon, (size, size), interpolation=cv2.INTER_AREA)
        self._annotation_icon_cache[key] = resized
        return resized

    def set_annotation_type_ids(self, type_ids: Iterable[object]) -> None:
        self._annotation_type_ids = {str(type_id) for type_id in type_ids if str(type_id or "")}

    def annotation_type_ids(self) -> list[str]:
        return sorted(self._annotation_type_ids)

    def annotation_points(self) -> dict[str, list[dict]]:
        if self._annotation_points_cache is None:
            self._annotation_points_cache = _load_annotation_points()
        return self._annotation_points_cache

    def invalidate_annotation_cache(self, *, icons: bool = False) -> None:
        self._annotation_points_cache = None
        self._annotation_spatial_index = None
        self._annotation_coord_transform_cache = _UNSET
        if icons:
            self._point_icon_index = None
            self._point_icon_cache.clear()
            self._annotation_icon_cache.clear()

    def _annotation_coord_transform(self) -> dict | None:
        cached = getattr(self, "_annotation_coord_transform_cache", _UNSET)
        if cached is not _UNSET:
            return cached if isinstance(cached, dict) else None
        loaded = self._load_annotation_payload()
        payload = loaded[1] if loaded is not None else None
        transform = resource_metadata.coord_transform_from_payload(payload)
        self._annotation_coord_transform_cache = dict(transform) if isinstance(transform, dict) else None
        return transform

    def _annotation_coord_adapter(self, fallback_adapter=None):
        transform = self._annotation_coord_transform()
        if transform is None:
            return fallback_adapter
        from ui_island.views.map_coordinates import MapCoordinateAdapter

        return MapCoordinateAdapter.from_dict(transform, map_file=getattr(fallback_adapter, "map_file", None))

    def route_coordinate_adapter(self, route_ref: str, fallback_adapter=None):
        route_id = self.resolve_route_id(route_ref)
        route = self.route_for_id(route_id) if route_id is not None else None
        return _route_coord_adapter(route, fallback_adapter)

    def annotation_coordinate_adapter(self, fallback_adapter=None):
        return self._annotation_coord_adapter(fallback_adapter)

    def _annotation_spatial_entries(self) -> dict[tuple[int, int], list[_AnnotationSpatialEntry]]:
        if self._annotation_spatial_index is not None:
            return self._annotation_spatial_index

        index: dict[tuple[int, int], list[_AnnotationSpatialEntry]] = {}
        loaded = None if self._annotation_points_cache is not None else self._load_annotation_payload()
        if loaded is None:
            points_by_type = self.annotation_points()
        else:
            _file_path, payload = loaded
            points_by_type = payload.get("pointsByType", {})
            if not isinstance(points_by_type, dict):
                points_by_type = {}

        for type_id, points in points_by_type.items():
            if not isinstance(points, list):
                continue
            for point_index, point in enumerate(points):
                if not isinstance(point, dict):
                    continue
                xy = _point_xy(point)
                if xy is None:
                    continue
                cell = (
                    math.floor(xy[0] / _ANNOTATION_SPATIAL_CELL_SIZE),
                    math.floor(xy[1] / _ANNOTATION_SPATIAL_CELL_SIZE),
                )
                index.setdefault(cell, []).append(
                    _AnnotationSpatialEntry(str(type_id), point_index, point, xy)
                )
        self._annotation_spatial_index = index
        return index

    def _annotation_entries_in_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        type_ids: Iterable[str] | None = None,
        coord_adapter=None,
    ) -> list[_AnnotationSpatialEntry]:
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        selected = set(type_ids if type_ids is not None else self._annotation_type_ids)
        if not selected:
            return []

        effective_adapter = self._annotation_coord_adapter(coord_adapter)
        ix1, iy1, ix2, iy2 = _current_rect_to_internal_bounds(effective_adapter, x1, y1, x2, y2)
        index = self._annotation_spatial_entries()
        min_cell_x = math.floor(ix1 / _ANNOTATION_SPATIAL_CELL_SIZE)
        max_cell_x = math.floor(ix2 / _ANNOTATION_SPATIAL_CELL_SIZE)
        min_cell_y = math.floor(iy1 / _ANNOTATION_SPATIAL_CELL_SIZE)
        max_cell_y = math.floor(iy2 / _ANNOTATION_SPATIAL_CELL_SIZE)
        result: list[_AnnotationSpatialEntry] = []
        for cell_y in range(min_cell_y, max_cell_y + 1):
            for cell_x in range(min_cell_x, max_cell_x + 1):
                for entry in index.get((cell_x, cell_y), []):
                    if entry.type_id not in selected:
                        continue
                    current_xy = _adapter_to_current(effective_adapter, entry.xy)
                    if x1 <= current_xy[0] <= x2 and y1 <= current_xy[1] <= y2:
                        if current_xy == entry.xy:
                            result.append(entry)
                        else:
                            result.append(
                                _AnnotationSpatialEntry(
                                    entry.type_id,
                                    entry.point_index,
                                    entry.point,
                                    current_xy,
                                )
                            )
        return result

    def annotation_type_items(self) -> list[dict]:
        return _load_annotation_type_items()

    def _load_annotation_payload(self) -> tuple[str, dict] | None:
        file_path = _default_annotation_points_file()
        if not file_path:
            return None
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception as exc:
            print(f"Load annotation points failed {file_path}: {exc}")
            return None
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("types"), list) or not isinstance(payload.get("pointsByType"), dict):
            return None
        return file_path, payload

    def _write_annotation_payload(self, file_path: str, payload: dict) -> bool:
        tmp_path = f"{file_path}.tmp"
        try:
            _ensure_annotation_metadata(payload)
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            os.replace(tmp_path, file_path)
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            print(f"Write annotation points failed {file_path}: {exc}")
            return False
        self.invalidate_annotation_cache()
        return True

    @staticmethod
    def _annotation_type_meta(types: list, type_id: str) -> dict | None:
        for item in types:
            if isinstance(item, dict) and str(item.get("typeId") or "") == type_id:
                return item
        return None

    @staticmethod
    def _sync_annotation_count(types: list, points_by_type: dict, type_id: str) -> None:
        meta = RouteManager._annotation_type_meta(types, type_id)
        points = points_by_type.get(type_id)
        if meta is not None and isinstance(points, list):
            meta["count"] = len(points)

    @staticmethod
    def _new_manual_annotation_id() -> int:
        return 1_000_000_000_000 + secrets.randbelow(9_000_000_000_000)

    @staticmethod
    def new_route_point_id() -> str:
        return _new_route_point_id()

    def annotation_point(self, type_id: str, point_index: int, coord_adapter=None) -> dict | None:
        type_id = str(type_id or "").strip()
        if not type_id or not isinstance(point_index, int):
            return None
        loaded = self._load_annotation_payload()
        if loaded is None:
            return None
        _file_path, payload = loaded
        points = payload["pointsByType"].get(type_id)
        if not isinstance(points, list) or not (0 <= point_index < len(points)):
            return None
        point = points[point_index]
        if not isinstance(point, dict) or _point_xy(point) is None:
            return None
        copied = dict(point)
        effective_adapter = self._annotation_coord_adapter(coord_adapter)
        if effective_adapter is not None:
            xy = _point_xy(copied)
            if xy is not None:
                copied["x"], copied["y"] = effective_adapter.to_current(xy[0], xy[1])
        copied.setdefault("typeId", type_id)
        return copied

    def hit_test_annotation_point(
        self,
        map_x: float,
        map_y: float,
        threshold: float,
        coord_adapter=None,
    ) -> dict | None:
        if threshold <= 0 or not self._annotation_type_ids:
            return None
        best: tuple[float, str, int, dict] | None = None
        entries = self._annotation_entries_in_rect(
            map_x - threshold,
            map_y - threshold,
            map_x + threshold,
            map_y + threshold,
            coord_adapter=coord_adapter,
        )
        for entry in entries:
            dist = math.hypot(entry.xy[0] - map_x, entry.xy[1] - map_y)
            if dist > threshold:
                continue
            if best is None or dist < best[0]:
                best = (dist, entry.type_id, entry.point_index, entry.point)

        if best is None:
            return None
        dist, type_id, index, point = best
        return {
            "typeId": type_id,
            "pointIndex": index,
            "point": dict(point),
            "distance": dist,
        }

    def add_annotation_point(self, x: int, y: int, type_id: str, type_name: str, coord_adapter=None) -> bool:
        type_id = str(type_id or "").strip()
        if not type_id:
            return False

        loaded = self._load_annotation_payload()
        if loaded is None:
            return False
        file_path, payload = loaded
        types = payload["types"]
        points_by_type = payload["pointsByType"]

        type_meta = self._annotation_type_meta(types, type_id)
        if type_meta is None:
            return False

        points = points_by_type.get(type_id)
        if points is None:
            points = []
            points_by_type[type_id] = points
        if not isinstance(points, list):
            return False

        name = str(type_name or type_meta.get("type") or type_id).strip() or type_id
        effective_adapter = self._annotation_coord_adapter(coord_adapter)
        try:
            resource_x, resource_y = _adapter_to_internal(effective_adapter, (float(x), float(y)))
            point = {
                "x": int(round(resource_x)),
                "y": int(round(resource_y)),
                "label": name,
                "type": name,
                "typeId": type_id,
                "id": self._new_manual_annotation_id(),
                "manual": True,
            }
        except (TypeError, ValueError):
            return False
        points.append(point)
        self._sync_annotation_count(types, points_by_type, type_id)
        return self._write_annotation_payload(file_path, payload)

    def change_annotation_point_type(
        self,
        type_id: str,
        point_index: int,
        new_type_id: str,
        new_type_name: str,
    ) -> bool:
        type_id = str(type_id or "").strip()
        new_type_id = str(new_type_id or "").strip()
        if not type_id or not new_type_id or not isinstance(point_index, int):
            return False

        loaded = self._load_annotation_payload()
        if loaded is None:
            return False
        file_path, payload = loaded
        types = payload["types"]
        points_by_type = payload["pointsByType"]
        if self._annotation_type_meta(types, new_type_id) is None:
            return False

        old_points = points_by_type.get(type_id)
        if not isinstance(old_points, list) or not (0 <= point_index < len(old_points)):
            return False
        point = old_points[point_index]
        if not isinstance(point, dict) or _point_xy(point) is None:
            return False

        if new_type_id == type_id:
            point["typeId"] = new_type_id
            point["type"] = str(new_type_name or new_type_id).strip() or new_type_id
            point["manual"] = True
            self._sync_annotation_count(types, points_by_type, type_id)
            return self._write_annotation_payload(file_path, payload)

        new_points = points_by_type.get(new_type_id)
        if new_points is None:
            new_points = []
            points_by_type[new_type_id] = new_points
        if not isinstance(new_points, list):
            return False

        moved = dict(point)
        moved["typeId"] = new_type_id
        moved["type"] = str(new_type_name or new_type_id).strip() or new_type_id
        moved["manual"] = True
        old_points.pop(point_index)
        new_points.append(moved)
        self._sync_annotation_count(types, points_by_type, type_id)
        self._sync_annotation_count(types, points_by_type, new_type_id)
        return self._write_annotation_payload(file_path, payload)

    def delete_annotation_point(self, type_id: str, point_index: int) -> bool:
        type_id = str(type_id or "").strip()
        if not type_id or not isinstance(point_index, int):
            return False
        loaded = self._load_annotation_payload()
        if loaded is None:
            return False
        file_path, payload = loaded
        types = payload["types"]
        points_by_type = payload["pointsByType"]
        points = points_by_type.get(type_id)
        if not isinstance(points, list) or not (0 <= point_index < len(points)):
            return False
        points.pop(point_index)
        self._sync_annotation_count(types, points_by_type, type_id)
        return self._write_annotation_payload(file_path, payload)

    def create_optimized_annotation_route(self, type_id: str, type_name: str) -> dict:
        type_id = str(type_id or "").strip()
        if not type_id:
            raise ValueError("标注类型无效")

        source_name = str(type_name or type_id).strip() or type_id
        loaded = self._load_annotation_payload()
        if self._annotation_points_cache is not None:
            annotation_payload = {"pointsByType": self._annotation_points_cache}
        elif loaded is None:
            annotation_payload = {"pointsByType": self.annotation_points()}
        else:
            _file_path, annotation_payload = loaded
        points = []
        points_by_type = annotation_payload.get("pointsByType", {})
        source_points = points_by_type.get(type_id, []) if isinstance(points_by_type, dict) else []
        for point in source_points:
            if not isinstance(point, dict):
                continue
            xy = _point_xy(point)
            if xy is None:
                continue
            copied = dict(point)
            copied["x"] = int(round(xy[0]))
            copied["y"] = int(round(xy[1]))
            copied.setdefault("typeId", type_id)
            points.append(copied)

        if not points:
            raise ValueError("没有可用采集点位")

        before = total_route_length(points, loop=False)
        optimized_points = optimize_route_points(points, start=None, loop=False, passes=50)
        after = total_route_length(optimized_points, loop=False)
        reduction = (1 - after / before) * 100 if before > 0 else 0.0

        category = _ALGORITHM_CATEGORY
        category_dir = self._category_path(category)
        os.makedirs(category_dir, exist_ok=True)
        if category not in self.categories:
            self.categories.append(category)
            self.route_groups[category] = []

        base_name = _safe_route_stem(f"{source_name}{_ALGORITHM_ROUTE_SUFFIX}", f"{type_id}{_ALGORITHM_ROUTE_SUFFIX}")
        route_name, path = self._unique_route_name_and_path(category, base_name)
        route_id = self._next_route_id()
        payload = {
            "id": route_id,
            "name": route_name,
            "notes": (
                f"来源标注：{source_name}（{type_id}）；"
                f"算法生成 {len(optimized_points)} 个点位；"
                f"平面距离 {before:.0f} -> {after:.0f}（减少 {reduction:.1f}%）。"
                "规划最优不代表实际最优，因为无法考虑高低差等绕路因素，可参考自行修改节点。"
            ),
            "loop": False,
            "points": optimized_points,
        }
        _ensure_route_metadata(payload)

        self._write_json_file(path, _ordered_route_payload(payload))

        route = dict(payload)
        route["display_name"] = route_name
        for point in route.get("points", []):
            if isinstance(point, dict):
                point["visited"] = False
        self.route_groups.setdefault(category, []).append(route)
        self._route_index_by_id[route_id] = route
        self._category_by_route_id[route_id] = category
        self.visibility[route_id] = False
        return {
            "category": category,
            "name": route_name,
            "path": path,
            "id": route_id,
            "points": len(optimized_points),
            "before": before,
            "after": after,
            "reduction_percent": reduction,
        }

    def guide_hint_for_view(
        self,
        player_x: int | float | None,
        player_y: int | float | None,
        vx1: int,
        vy1: int,
        width: int,
        height: int,
        coord_adapter=None,
    ) -> dict[str, str] | None:
        if player_x is None or player_y is None:
            return None
        guide_routes = _routes_with_current_coords(self.visible_routes(), coord_adapter)
        target = _guide_target_for_player(
            guide_routes,
            (float(player_x), float(player_y)),
            _config_int("ROUTE_GUIDE_NODE_DISTANCE", 80),
            _config_int("ROUTE_GUIDE_SEGMENT_DISTANCE", 35),
            _strict_guide_mode(),
        )
        label = _guide_distance_label(
            target,
            vx1=vx1,
            vy1=vy1,
            width=width,
            height=height,
        )
        if target is None or label is None:
            return None
        teleport_label = _nearest_teleport_label(
            self.teleport_points(),
            _adapter_to_internal(coord_adapter, target.xy),
        )
        hint: dict[str, str] = {"distance_label": label}
        if teleport_label:
            hint["teleport_label"] = teleport_label
        return hint

    @staticmethod
    def route_id(route: dict) -> str:
        route_id = route.get("id")
        return route_id if isinstance(route_id, str) else ""

    def iter_routes(self) -> Iterable[tuple[str, dict]]:
        for category in self.categories:
            for route in self.route_groups[category]:
                yield category, route

    def route_for_id(self, route_id: str) -> dict | None:
        if not isinstance(route_id, str):
            return None
        return self._route_index_by_id.get(route_id)

    def category_for_route_id(self, route_id: str) -> str | None:
        if not isinstance(route_id, str):
            return None
        return self._category_by_route_id.get(route_id)

    def summarize_route(self, route_id: str) -> dict | None:
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        if route is None or category is None:
            return None
        return {
            "display_label": route.get("display_name", ""),
            "points_count": len(route.get("points", []) or []),
            "category": category,
        }

    def suggest_insertion_index(self, route_id: str, x: float, y: float, coord_adapter=None) -> int | None:
        route = self.route_for_id(route_id)
        if route is None:
            return None
        points = route.get("points", []) or []
        route_adapter = _route_coord_adapter(route, coord_adapter)
        current_points: list[dict] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            copied = dict(point)
            xy = _point_xy(copied)
            if xy is None:
                continue
            copied["x"], copied["y"] = _adapter_to_current(route_adapter, xy)
            current_points.append(copied)
        return _best_insertion_index(current_points, (x, y))

    def hit_test_point(
        self,
        map_x: float,
        map_y: float,
        threshold: float,
        route_ids: list[str] | None = None,
        coord_adapter=None,
    ) -> tuple[str, int] | None:
        """在给定 map 坐标附近查找最近的路线节点。
        route_ids=None 时只在可见路线中查找;threshold 为 map 像素距离上限。
        命中多个时返回距离最近者(相等时取遍历顺序首者)。
        """
        if threshold <= 0:
            return None

        if route_ids is None:
            candidates = [
                (self.route_id(route), route)
                for route in self.visible_routes()
            ]
        else:
            candidates = []
            for rid in route_ids:
                route = self.route_for_id(rid)
                if route is not None:
                    candidates.append((rid, route))

        best: tuple[float, str, int] | None = None
        for rid, route in candidates:
            if not rid:
                continue
            route_adapter = _route_coord_adapter(route, coord_adapter)
            points = route.get("points") or []
            for index, point in enumerate(points):
                try:
                    px = float(point["x"])
                    py = float(point["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                px, py = _adapter_to_current(route_adapter, (px, py))
                dist = math.hypot(px - map_x, py - map_y)
                if dist > threshold:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, rid, index)

        if best is None:
            return None
        return best[1], best[2]

    def delete_points_from_routes(
        self,
        deletions: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        """从多条路线批量删除指定下标的节点并写回 JSON。
        deletions: route_id -> 待删除 index 列表(重复/越界/非 int 会自动剔除)。
        返回每条路线实际删除成功的 index 列表(升序);失败或无效项返回空 list。
        删除采用从高到低 pop 避免偏移;写盘失败回滚内存状态。
        """
        outcomes: dict[str, list[int]] = {}
        any_success = False

        for route_id, raw_indexes in deletions.items():
            outcomes[route_id] = []
            route = self.route_for_id(route_id)
            category = self.category_for_route_id(route_id)
            if route is None or category is None:
                continue

            points = route.get("points")
            if not points:
                continue

            cleaned: set[int] = set()
            for item in raw_indexes or []:
                if isinstance(item, bool):
                    continue
                if not isinstance(item, int):
                    continue
                if 0 <= item < len(points):
                    cleaned.add(item)
            if not cleaned:
                continue

            descending = sorted(cleaned, reverse=True)
            popped_points: list[dict] = []
            popped_indexes: list[int] = []
            old_labels = [item.get("label", None) if isinstance(item, dict) else None for item in points]
            for idx in descending:
                popped_points.append(points.pop(idx))
                popped_indexes.append(idx)
            _apply_route_node_auto_labels(points)

            try:
                self._write_route_file(category, route.get("display_name", ""), route)
            except Exception as e:
                for idx, saved in zip(reversed(popped_indexes), reversed(popped_points)):
                    points.insert(idx, saved)
                for item, old_label in zip(points, old_labels):
                    if not isinstance(item, dict):
                        continue
                    if old_label is None:
                        item.pop("label", None)
                    else:
                        item["label"] = old_label
                print(f"Delete points write failed route_id={route_id}: {e}")
                continue

            outcomes[route_id] = sorted(cleaned)
            any_success = True

        if any_success:
            try:
                self.save_progress()
            except Exception as e:
                print(f"Save progress after delete failed: {e}")

        return outcomes

    def insert_point_into_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str],
        overrides: dict[str, int] | None = None,
        point_fields: dict | None = None,
        coord_adapter=None,
    ) -> dict[str, int | None]:
        """为每个 route_id 在最佳位置插入 (x, y) 节点并写回 JSON。
        overrides: route_id -> 强制 index(0-based),超出范围会 clamp。
        返回每个 route_id 实际插入的 index;失败为 None。
        """
        overrides = overrides or {}
        outcomes: dict[str, int | None] = {}
        any_success = False

        for route_id in route_ids:
            route = self.route_for_id(route_id)
            category = self.category_for_route_id(route_id)
            if route is None or category is None:
                outcomes[route_id] = None
                continue

            points = route.get("points")
            if points is None:
                points = []
                route["points"] = points
            route_adapter = _route_coord_adapter(route, coord_adapter)
            resource_x, resource_y = _adapter_to_internal(route_adapter, (float(x), float(y)))
            insertion_points = points
            if route_adapter is not None:
                insertion_points = []
                for point in points:
                    if not isinstance(point, dict):
                        continue
                    copied = dict(point)
                    xy = _point_xy(copied)
                    if xy is None:
                        continue
                    copied["x"], copied["y"] = route_adapter.to_current(xy[0], xy[1])
                    insertion_points.append(copied)

            if route_id in overrides:
                raw = overrides[route_id]
                try:
                    index = int(raw)
                except (TypeError, ValueError):
                    index = _best_insertion_index(insertion_points, (x, y))
                index = max(0, min(len(points), index))
            else:
                index = _best_insertion_index(insertion_points, (x, y))

            old_labels = [item.get("label", None) if isinstance(item, dict) else None for item in points]
            new_point = {"id": self.new_route_point_id()}
            for key in ("label", "type", "typeId", "radius", "sourceId", "manual", "node_type"):
                if isinstance(point_fields, dict) and key in point_fields:
                    new_point[key] = point_fields[key]
            new_point["node_type"] = _node_type(new_point)
            new_point["x"] = int(round(resource_x))
            new_point["y"] = int(round(resource_y))
            new_point["visited"] = False
            points.insert(index, new_point)
            _apply_route_node_auto_labels(points)

            try:
                self._write_route_file(category, route.get("display_name", ""), route)
            except Exception as e:
                points.pop(index)
                for item, old_label in zip(points, old_labels):
                    if not isinstance(item, dict):
                        continue
                    if old_label is None:
                        item.pop("label", None)
                    else:
                        item["label"] = old_label
                print(f"Insert point write failed route_id={route_id}: {e}")
                outcomes[route_id] = None
                continue

            outcomes[route_id] = index
            any_success = True

        if any_success:
            try:
                self.save_progress()
            except Exception as e:
                print(f"Save progress after insert failed: {e}")

        return outcomes

    def save_route_points(self, route_id: str, points: list[dict], loop: bool | None = None) -> bool:
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        if route is None or category is None:
            return False

        old_points = route.get("points", [])
        had_loop = "loop" in route
        old_loop = route.get("loop")
        normalized: list[dict] = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            copied = dict(point)
            if _point_xy(copied) is None:
                continue
            copied["x"] = int(round(float(copied["x"])))
            copied["y"] = int(round(float(copied["y"])))
            copied["visited"] = bool(copied.get("visited", False))
            normalized.append(copied)
        _apply_route_node_auto_labels(normalized)

        route["points"] = normalized
        if loop is not None:
            route["loop"] = bool(loop)
        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            route["points"] = old_points
            if loop is not None:
                if had_loop:
                    route["loop"] = old_loop
                else:
                    route.pop("loop", None)
            print(f"Save route points failed route_id={route_id}: {e}")
            return False

        try:
            self.save_progress()
        except Exception as e:
            print(f"Save progress after point save failed: {e}")
        return True

    def route_name_for_id(self, route_id: str) -> str:
        route = self.route_for_id(route_id)
        if route is None:
            return ""
        return route.get("display_name", "")

    def resolve_route_id(self, value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        if value in self._route_index_by_id:
            return value

        matches = [
            self.route_id(route)
            for _category, route in self.iter_routes()
            if route.get("display_name") == value
        ]
        matches = [route_id for route_id in matches if route_id]
        if len(matches) == 1:
            return matches[0]
        return None

    def visible_routes(self) -> list[dict]:
        return [
            route
            for _category, route in self.iter_routes()
            if self.visibility.get(self.route_id(route), False)
        ]

    def visible_route_ids(self) -> list[str]:
        return [self.route_id(route) for route in self.visible_routes() if self.route_id(route)]

    def visible_route_names(self) -> list[str]:
        return [route.get("display_name", "") for route in self.visible_routes()]

    def has_progress(self, route_ref: str) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        if route is None:
            return False
        return any(point.get("visited", False) for point in route.get("points", []))

    def point_visited(self, route_ref: str, point_index: int) -> bool | None:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return None
        route = self.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return None
        return bool(points[point_index].get("visited", False))

    def route_point_annotation_type_id(self, route_ref: str, point_index: int) -> str:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return ""
        route = self.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return ""
        point = points[point_index]
        return str(point.get("typeId") or "") if isinstance(point, dict) else ""

    def route_point_has_annotation(self, route_ref: str, point_index: int) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        if not isinstance(point, dict):
            return False
        return bool(str(point.get("typeId") or "").strip() or str(point.get("type") or "").strip())

    def set_point_position(
        self,
        route_ref: str,
        point_index: int,
        x: int | float,
        y: int | float,
        persist: bool = True,
        coord_adapter=None,
    ) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or category is None or not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        if not isinstance(point, dict):
            return False

        route_adapter = _route_coord_adapter(route, coord_adapter)
        try:
            resource_x, resource_y = _adapter_to_internal(route_adapter, (float(x), float(y)))
            next_x = int(round(resource_x))
            next_y = int(round(resource_y))
        except (TypeError, ValueError):
            return False

        old_x = point.get("x", None)
        old_y = point.get("y", None)
        point["x"] = next_x
        point["y"] = next_y
        if not persist:
            return True

        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            if old_x is None:
                point.pop("x", None)
            else:
                point["x"] = old_x
            if old_y is None:
                point.pop("y", None)
            else:
                point["y"] = old_y
            print(f"Set point position failed route_id={route_id} index={point_index}: {e}")
            return False
        return True

    def reorder_route_point(self, route_ref: str, from_index: int, to_index: int) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        points = route.get("points", []) if route is not None else []
        if (
            route is None
            or category is None
            or not isinstance(points, list)
            or not isinstance(from_index, int)
            or isinstance(from_index, bool)
            or not (0 <= from_index < len(points))
        ):
            return False
        if not points:
            return False
        if isinstance(to_index, bool):
            return False
        try:
            target = int(to_index)
        except (TypeError, ValueError):
            return False
        target = max(0, min(len(points) - 1, target))
        if from_index == target:
            return False

        old_points = [dict(item) if isinstance(item, dict) else item for item in points]
        point = points.pop(from_index)
        points.insert(target, point)
        _apply_route_node_auto_labels(points)
        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            route["points"] = old_points
            print(f"Reorder route point failed route_id={route_id} from={from_index} to={target}: {e}")
            return False

        try:
            self.save_progress()
        except Exception as e:
            print(f"Save progress after point reorder failed: {e}")
        return True

    def set_point_annotation(
        self,
        route_ref: str,
        point_index: int,
        type_id: str,
        type_name: str,
        *,
        node_type: str | None = None,
    ) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        type_id = str(type_id or "").strip()
        if not type_id:
            return False
        type_name = str(type_name or type_id).strip() or type_id
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or category is None or not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        if not isinstance(point, dict):
            return False

        old_type_id = point.get("typeId", None)
        old_type = point.get("type", None)
        old_node_type = point.get("node_type", None)
        old_labels = [item.get("label", None) if isinstance(item, dict) else None for item in points]
        point["typeId"] = type_id
        point["type"] = type_name
        if node_type is not None:
            point["node_type"] = _node_type({"node_type": node_type})
        _apply_route_node_auto_labels(points)
        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            if old_type_id is None:
                point.pop("typeId", None)
            else:
                point["typeId"] = old_type_id
            if old_type is None:
                point.pop("type", None)
            else:
                point["type"] = old_type
            if old_node_type is None:
                point.pop("node_type", None)
            else:
                point["node_type"] = old_node_type
            for item, old_label in zip(points, old_labels):
                if not isinstance(item, dict):
                    continue
                if old_label is None:
                    item.pop("label", None)
                else:
                    item["label"] = old_label
            print(f"Set point annotation failed route_id={route_id} index={point_index}: {e}")
            return False
        return True

    def clear_point_annotation(self, route_ref: str, point_index: int) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or category is None or not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        if not isinstance(point, dict):
            return False

        old_type_id = point.pop("typeId", None)
        old_type = point.pop("type", None)
        old_labels = [item.get("label", None) if isinstance(item, dict) else None for item in points]
        _apply_route_node_auto_labels(points)
        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            if old_type_id is not None:
                point["typeId"] = old_type_id
            if old_type is not None:
                point["type"] = old_type
            for item, old_label in zip(points, old_labels):
                if not isinstance(item, dict):
                    continue
                if old_label is None:
                    item.pop("label", None)
                else:
                    item["label"] = old_label
            print(f"Clear point annotation failed route_id={route_id} index={point_index}: {e}")
            return False
        return True

    def set_point_node_type(self, route_ref: str, point_index: int, node_type: str) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        category = self.category_for_route_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or category is None or not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        point = points[point_index]
        if not isinstance(point, dict):
            return False

        normalized = _node_type({"node_type": node_type})
        old_node_type = point.get("node_type", None)
        old_labels = [item.get("label", None) if isinstance(item, dict) else None for item in points]
        point["node_type"] = normalized
        _apply_route_node_auto_labels(points)
        try:
            self._write_route_file(category, route.get("display_name", ""), route)
        except Exception as e:
            if old_node_type is None:
                point.pop("node_type", None)
            else:
                point["node_type"] = old_node_type
            for item, old_label in zip(points, old_labels):
                if not isinstance(item, dict):
                    continue
                if old_label is None:
                    item.pop("label", None)
                else:
                    item["label"] = old_label
            print(f"Set point node type failed route_id={route_id} index={point_index}: {e}")
            return False
        return True

    def set_point_visited(self, route_ref: str, point_index: int, visited: bool) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            return False
        points[point_index]["visited"] = bool(visited)
        self.save_progress()
        return True

    def reload(self) -> None:
        self.save_visibility()
        self.save_progress()
        self.categories = []
        self.route_groups = {}
        self.visibility = {}
        self._color_cache = {}
        self._route_index_by_id = {}
        self._category_by_route_id = {}
        self._generated_route_ids = set()
        self._resource_warning_counts = {}
        self._resource_warning_examples = {}
        self._discover_categories()
        self._ensure_route_ids()
        self._load_all_routes()
        self._assign_route_colors()
        self._load_visibility()
        self._load_progress()

    def create_category(self, name: str) -> bool:
        category = name.strip()
        if not self._is_valid_fs_name(category):
            return False
        os.makedirs(os.path.join(self.base_folder, category), exist_ok=True)
        return True

    def rename_category(self, old_name: str, new_name: str) -> bool:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if old_name == new_name:
            return True
        if old_name not in self.categories or not self._is_valid_fs_name(new_name):
            return False

        old_path = self._category_path(old_name)
        new_path = self._category_path(new_name)
        if not os.path.isdir(old_path) or os.path.exists(new_path):
            return False

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            print(f"Rename category failed {old_path} -> {new_path}: {e}")
            return False

        index = self.categories.index(old_name)
        self.categories[index] = new_name
        moved_routes = self.route_groups.pop(old_name, [])
        self.route_groups[new_name] = moved_routes
        for route in moved_routes:
            route_id = self.route_id(route)
            if route_id:
                self._category_by_route_id[route_id] = new_name
        return True

    def delete_category(self, name: str) -> bool:
        name = name.strip()
        if name not in self.categories:
            return False

        path = self._category_path(name)
        if not os.path.isdir(path):
            return False

        for route in self.route_groups.get(name, []):
            route_id = self.route_id(route)
            if route_id:
                self.visibility.pop(route_id, None)
                self._color_cache.pop(route_id, None)
                self._route_index_by_id.pop(route_id, None)
                self._category_by_route_id.pop(route_id, None)

        try:
            shutil.rmtree(path)
        except OSError as e:
            print(f"Delete category failed {path}: {e}")
            return False

        self.categories = [category for category in self.categories if category != name]
        self.route_groups.pop(name, None)
        self.save_visibility()
        self.save_progress()
        return True

    def create_route(self, category: str, name: str) -> bool:
        name = name.strip()
        if not self._is_valid_route_name(name):
            return False
        if category not in self.categories:
            return False
        category_dir = self._category_path(category)
        if not os.path.isdir(category_dir):
            return False
        path = self._route_file_path(category, name)
        if os.path.exists(path):
            return False

        payload = {
            "id": self._next_route_id(),
            "name": name,
            "notes": "",
            "loop": False,
            "points": [],
        }
        _ensure_route_metadata(payload)
        try:
            self._write_json_file(path, _ordered_route_payload(payload))
        except Exception as e:
            print(f"Create route failed {path}: {e}")
            return False
        return True

    def rename_route(self, category: str, old_name: str, new_name: str) -> bool:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not self._is_valid_route_name(new_name):
            return False
        if old_name == new_name:
            return True

        route = self._find_route(category, old_name)
        if route is None:
            return False

        old_path = self._route_file_path(category, old_name)
        new_path = self._route_file_path(category, new_name)
        if not os.path.exists(old_path) or os.path.exists(new_path):
            return False

        old_route_name = route.get("name", old_name)
        try:
            os.replace(old_path, new_path)
            route["display_name"] = new_name
            route["name"] = new_name
            route.setdefault("notes", "")
            self._write_route_file(category, new_name, route)
        except Exception as e:
            route["display_name"] = old_name
            route["name"] = old_route_name
            if os.path.exists(new_path) and not os.path.exists(old_path):
                try:
                    os.replace(new_path, old_path)
                except OSError:
                    pass
            print(f"Rename route failed {old_path} -> {new_path}: {e}")
            return False
        self.save_visibility()
        self.save_progress()
        return True

    def delete_route(self, category: str, name: str) -> bool:
        name = name.strip()
        routes = self.route_groups.get(category)
        if routes is None:
            return False

        route_index = next(
            (index for index, route in enumerate(routes) if route.get("display_name") == name),
            None,
        )
        if route_index is None:
            return False

        route = routes[route_index]
        route_id = self.route_id(route)
        path = self._route_file_path(category, name)
        if os.path.exists(path):
            os.remove(path)

        routes.pop(route_index)
        if route_id:
            self.visibility.pop(route_id, None)
            self._color_cache.pop(route_id, None)
            self._route_index_by_id.pop(route_id, None)
            self._category_by_route_id.pop(route_id, None)
        self.save_visibility()
        self.save_progress()
        return True

    def route_file_path(self, category: str, name: str) -> str:
        return self._route_file_path(category, name)

    def category_path(self, category: str) -> str:
        return self._category_path(category)

    def _unique_route_name_and_path(self, category: str, base_name: str) -> tuple[str, str]:
        route_name = base_name
        path = self._route_file_path(category, route_name)
        index = 2
        while os.path.exists(path):
            route_name = f"{base_name} {index}"
            path = self._route_file_path(category, route_name)
            index += 1
        return route_name, path

    def get_route_notes(self, category: str, name: str) -> str:
        route = self._find_route(category, name)
        if route is None:
            return ""
        notes = route.get("notes", "")
        if notes is None:
            return ""
        return notes if isinstance(notes, str) else str(notes)

    def route_enable_versions(self, route_ref: str) -> list[str] | None:
        route_id = self.resolve_route_id(route_ref)
        route = self.route_for_id(route_id) if route_id is not None else None
        if route is None:
            return None
        if "enable_versions" not in route and not resource_metadata.format_version_as_enable_version(route):
            return None
        return resource_metadata.enable_versions_with_format_version(route)

    def update_route_enable_versions(self, route_ref: str, versions: list[str]) -> bool:
        route_id = self.resolve_route_id(route_ref)
        route = self.route_for_id(route_id) if route_id is not None else None
        category = self.category_for_route_id(route_id) if route_id is not None else None
        if route is None or category is None:
            return False

        had_enable_versions = "enable_versions" in route
        old_enable_versions = route.get("enable_versions", None)
        cleaned = resource_metadata.normalize_enable_versions(versions)
        route["enable_versions"] = cleaned
        try:
            self._write_route_file(
                category,
                route.get("display_name", ""),
                route,
                preserve_manual_enable_versions=True,
            )
        except Exception as e:
            if had_enable_versions:
                route["enable_versions"] = old_enable_versions
            else:
                route.pop("enable_versions", None)
            print(f"Save route enable_versions failed route_id={route_id}: {e}")
            return False
        return True

    def add_current_route_enable_version(self, route_ref: str) -> bool:
        route_id = self.resolve_route_id(route_ref)
        route = self.route_for_id(route_id) if route_id is not None else None
        category = self.category_for_route_id(route_id) if route_id is not None else None
        if route is None or category is None:
            return False

        current = resource_metadata.APP_FORMAT_VERSION
        had_enable_versions = "enable_versions" in route
        old_enable_versions = route.get("enable_versions", None)
        enable_versions = resource_metadata.normalize_enable_versions(
            old_enable_versions if isinstance(old_enable_versions, list) else []
        )
        if current in enable_versions:
            return True

        route["enable_versions"] = [*enable_versions, current]
        try:
            self._write_route_file(
                category,
                route.get("display_name", ""),
                route,
                preserve_manual_enable_versions=True,
            )
        except Exception as e:
            if had_enable_versions:
                route["enable_versions"] = old_enable_versions
            else:
                route.pop("enable_versions", None)
            print(f"Save route current enable_version failed route_id={route_id}: {e}")
            return False
        return True

    def route_color_override(self, route_ref: str) -> str:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return ""
        route = self.route_for_id(route_id)
        if route is None:
            return ""
        return _normalize_route_color_hex(route.get("color")) or ""

    def update_route_notes(self, category: str, name: str, notes: str) -> bool:
        route = self._find_route(category, name)
        if route is None:
            return False

        route["notes"] = notes
        route.setdefault("name", name)
        try:
            self._write_route_file(category, name, route)
        except Exception as e:
            print(f"Save route notes failed {self._route_file_path(category, name)}: {e}")
            return False
        return True

    def update_route_coord_transform(
        self,
        route_ref: str,
        coord_transform: dict | None,
    ) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        if route is None:
            return False
        category = self.category_for_route_id(route_id)
        name = route.get("display_name") or route.get("name")
        if not category or not name:
            return False
        previous = route.get("coord_transform")
        had_previous = "coord_transform" in route
        resource_metadata.apply_coord_transform_to_payload(route, coord_transform)
        try:
            self._write_route_file(category, name, route)
        except Exception as e:
            if had_previous:
                route["coord_transform"] = previous
            else:
                route.pop("coord_transform", None)
            print(f"Save route coord_transform failed {self._route_file_path(category, name)}: {e}")
            return False
        return True

    def save_route_calibration(
        self,
        route_ref: str,
        coord_transform: dict | None,
    ) -> bool:
        route_id = self.resolve_route_id(route_ref)
        if route_id is None:
            return False
        route = self.route_for_id(route_id)
        if route is None:
            return False
        category = self.category_for_route_id(route_id)
        name = route.get("display_name") or route.get("name")
        if not category or not name:
            return False

        had_transform = "coord_transform" in route
        previous_transform = route.get("coord_transform")
        had_enable_versions = "enable_versions" in route
        previous_enable_versions = route.get("enable_versions")

        resource_metadata.apply_coord_transform_to_payload(route, coord_transform)
        enable_versions = resource_metadata.normalize_enable_versions(
            previous_enable_versions if isinstance(previous_enable_versions, list) else []
        )
        current_version = resource_metadata.APP_FORMAT_VERSION
        if current_version not in enable_versions:
            enable_versions.append(current_version)
        route["enable_versions"] = enable_versions

        try:
            self._write_route_file(
                category,
                name,
                route,
                preserve_manual_enable_versions=True,
            )
        except Exception as e:
            if had_transform:
                route["coord_transform"] = previous_transform
            else:
                route.pop("coord_transform", None)
            if had_enable_versions:
                route["enable_versions"] = previous_enable_versions
            else:
                route.pop("enable_versions", None)
            print(f"Save route calibration failed {self._route_file_path(category, name)}: {e}")
            return False
        return True

    def save_annotation_calibration(
        self,
        annotation_path: str,
        coord_transform: dict | None,
    ) -> bool:
        file_path = os.fspath(annotation_path or "")
        if not file_path or not os.path.isfile(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception as exc:
            print(f"Load annotation calibration failed {file_path}: {exc}")
            return False
        if not isinstance(payload, dict):
            return False
        resource_metadata.apply_coord_transform_to_payload(payload, coord_transform)
        return self._write_annotation_payload(file_path, payload)

    def route_coord_transform(self, route_ref: str) -> dict | None:
        route = self.route_for_id(route_ref)
        if route is None:
            return None
        return resource_metadata.coord_transform_from_payload(route)

    def update_route_notes_and_color(
        self,
        category: str,
        name: str,
        notes: str,
        color: object | None,
    ) -> bool:
        route = self._find_route(category, name)
        if route is None:
            return False

        normalized_color = None
        if color is not None and str(color).strip() != "":
            normalized_color = _normalize_route_color_hex(color)
            if normalized_color is None:
                return False

        old_notes = route.get("notes", None)
        had_color = "color" in route
        old_color = route.get("color", None)
        route["notes"] = notes
        route.setdefault("name", name)
        if color is None or str(color).strip() == "":
            route.pop("color", None)
        else:
            route["color"] = normalized_color
        try:
            self._write_route_file(category, name, route)
        except Exception as e:
            if old_notes is None:
                route.pop("notes", None)
            else:
                route["notes"] = old_notes
            if had_color:
                route["color"] = old_color
            else:
                route.pop("color", None)
            print(f"Save route notes failed {self._route_file_path(category, name)}: {e}")
            return False
        return True

    def draw_on(
        self,
        canvas,
        vx1,
        vy1,
        view_size,
        player_x=None,
        player_y=None,
        drawing_route: dict | None = None,
        auto_visit: bool = True,
        coord_adapter=None,
        viewport_width: int | float | None = None,
        viewport_height: int | float | None = None,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        map_pixels_per_screen_px: float | None = None,
        skip_annotations: bool = False,
    ) -> None:
        scale_x = float(scale_x or 1.0)
        scale_y = float(scale_y or 1.0)
        vx1 = float(vx1)
        vy1 = float(vy1)
        canvas_height, canvas_width = canvas.shape[:2]
        if viewport_width is None:
            viewport_width = canvas_width / max(scale_x, 1e-6)
        if viewport_height is None:
            viewport_height = canvas_height / max(scale_y, 1e-6)
        viewport_width = float(viewport_width)
        viewport_height = float(viewport_height)

        player_xy: tuple[float, float] | None = None
        local_player = None
        if player_x is not None and player_y is not None:
            player_xy = (float(player_x), float(player_y))
            local_player = _map_to_canvas_point(player_xy, vx1, vy1, scale_x, scale_y)

        if map_pixels_per_screen_px is None:
            map_pixels_per_screen_px = max(1.0 / max(scale_x, 1e-6), 1.0 / max(scale_y, 1e-6))
        if not skip_annotations:
            self._draw_annotations(
                canvas,
                vx1,
                vy1,
                canvas_width,
                canvas_height,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                scale_x=scale_x,
                scale_y=scale_y,
                map_pixels_per_screen_px=float(map_pixels_per_screen_px),
                coord_adapter=coord_adapter,
            )
        visible_routes = [
            route
            for _category, route in self.iter_routes()
            if self.route_id(route) and self.visibility.get(self.route_id(route), False)
        ]
        guide_routes = list(visible_routes)
        if drawing_route is not None:
            drawing_route_id = self.route_id(drawing_route)
            if bool(drawing_route.get("_hide_other_routes")):
                visible_routes = []
            elif drawing_route_id:
                visible_routes = [
                    route for route in visible_routes if self.route_id(route) != drawing_route_id
                ]
            visible_routes.append(drawing_route)

        draw_records: list[
            tuple[
                dict,
                tuple[int, int, int],
                list[tuple[int, int] | None],
                list[tuple[float, float] | None],
                list[dict],
                bool,
            ]
        ] = []

        for route in visible_routes:
            route_id = self.route_id(route)
            route_adapter = _route_coord_adapter(route, coord_adapter)
            points = route.get("points", [])
            color = self.color_for(route_id)
            local_points: list[tuple[int, int] | None] = []
            map_points: list[tuple[float, float] | None] = []
            for point in points:
                xy = _point_xy(point) if isinstance(point, dict) else None
                if xy is None:
                    local_points.append(None)
                    map_points.append(None)
                else:
                    current_xy = _adapter_to_current(route_adapter, xy)
                    map_points.append(current_xy)
                    local_points.append(_map_to_canvas_point(current_xy, vx1, vy1, scale_x, scale_y))
            is_drawing_route = drawing_route is not None and route is drawing_route
            draw_records.append((route, color, local_points, map_points, points, is_drawing_route))

            if bool(route.get("_annotation_calibration")):
                continue
            for index in range(len(local_points) - 1):
                start = local_points[index]
                end = local_points[index + 1]
                if start is None or end is None:
                    continue
                next_type = _node_type(points[index + 1] if index + 1 < len(points) else None)
                _draw_styled_line(canvas, start, end, self.route_line_color(next_type, color), style=next_type)
            if route.get("loop") and len(local_points) > 2:
                start = local_points[-1]
                end = local_points[0]
                if start is not None and end is not None:
                    style = _node_type(points[0] if points else None)
                    _draw_styled_line(canvas, start, end, self.route_line_color(style, color), style=style)

        for _route, _color, _local_points, map_points, points, is_drawing_route in draw_records:
            if is_drawing_route:
                continue
            for index, (map_point, point_data) in enumerate(zip(map_points, points)):
                if map_point is None:
                    continue

                visited = point_data.get("visited", False)
                if auto_visit and not visited and player_xy is not None:
                    dist = math.hypot(map_point[0] - player_xy[0], map_point[1] - player_xy[1])
                    if dist < _CLOSE_THRESHOLD:
                        point_data["visited"] = True

        if player_x is not None and player_y is not None:
            guide_current_routes = _routes_with_current_coords(guide_routes, coord_adapter)
            target = _guide_target_for_player(
                guide_current_routes,
                (float(player_x), float(player_y)),
                _config_int("ROUTE_GUIDE_NODE_DISTANCE", 80),
                _config_int("ROUTE_GUIDE_SEGMENT_DISTANCE", 35),
                _strict_guide_mode(),
            )
            if target is not None and self.pointer_arrow_visible():
                _draw_spaced_direction_arrows(
                    canvas,
                    target.arrow_start_xy or (float(player_x), float(player_y)),
                    target.arrow_target_xy or target.xy,
                    vx1=vx1,
                    vy1=vy1,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    spacing=_config_int("ROUTE_GUIDE_POINTER_SPACING", 28, 8),
                    size=_config_int("ROUTE_GUIDE_POINTER_SIZE", 10, 5),
                    color=self.pointer_arrow_color(),
                )
        for _route, color, local_points, _map_points, points, _is_drawing_route in draw_records:
            is_annotation_calibration = bool(_route.get("_annotation_calibration"))
            for index, (local_point, point_data) in enumerate(zip(local_points, points)):
                if local_point is None:
                    continue
                if not (0 <= local_point[0] <= canvas_width and 0 <= local_point[1] <= canvas_height):
                    continue

                visited = point_data.get("visited", False)
                point_icon = (
                    self.annotation_icon_for(point_data.get("typeId"))
                    if is_annotation_calibration
                    else self.point_icon_for(point_data.get("typeId"))
                )
                visited_point_opacity = _config_opacity("ROUTE_VISITED_POINT_OPACITY", 1.0)
                visited_icon_opacity = _config_opacity("ROUTE_VISITED_ICON_OPACITY", _POINT_ICON_VISITED_ALPHA)

                if visited:
                    dot_color = (45, 45, 45)
                    border_color = (90, 90, 90)
                    text_color = (170, 170, 170) if point_icon is not None else (100, 100, 100)
                else:
                    dot_color = color
                    border_color = (255, 255, 255)
                    text_color = color

                if point_icon is not None:
                    _overlay_bgra_icon(
                        canvas,
                        point_icon,
                        local_point,
                        opacity=visited_icon_opacity if visited else 1.0,
                    )
                else:
                    opacity = visited_point_opacity if visited else 1.0
                    dot_radius = _config_int("ROUTE_NODE_DOT_SIZE", 5, 1)
                    _draw_circle_with_opacity(canvas, local_point, dot_radius, dot_color, -1, opacity)
                    _draw_circle_with_opacity(canvas, local_point, dot_radius, border_color, 1, opacity)

                if is_annotation_calibration:
                    continue
                if not _config_bool("ROUTE_NODE_ORDER_VISIBLE", True):
                    continue

                label = str(index + 1)
                text_x = local_point[0] + (10 if point_icon is not None else 7)
                text_y = local_point[1] - (9 if point_icon is not None else 4)
                cv2.putText(
                    canvas,
                    label,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    canvas,
                    label,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    text_color,
                    1,
                    cv2.LINE_AA,
                )

    def _draw_annotations(
        self,
        canvas,
        vx1,
        vy1,
        canvas_width: int,
        canvas_height: int,
        *,
        viewport_width: int | float | None = None,
        viewport_height: int | float | None = None,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        map_pixels_per_screen_px: float = 1.0,
        coord_adapter=None,
    ) -> None:
        if not self._annotation_type_ids:
            return
        scale_x = float(scale_x or 1.0)
        scale_y = float(scale_y or 1.0)
        if viewport_width is None:
            viewport_width = canvas_width / max(scale_x, 1e-6)
        if viewport_height is None:
            viewport_height = canvas_height / max(scale_y, 1e-6)

        pad_x, pad_y = _map_rect_padding_for_screen(
            _ANNOTATION_QUERY_PADDING_SCREEN_PX,
            scale_x,
            scale_y,
        )
        entries = self._annotation_entries_in_rect(
            float(vx1) - pad_x,
            float(vy1) - pad_y,
            float(vx1) + float(viewport_width) + pad_x,
            float(vy1) + float(viewport_height) + pad_y,
            coord_adapter=coord_adapter,
        )
        if not entries:
            return

        should_cluster = (
            float(map_pixels_per_screen_px) >= _ANNOTATION_CLUSTER_RATIO_THRESHOLD
            or len(entries) > _ANNOTATION_CLUSTER_VISIBLE_THRESHOLD
        )
        if should_cluster:
            self._draw_annotation_clusters(canvas, entries, float(vx1), float(vy1), scale_x, scale_y)
            return

        for entry in entries:
            icon = self.annotation_icon_for(entry.type_id)
            if icon is None:
                continue
            local_point = _map_to_canvas_point(entry.xy, float(vx1), float(vy1), scale_x, scale_y)
            if not (
                -_ANNOTATION_ICON_SIZE <= local_point[0] <= canvas_width + _ANNOTATION_ICON_SIZE
                and -_ANNOTATION_ICON_SIZE <= local_point[1] <= canvas_height + _ANNOTATION_ICON_SIZE
            ):
                continue
            _overlay_bgra_icon(canvas, icon, local_point, opacity=1.0)

    def _draw_annotation_clusters(
        self,
        canvas,
        entries: list[_AnnotationSpatialEntry],
        vx1: float,
        vy1: float,
        scale_x: float,
        scale_y: float,
    ) -> None:
        canvas_height, canvas_width = canvas.shape[:2]
        clusters: dict[tuple[int, int], list[tuple[_AnnotationSpatialEntry, tuple[int, int]]]] = {}
        for entry in entries:
            local_point = _map_to_canvas_point(entry.xy, vx1, vy1, scale_x, scale_y)
            if not (
                -_ANNOTATION_CLUSTER_GRID_PX <= local_point[0] <= canvas_width + _ANNOTATION_CLUSTER_GRID_PX
                and -_ANNOTATION_CLUSTER_GRID_PX <= local_point[1] <= canvas_height + _ANNOTATION_CLUSTER_GRID_PX
            ):
                continue
            key = (
                int(math.floor(local_point[0] / _ANNOTATION_CLUSTER_GRID_PX)),
                int(math.floor(local_point[1] / _ANNOTATION_CLUSTER_GRID_PX)),
            )
            clusters.setdefault(key, []).append((entry, local_point))

        for members in clusters.values():
            if len(members) == 1:
                entry, local_point = members[0]
                icon = self.annotation_icon_for(entry.type_id)
                if icon is not None:
                    _overlay_bgra_icon(canvas, icon, local_point, opacity=1.0)
                continue

            count = len(members)
            cx = int(round(sum(point[0] for _entry, point in members) / count))
            cy = int(round(sum(point[1] for _entry, point in members) / count))
            radius = max(10, min(18, 8 + len(str(count)) * 4))
            cv2.circle(canvas, (cx, cy), radius + 2, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(canvas, (cx, cy), radius, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(canvas, (cx, cy), radius, (30, 30, 30), 1, cv2.LINE_AA)
            label = str(count)
            font_scale = 0.42 if count < 100 else 0.36
            (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            cv2.putText(
                canvas,
                label,
                (cx - text_w // 2, cy + (text_h - baseline) // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

    def _assign_route_colors(self) -> None:
        all_route_ids = sorted(
            self.route_id(route)
            for _category, route in self.iter_routes()
            if self.route_id(route)
        )
        for index, route_id in enumerate(all_route_ids):
            hue = (index * 0.618033988749895) % 1.0
            sat = 0.82 + (index % 4) * 0.045
            val = 0.92 + (index % 2) * 0.07
            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            self._color_cache[route_id] = (int(b * 255), int(g * 255), int(r * 255))

    def _discover_categories(self) -> None:
        if not os.path.isdir(self.base_folder):
            os.makedirs(self.base_folder, exist_ok=True)

        found: list[str] = []
        for entry in sorted(os.listdir(self.base_folder)):
            full_path = os.path.join(self.base_folder, entry)
            if os.path.isdir(full_path):
                found.append(entry)

        self.categories = found
        self.route_groups = {category: [] for category in self.categories}

    def _ensure_route_ids(self) -> None:
        route_files = sorted(
            self._iter_route_files(),
            key=lambda item: (item[2], item[1].casefold()),
        )
        if not route_files:
            return

        used_ids: set[str] = set()
        pending_updates: list[tuple[str, dict]] = []

        for _category, path, _created_at in route_files:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception as e:
                print(f"Load route for id migration failed {path}: {e}")
                continue

            route_id = data.get("id")
            if _has_external_edges(data) and (not self._is_valid_route_id(route_id) or route_id in used_ids):
                continue
            if self._is_valid_route_id(route_id) and route_id not in used_ids:
                used_ids.add(route_id)
                continue

            pending_updates.append((path, data))

        for path, data in pending_updates:
            route_id = self._allocate_route_id(used_ids)
            data["id"] = route_id
            try:
                self._write_json_file(path, _ordered_route_payload(data))
            except Exception as e:
                print(f"Write route id migration failed {path}: {e}")

    def _load_all_routes(self) -> None:
        used_ids: set[str] = set()

        for category in self.categories:
            category_path = self._category_path(category)
            for path in glob.glob(os.path.join(category_path, "*.json")):
                try:
                    file_name = os.path.basename(path)
                    if file_name in {_PROGRESS_FILE, _VISIBILITY_FILE}:
                        continue

                    route_name = os.path.splitext(file_name)[0]
                    with open(path, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                    self._validate_route_metadata(data, route_name)

                    has_edges = _has_external_edges(data)
                    if has_edges:
                        external_points = _external_nodes_as_points(data)
                        if external_points is not None:
                            data["_gmt_points_from_nodes"] = True
                            data["_gmt_had_original_points"] = "points" in data
                            data["_gmt_original_points"] = data.get("points")
                            data["points"] = external_points

                    route_id = data.get("id")
                    if not self._is_valid_route_id(route_id) or route_id in used_ids:
                        route_id = self._allocate_route_id(used_ids)
                        data["id"] = route_id
                        if not has_edges:
                            self._write_json_file(path, _ordered_route_payload(data))
                    else:
                        used_ids.add(route_id)

                    data.setdefault("name", route_name)
                    data.setdefault("notes", "")
                    data["display_name"] = route_name
                    for point in data.get("points", []):
                        point["visited"] = False

                    self.route_groups[category].append(data)
                    self._route_index_by_id[route_id] = data
                    self._category_by_route_id[route_id] = category
                    self.visibility[route_id] = False
                except Exception as e:
                    print(f"Load route failed {path}: {e}")

    def _progress_path(self) -> str:
        return os.path.join(self.base_folder, _PROGRESS_FILE)

    def _visibility_path(self) -> str:
        return os.path.join(self.base_folder, _VISIBILITY_FILE)

    def _load_visibility(self) -> None:
        path = self._visibility_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as e:
            print(f"Read route visibility failed: {e}")
            return

        if not isinstance(data, list):
            return

        for item in data:
            route_id = self.resolve_route_id(item)
            if route_id is not None:
                self.visibility[route_id] = True

    def _load_progress(self) -> None:
        path = self._progress_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as e:
            print(f"Read route progress failed: {e}")
            return

        if not isinstance(data, dict):
            return

        for route_ref, visited_indexes in data.items():
            route_id = self.resolve_route_id(route_ref)
            if route_id is None:
                continue
            route = self.route_for_id(route_id)
            if route is None or not isinstance(visited_indexes, list):
                continue
            for index in visited_indexes:
                if 0 <= index < len(route.get("points", [])):
                    route["points"][index]["visited"] = True

    def save_progress(self) -> None:
        data: dict[str, list[int]] = {}
        for _category, route in self.iter_routes():
            route_id = self.route_id(route)
            visited = [
                index
                for index, point in enumerate(route.get("points", []))
                if point.get("visited", False)
            ]
            if route_id and visited:
                data[route_id] = visited
        try:
            with open(self._progress_path(), "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save route progress failed: {e}")

    def reset_progress(self, route_ref: str | None = None) -> None:
        route_id = self.resolve_route_id(route_ref) if route_ref is not None else None
        for _category, route in self.iter_routes():
            if route_id is not None and self.route_id(route) != route_id:
                continue
            for point in route.get("points", []):
                point["visited"] = False
        self.save_progress()

    def save_visibility(self) -> None:
        try:
            with open(self._visibility_path(), "w", encoding="utf-8") as handle:
                json.dump(self.visible_route_ids(), handle, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save route visibility failed: {e}")

    def _route_file_path(self, category: str, name: str) -> str:
        return os.path.join(self.base_folder, category, f"{name}.json")

    def _category_path(self, category: str) -> str:
        return os.path.join(self.base_folder, category)

    def _write_route_file(
        self,
        category: str,
        name: str,
        route: dict,
        *,
        preserve_manual_enable_versions: bool = False,
    ) -> None:
        path = self._route_file_path(category, name)
        route_id = self.route_id(route)
        if not route_id:
            route_id = self._next_route_id()
            route["id"] = route_id
        payload = self._serialize_route(
            route,
            name,
            route_id,
            preserve_manual_enable_versions=preserve_manual_enable_versions,
        )
        self._write_json_file(path, payload)

    @staticmethod
    def _serialize_route(
        route: dict,
        default_name: str,
        route_id: str,
        *,
        preserve_manual_enable_versions: bool = False,
    ) -> dict:
        payload = {
            key: value
            for key, value in route.items()
            if key != "display_name" and not str(key).startswith("_gmt_")
        }
        payload["id"] = route_id
        payload["name"] = payload.get("name") or default_name
        notes = payload.get("notes", "")
        payload["notes"] = "" if notes is None else (notes if isinstance(notes, str) else str(notes))
        payload.pop("annotation_hash", None)
        if preserve_manual_enable_versions:
            resource_metadata.ensure_metadata(
                payload,
                include_id=False,
                include_route_defaults=True,
                preserve_format_version=True,
                enable_versions_policy="preserve",
            )
        else:
            _ensure_existing_route_metadata(payload)
        if "color" in payload:
            normalized_color = _normalize_route_color_hex(payload.get("color"))
            if normalized_color is None:
                payload.pop("color", None)
            else:
                payload["color"] = normalized_color

        point_key = "nodes" if route.get("_gmt_points_from_nodes") and "nodes" in payload else "points"
        points: list[object] = []
        for point in route.get("points", []):
            if isinstance(point, dict):
                points.append({key: value for key, value in point.items() if key != "visited"})
            else:
                points.append(point)
        payload[point_key] = points
        if point_key == "nodes":
            if route.get("_gmt_had_original_points"):
                payload["points"] = route.get("_gmt_original_points")
            else:
                payload.pop("points", None)
        return _ordered_route_payload(payload)

    def _find_route(self, category: str, name: str) -> dict | None:
        for route in self.route_groups.get(category, []):
            if route.get("display_name") == name:
                return route
        return None

    def _iter_route_files(self) -> list[tuple[str, str, float]]:
        items: list[tuple[str, str, float]] = []
        for category in self.categories:
            category_path = self._category_path(category)
            for path in glob.glob(os.path.join(category_path, "*.json")):
                if os.path.basename(path) in {_PROGRESS_FILE, _VISIBILITY_FILE}:
                    continue
                items.append((category, path, self._route_file_timestamp(path)))
        return items

    @staticmethod
    def _route_file_timestamp(path: str) -> float:
        try:
            return os.path.getctime(path)
        except OSError:
            try:
                return os.path.getmtime(path)
            except OSError:
                return time.time()

    def _allocate_route_id(self, used_ids: set[str]) -> str:
        route_id = self._new_random_route_id()
        while route_id in used_ids:
            route_id = self._new_random_route_id()
        used_ids.add(route_id)
        return route_id

    def _next_route_id(self) -> str:
        used_ids = set(self._route_index_by_id) | self._generated_route_ids
        route_id = self._allocate_route_id(used_ids)
        self._generated_route_ids.add(route_id)
        return route_id

    @staticmethod
    def _new_random_route_id() -> str:
        return str(1_000_000_000_000 + secrets.randbelow(9_000_000_000_000))

    @staticmethod
    def _write_json_file(path: str, payload: dict) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    @staticmethod
    def _is_valid_fs_name(name: str) -> bool:
        if not name or name in {".", ".."}:
            return False
        if any(char in name for char in _INVALID_FILE_NAME_CHARS):
            return False
        if name.endswith((" ", ".")):
            return False
        return True

    def _is_valid_route_name(self, name: str) -> bool:
        if not self._is_valid_fs_name(name):
            return False
        return f"{name}.json" not in {_PROGRESS_FILE, _VISIBILITY_FILE}

    @staticmethod
    def _is_valid_route_id(value: object) -> bool:
        if not isinstance(value, str):
            return False
        raw = value.strip()
        if len(raw) >= 10 and raw.isdigit():
            return True
        return bool(resource_metadata.HASH_RE.fullmatch(raw.casefold()))

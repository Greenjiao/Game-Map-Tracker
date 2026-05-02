"""Convert sift2 resource point files into GMT-N annotations."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import OrderedDict
from pathlib import Path

from tools.annotation_converters.base import UnsupportedAnnotationFormatError
from tools.annotation_converters.registry import register_outside_converter

FORMAT_VERSION = "sift2"

_ROCOPATH_LON_SCALE = 5824.0800
_ROCOPATH_LON_OFFSET = 7217.5810
_ROCOPATH_LAT_SCALE = 5822.8413
_ROCOPATH_LAT_OFFSET = 6602.7721

_TILE_SIZE = 256
_MAP_ZOOM = 13
_MAP_TILE_ORIGIN_X = 4064
_MAP_TILE_ORIGIN_Y = 4064
_MAP_PIXEL_SIZE = 8192

_LABEL_INDEX_RE = re.compile(r"\s+\d+$")

ROCOPATH_TO_GMT_TYPE_IDS = {
    "5511": "17310030043",
    "5512": "17310030045",
    "5513": "17310030044",
    "5514": "17310030046",
    "5549": "17310030002",
    "5575": "17310030050",
    "5576": "17310030051",
    "5577": "17310030055",
    "5579": "17310030057",
    "5580": "17310030058",
    "5581": "17310030059",
    "5582": "17310030075",
    "5583": "17310030060",
    "5584": "17310030062",
    "5585": "17310030063",
    "5586": "17310030064",
    "5587": "17310030065",
    "5588": "17310030078",
    "5589": "17310030079",
    "5590": "17310030068",
    "5591": "17310030069",
    "5592": "17310030071",
    "5593": "17310030074",
    "5594": "17310030073",
    "5595": "17310030061",
    "5596": "17310030066",
    "5597": "17310030067",
    "5598": "17310030053",
    "5599": "17310030052",
    "5600": "17310030049",
    "5601": "17310030077",
    "5602": "17310030070",
    "5603": "17310030072",
    "5609": "17310030083",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _candidate_gmt_type_index_paths() -> list[Path]:
    roots: list[Path] = []
    try:
        import config

        roots.append(Path(config.BASE_DIR))
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)

    roots.append(_project_root())

    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        path = root / "tools" / "points_icon" / "icons.json"
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _gmt_type_index_path() -> Path:
    candidates = _candidate_gmt_type_index_paths()
    for path in candidates:
        if path.is_file():
            return path
    detail = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"tools/points_icon/icons.json 不存在，已尝试：{detail}")


def _load_gmt_type_items() -> dict[str, dict]:
    path = _gmt_type_index_path()
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("tools/points_icon/icons.json 必须是列表")

    result: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "").strip()
        if not type_id or type_id in result:
            continue
        result[type_id] = {
            "typeId": type_id,
            "type": str(item.get("type") or type_id),
            "groupId": str(item.get("groupId") or ""),
            "group": str(item.get("group") or ""),
            "iconPath": str(item.get("iconPath") or f"{type_id}.png"),
        }
    return result


def _source_id(value: object) -> object:
    if isinstance(value, str):
        clean = value.strip()
        if clean.isdigit():
            return int(clean)
        return clean
    return value


def _number(value: object, field: str, source_id: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"sift2 点位 {source_id or '<无 id>'} 缺少有效 {field}")
    return value


def _rocopath_xy_to_latlng(x: float, y: float) -> tuple[float, float]:
    longitude = (float(x) - _ROCOPATH_LON_OFFSET) / _ROCOPATH_LON_SCALE
    latitude = (_ROCOPATH_LAT_OFFSET - float(y)) / _ROCOPATH_LAT_SCALE
    return latitude, longitude


def _latlng_to_gmt_xy(latitude: float, longitude: float) -> tuple[int, int]:
    world_size = (2**_MAP_ZOOM) * _TILE_SIZE
    global_x = (float(longitude) + 180.0) / 360.0 * world_size
    lat_rad = math.radians(float(latitude))
    mercator = math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad))
    global_y = (1.0 - mercator / math.pi) / 2.0 * world_size

    x = int(round(global_x - _MAP_TILE_ORIGIN_X * _TILE_SIZE))
    y = int(round(global_y - _MAP_TILE_ORIGIN_Y * _TILE_SIZE))
    max_pixel = _MAP_PIXEL_SIZE - 1
    return max(0, min(max_pixel, x)), max(0, min(max_pixel, y))


def _rocopath_xy_to_gmt_xy(x: float, y: float) -> tuple[int, int]:
    latitude, longitude = _rocopath_xy_to_latlng(x, y)
    return _latlng_to_gmt_xy(latitude, longitude)


def _clean_label(value: object, fallback: str) -> str:
    raw = "" if value is None else str(value)
    clean = _LABEL_INDEX_RE.sub("", raw).strip()
    return clean or fallback


def convert_rocopath_resource_points_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("sift2 JSON 顶层必须是对象")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("sift2 JSON 缺少 items 列表")

    type_items = _load_gmt_type_items()
    missing_mappings: OrderedDict[str, str] = OrderedDict()
    missing_target_types: OrderedDict[str, str] = OrderedDict()
    points_by_type: OrderedDict[str, list[dict]] = OrderedDict()

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        source_type_id = str(raw_item.get("resource_type_id") or "").strip()
        target_type_id = ROCOPATH_TO_GMT_TYPE_IDS.get(source_type_id)
        if not target_type_id:
            missing_mappings.setdefault(source_type_id or "<空类型>", str(raw_item.get("resource_title") or ""))
            continue

        target_type = type_items.get(target_type_id)
        if target_type is None:
            missing_target_types.setdefault(target_type_id, source_type_id)
            continue

        source_id = _source_id(raw_item.get("id"))
        source_x = _number(raw_item.get("x"), "x", source_id)
        source_y = _number(raw_item.get("y"), "y", source_id)
        x, y = _rocopath_xy_to_gmt_xy(source_x, source_y)
        point = {
            "x": x,
            "y": y,
            "label": _clean_label(raw_item.get("label"), target_type["type"]),
            "type": target_type["type"],
            "typeId": target_type_id,
            "sourceId": source_id,
        }
        points_by_type.setdefault(target_type_id, []).append(point)

    if missing_mappings:
        detail = "、".join(f"{type_id} {title}".strip() for type_id, title in missing_mappings.items())
        raise UnsupportedAnnotationFormatError(f"sift2 缺少资源类型映射：{detail}")
    if missing_target_types:
        detail = "、".join(f"{target_id}(来自 {source_id})" for target_id, source_id in missing_target_types.items())
        raise UnsupportedAnnotationFormatError(f"GMT-N 缺少目标标注类型：{detail}")

    output_types = []
    for type_id, points in points_by_type.items():
        item = dict(type_items[type_id])
        item["count"] = len(points)
        output_types.append(item)

    output = {
        "mapId": payload.get("mapId", 4010),
        "types": output_types,
        "pointsByType": dict(points_by_type),
    }
    if "name" in payload:
        output["name"] = "" if payload["name"] is None else str(payload["name"])
    if "notes" in payload:
        output["notes"] = "" if payload["notes"] is None else str(payload["notes"])
    return output


register_outside_converter(FORMAT_VERSION, convert_rocopath_resource_points_payload)

__all__ = [
    "FORMAT_VERSION",
    "ROCOPATH_TO_GMT_TYPE_IDS",
    "convert_rocopath_resource_points_payload",
]

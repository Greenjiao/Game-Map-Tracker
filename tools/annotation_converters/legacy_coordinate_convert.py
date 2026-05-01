"""Convert legacy annotation coordinates into the current annotation format."""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from ui_island.services import resource_metadata

from .base import AnnotationConversionReport, read_json, write_json_atomic

try:
    from tools.route_format_converter import old_big_map_xy_to_17173_xy
except ImportError:  # pragma: no cover - supports running from tools/ directly.
    from route_format_converter import old_big_map_xy_to_17173_xy

_ANNOTATION_OUTPUT_PREFIX = "annotations_converted"
_ANNOTATION_PAYLOAD_KEY_ORDER = (
    "id",
    "generatedAt",
    "format_version",
    "enable_versions",
    "mapId",
    "types",
    "pointsByType",
)


def _dated_output_name(root: Path, source: Path) -> str:
    today = datetime.now().strftime("%Y%m%d")
    stem = source.stem or _ANNOTATION_OUTPUT_PREFIX
    suffix = source.suffix or ".json"
    for index in range(1, 100):
        name = f"{stem}_{today}{index:02d}{suffix}"
        if not (root / name).exists():
            return name
    return f"{stem}_{today}99{suffix}"


def _ordered_annotation_payload(payload: dict) -> dict:
    ordered = {key: payload[key] for key in _ANNOTATION_PAYLOAD_KEY_ORDER if key in payload}
    ordered.update((key, value) for key, value in payload.items() if key not in ordered)
    return ordered


def _finalize_annotation_payload(payload: dict) -> dict:
    output = dict(payload)
    output["generatedAt"] = datetime.now(timezone.utc).isoformat()
    output.pop("id", None)
    resource_metadata.ensure_metadata(output, include_id=True)
    return _ordered_annotation_payload(output)


def _type_items_by_id(types: object) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not isinstance(types, list):
        return result
    for item in types:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "").strip()
        if type_id and type_id not in result:
            result[type_id] = dict(item)
    return result


def _point_type_id(bucket_type_id: str, point: dict) -> str:
    return str(point.get("typeId") or bucket_type_id or "").strip()


def _sync_type_counts(payload: dict, *, synthesize_missing: bool) -> None:
    points_by_type = payload.get("pointsByType")
    if not isinstance(points_by_type, dict):
        points_by_type = {}
        payload["pointsByType"] = points_by_type

    types = payload.get("types")
    if not isinstance(types, list):
        types = []
        payload["types"] = types

    type_items = _type_items_by_id(types)
    for item in types:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "").strip()
        points = points_by_type.get(type_id)
        item["count"] = len(points) if isinstance(points, list) else 0

    for type_id in sorted(str(key) for key in points_by_type):
        points = points_by_type.get(type_id)
        count = len(points) if isinstance(points, list) else 0
        item = type_items.get(type_id)
        if item is None:
            if not synthesize_missing:
                continue
            first_point = points[0] if isinstance(points, list) and points and isinstance(points[0], dict) else {}
            item = {
                "typeId": type_id,
                "type": str(first_point.get("type") or type_id),
                "groupId": "",
                "group": "其他",
                "iconPath": f"{type_id}.png",
            }
            type_items[type_id] = item
            types.append(item)
        item["count"] = count


def _convert_point(bucket_type_id: str, point: dict) -> tuple[str, dict] | None:
    copied = dict(point)
    type_id = _point_type_id(bucket_type_id, copied)
    try:
        new_x, new_y = old_big_map_xy_to_17173_xy(copied["x"], copied["y"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    copied["x"] = new_x
    copied["y"] = new_y
    if type_id:
        copied["typeId"] = type_id
    target_type_id = type_id or bucket_type_id
    if not target_type_id:
        return None
    return target_type_id, copied


def convert_old_big_map_annotation_payload(payload: dict) -> tuple[dict, AnnotationConversionReport]:
    if not isinstance(payload, dict):
        raise ValueError("标注 JSON 顶层必须是对象")
    points_by_type = payload.get("pointsByType")
    if not isinstance(points_by_type, dict):
        raise ValueError("标注 JSON 缺少 pointsByType 对象")

    report = AnnotationConversionReport()
    converted_by_type: OrderedDict[str, list[dict]] = OrderedDict()

    for raw_type_id, raw_points in points_by_type.items():
        bucket_type_id = str(raw_type_id or "").strip()
        if not isinstance(raw_points, list):
            report.skipped_points += 1
            report.messages.append(f"[跳过] {bucket_type_id or '<空类型>'} 不是点位列表")
            continue

        for point in raw_points:
            if not isinstance(point, dict):
                report.skipped_points += 1
                continue
            converted = _convert_point(bucket_type_id, point)
            if converted is None:
                report.skipped_points += 1
                continue
            target_type_id, copied = converted
            converted_by_type.setdefault(target_type_id, []).append(copied)
            report.converted_points += 1

    output = {
        "mapId": payload.get("mapId", 4010),
        "types": [dict(item) for item in payload.get("types", []) if isinstance(item, dict)],
        "pointsByType": dict(converted_by_type),
    }
    _sync_type_counts(output, synthesize_missing=True)
    return _finalize_annotation_payload(output), report


def convert_manual_old_big_map_annotation_payload(payload: dict) -> tuple[dict, AnnotationConversionReport]:
    if not isinstance(payload, dict):
        raise ValueError("标注 JSON 顶层必须是对象")
    points_by_type = payload.get("pointsByType")
    if not isinstance(points_by_type, dict):
        raise ValueError("标注 JSON 缺少 pointsByType 对象")

    report = AnnotationConversionReport()
    converted_by_type: OrderedDict[str, list[dict]] = OrderedDict()

    for raw_type_id, raw_points in points_by_type.items():
        bucket_type_id = str(raw_type_id or "").strip()
        if not isinstance(raw_points, list):
            report.skipped_points += 1
            report.messages.append(f"[跳过] {bucket_type_id or '<空类型>'} 不是点位列表")
            continue

        for point in raw_points:
            if not isinstance(point, dict):
                report.skipped_points += 1
                continue
            if point.get("manual") is not True:
                report.skipped_points += 1
                continue
            converted = _convert_point(bucket_type_id, point)
            if converted is None:
                report.skipped_points += 1
                continue
            target_type_id, copied = converted
            converted_by_type.setdefault(target_type_id, []).append(copied)
            report.converted_points += 1

    output = {
        "mapId": payload.get("mapId", 4010),
        "types": [dict(item) for item in payload.get("types", []) if isinstance(item, dict)],
        "pointsByType": dict(converted_by_type),
    }
    _sync_type_counts(output, synthesize_missing=True)
    return _finalize_annotation_payload(output), report


def merge_annotation_payloads(
    base_payload: dict,
    converted_old_payload: dict,
    report: AnnotationConversionReport | None = None,
) -> dict:
    if not isinstance(base_payload, dict):
        raise ValueError("新标注 JSON 顶层必须是对象")
    base_points = base_payload.get("pointsByType")
    if not isinstance(base_points, dict):
        raise ValueError("新标注 JSON 缺少 pointsByType 对象")
    old_points = converted_old_payload.get("pointsByType")
    if not isinstance(old_points, dict):
        raise ValueError("旧标注转换结果缺少 pointsByType 对象")

    merged = dict(base_payload)
    merged["types"] = [dict(item) for item in base_payload.get("types", []) if isinstance(item, dict)]
    merged_points: dict[str, list[dict]] = {}

    for raw_type_id, points in base_points.items():
        type_id = str(raw_type_id or "").strip()
        copied_points = [dict(point) for point in points if isinstance(point, dict)] if isinstance(points, list) else []
        merged_points[type_id] = copied_points

    old_type_items = _type_items_by_id(converted_old_payload.get("types"))
    merged_type_items = _type_items_by_id(merged["types"])
    for raw_type_id, points in old_points.items():
        type_id = str(raw_type_id or "").strip()
        if not isinstance(points, list):
            continue
        target_points = merged_points.setdefault(type_id, [])
        if type_id and type_id not in merged_type_items and type_id in old_type_items:
            copied_type = dict(old_type_items[type_id])
            merged["types"].append(copied_type)
            merged_type_items[type_id] = copied_type

        for point in points:
            if not isinstance(point, dict):
                continue
            if point.get("manual") is not True:
                if report is not None:
                    report.skipped_points += 1
                continue
            copied_point = dict(point)
            target_points.append(copied_point)

    merged["pointsByType"] = merged_points
    if "mapId" not in merged and "mapId" in converted_old_payload:
        merged["mapId"] = converted_old_payload["mapId"]
    _sync_type_counts(merged, synthesize_missing=False)
    return _finalize_annotation_payload(merged)


def convert_annotation_file(
    old_file: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    merge: bool = True,
    merge_with: str | os.PathLike[str] | None = None,
) -> AnnotationConversionReport:
    old_path = Path(old_file).expanduser().resolve(strict=False)
    if not old_path.is_file():
        raise FileNotFoundError(f"旧标注文件不存在：{old_path}")

    output_root = Path(output_dir).expanduser().resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)

    old_payload = read_json(old_path)

    if merge:
        if merge_with is None:
            raise ValueError("合并模式需要选择新标注文件")
        merge_path = Path(merge_with).expanduser().resolve(strict=False)
        if not merge_path.is_file():
            raise FileNotFoundError(f"新标注文件不存在：{merge_path}")
        base_payload = read_json(merge_path)
        converted_payload, report = convert_manual_old_big_map_annotation_payload(old_payload)
        output_payload = merge_annotation_payloads(base_payload, converted_payload, report)
    else:
        output_payload, report = convert_old_big_map_annotation_payload(old_payload)

    output_name = (
        resource_metadata.annotation_output_name(output_root, prefix=_ANNOTATION_OUTPUT_PREFIX)
        if merge
        else _dated_output_name(output_root, old_path)
    )
    output_path = output_root / output_name
    write_json_atomic(output_path, output_payload)
    report.output_path = str(output_path)
    report.messages.append(f"[完成] 已写入：{output_path}")
    return report

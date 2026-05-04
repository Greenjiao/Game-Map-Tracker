"""Batch conversion helpers for route JSON files."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import config
from ui_island.services import resource_metadata
from ui_island.services.annotation_matcher import (
    AMBIGUOUS_DISTANCE_DELTA,
    DEFAULT_MATCH_RADIUS,
    AnnotationMatchCandidate,
    AnnotationMatchIndex,
    default_teleport_type_ids_from_folder,
    normalize_type_ids,
    suspicious_candidates,
)

_PROGRESS_FILE = "progress.json"
_VISIBILITY_FILE = "selected_routes.json"
_OUTPUT_SUFFIX = "_新格式"

_OLD_ROUTE_LON_SCALE = 5824.0800
_OLD_ROUTE_LON_OFFSET = 7217.5810
_OLD_ROUTE_LAT_SCALE = 5822.8413
_OLD_ROUTE_LAT_OFFSET = 6602.7721

_ROUTE_PAYLOAD_KEY_ORDER = (
    "id",
    "format_version",
    "enable_versions",
    "color",
    "name",
    "notes",
    "loop",
    "points",
    "nodes",
)


@dataclass
class RouteConversionReport:
    converted: int = 0
    skipped: int = 0
    ignored: int = 0
    errors: int = 0
    points_converted: int = 0
    annotation_matched: int = 0
    annotation_unmatched: int = 0
    annotation_existing_skipped: int = 0
    annotation_virtual_skipped: int = 0
    annotation_teleports: int = 0
    annotation_suspicious: int = 0
    messages: list[str] = field(default_factory=list)


@dataclass
class RouteAnnotationStats:
    matched: int = 0
    unmatched: int = 0
    existing_skipped: int = 0
    virtual_skipped: int = 0
    teleports: int = 0
    suspicious: int = 0

    @property
    def changed(self) -> int:
        return self.matched + self.unmatched


@dataclass(frozen=True)
class RouteAnnotationOptions:
    annotation_file: str
    match_type_ids: tuple[str, ...]
    teleport_type_ids: tuple[str, ...] = ()
    max_radius: float = DEFAULT_MATCH_RADIUS
    ambiguous_distance_delta: float = AMBIGUOUS_DISTANCE_DELTA


def _ordered_route_payload(payload: dict) -> dict:
    ordered = {key: payload[key] for key in _ROUTE_PAYLOAD_KEY_ORDER if key in payload}
    ordered.update((key, value) for key, value in payload.items() if key not in ordered)
    return ordered


def _iter_source_files(input_dir: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*.json" if recursive else "*.json"
    yield from sorted(path for path in input_dir.glob(pattern) if path.is_file())


def _target_path(source: Path, input_root: Path, output_root: Path) -> Path:
    relative = source.relative_to(input_root)
    target_name = relative.stem + _OUTPUT_SUFFIX + relative.suffix
    return output_root / relative.with_name(target_name)


def _same_name_target_path(source: Path, input_root: Path, output_root: Path) -> Path:
    return output_root / source.relative_to(input_root)


def validate_distinct_output_dir(input_dir: str | os.PathLike[str], output_dir: str | os.PathLike[str], *, recursive: bool = True) -> None:
    source_root = Path(input_dir).expanduser().resolve(strict=False)
    target_root = Path(output_dir).expanduser().resolve(strict=False)
    if source_root == target_root:
        raise ValueError("输出目录不能和输入目录相同，请选择独立的输出目录。")
    if recursive:
        try:
            target_root.relative_to(source_root)
        except ValueError:
            return
        raise ValueError("递归转换时输出目录不能位于输入目录内部，请选择独立的输出目录。")


def _is_route_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("points"), list) or isinstance(payload.get("nodes"), list)


def _route_point_xy(point: dict) -> tuple[float, float] | None:
    try:
        x = float(point["x"])
        y = float(point["y"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _has_route_annotation(point: dict) -> bool:
    return bool(str(point.get("type") or "").strip() or str(point.get("typeId") or "").strip())


def _format_candidate(candidate: AnnotationMatchCandidate) -> str:
    label = f"（{candidate.label}）" if candidate.label else ""
    return f"{candidate.type_name}/{candidate.type_id}{label} {candidate.distance:.1f}px"


def _copy_route_points_with_annotations(
    points: list,
    *,
    matcher: AnnotationMatchIndex,
    match_type_ids: set[str],
    teleport_type_ids: set[str],
    max_radius: float,
    ambiguous_distance_delta: float,
    stats: RouteAnnotationStats,
    messages: list[str],
    source: Path | None = None,
    bucket_name: str = "points",
) -> list:
    converted: list[object] = []
    source_label = str(source) if source is not None else "路线"
    for index, point in enumerate(points, 1):
        if not isinstance(point, dict):
            converted.append(point)
            continue

        copied = dict(point)
        if _has_route_annotation(copied):
            stats.existing_skipped += 1
            converted.append(copied)
            continue

        node_type = str(copied.get("node_type") or "").strip().casefold()
        if node_type == "virtual":
            stats.virtual_skipped += 1
            converted.append(copied)
            continue

        xy = _route_point_xy(copied)
        if xy is None:
            converted.append(copied)
            continue

        candidates = matcher.find_candidates(xy[0], xy[1], match_type_ids, max_radius=max_radius)
        if candidates:
            best = candidates[0]
            copied["typeId"] = best.type_id
            copied["type"] = best.type_name
            stats.matched += 1
            if "node_type" not in copied:
                if best.type_id in teleport_type_ids:
                    copied["node_type"] = "teleport"
                    stats.teleports += 1
                else:
                    copied["node_type"] = "collect"
            elif str(copied.get("node_type") or "").strip().casefold() == "teleport":
                stats.teleports += 1

            suspicious = suspicious_candidates(candidates, distance_delta=ambiguous_distance_delta)
            if suspicious:
                stats.suspicious += 1
                alternatives = "；".join(_format_candidate(candidate) for candidate in suspicious[:3])
                messages.append(
                    f"[可疑] {source_label} {bucket_name}[{index}] 使用最近标注 {_format_candidate(best)}；备选：{alternatives}"
                )
        else:
            if "node_type" not in copied:
                copied["node_type"] = "collect"
                stats.unmatched += 1
        converted.append(copied)
    return converted


def _accumulate_annotation_stats(report: RouteConversionReport, stats: RouteAnnotationStats) -> None:
    report.points_converted += stats.changed
    report.annotation_matched += stats.matched
    report.annotation_unmatched += stats.unmatched
    report.annotation_existing_skipped += stats.existing_skipped
    report.annotation_virtual_skipped += stats.virtual_skipped
    report.annotation_teleports += stats.teleports
    report.annotation_suspicious += stats.suspicious


def _clean_route_metadata(payload: dict) -> dict:
    output = dict(payload)
    output.pop("coordinate_space_id", None)
    output.pop("map_hash", None)
    output.pop("map_hashs", None)
    output.pop("map_info", None)
    return output


def _is_valid_route_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if len(raw) >= 10 and raw.isdigit():
        return True
    return bool(resource_metadata.HASH_RE.fullmatch(raw.casefold()))


def _ensure_route_metadata(payload: dict) -> dict:
    resource_metadata.ensure_metadata(
        payload,
        include_route_defaults=True,
        preserve_format_version=True,
        enable_versions_policy="append_current_if_list",
    )
    raw_id = str(payload.get("id") or "").strip()
    if _is_valid_route_id(raw_id):
        payload["id"] = raw_id
    else:
        payload["id"] = uuid.uuid4().hex
    return payload


def _ensure_current_enable_version(payload: dict) -> None:
    enable_versions = resource_metadata.normalize_enable_versions(payload.get("enable_versions"))
    if resource_metadata.APP_FORMAT_VERSION not in enable_versions:
        enable_versions.append(resource_metadata.APP_FORMAT_VERSION)
    payload["enable_versions"] = enable_versions


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def normalize_route_payload(
    payload: dict,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("路线 JSON 顶层必须是对象")
    return _ordered_route_payload(_ensure_route_metadata(_clean_route_metadata(payload)))


def old_big_map_xy_to_latlng(x: float, y: float) -> tuple[float, float]:
    """Reverse the old 17173 fitted pixel formula into latitude/longitude."""
    longitude = (float(x) - _OLD_ROUTE_LON_OFFSET) / _OLD_ROUTE_LON_SCALE
    latitude = (_OLD_ROUTE_LAT_OFFSET - float(y)) / _OLD_ROUTE_LAT_SCALE
    return latitude, longitude


def old_big_map_xy_to_17173_xy(x: float, y: float) -> tuple[int, int]:
    """Convert old big_map route pixels into big_map_17173.png pixels."""
    try:
        from tools.fetch_17173_points import latlng_to_xy
    except ImportError:  # pragma: no cover - supports running from tools/ directly.
        from fetch_17173_points import latlng_to_xy

    latitude, longitude = old_big_map_xy_to_latlng(x, y)
    return latlng_to_xy(latitude, longitude)


def convert_old_big_map_route_payload(payload: dict) -> tuple[dict, int]:
    if not isinstance(payload, dict):
        raise ValueError("路线 JSON 顶层必须是对象")

    output = _clean_route_metadata(payload)
    if not str(output.get("format_version") or "").strip():
        output["format_version"] = resource_metadata.APP_FORMAT_VERSION
    converted_points = 0
    for key in ("points", "nodes"):
        points = output.get(key)
        if not isinstance(points, list):
            continue
        converted: list[object] = []
        for point in points:
            if not isinstance(point, dict):
                converted.append(point)
                continue
            copied = dict(point)
            try:
                new_x, new_y = old_big_map_xy_to_17173_xy(copied["x"], copied["y"])
            except (KeyError, TypeError, ValueError, OverflowError):
                converted.append(copied)
                continue
            copied["x"] = new_x
            copied["y"] = new_y
            converted_points += 1
            converted.append(copied)
        output[key] = converted
    _ensure_current_enable_version(output)
    return _ordered_route_payload(_ensure_route_metadata(output)), converted_points


def default_route_annotation_type_ids(annotation_file: str | os.PathLike[str]) -> list[str]:
    matcher = AnnotationMatchIndex.from_file(annotation_file)
    return normalize_type_ids(item.get("typeId") for item in matcher.type_items)


def default_route_teleport_type_ids(
    annotation_file: str | os.PathLike[str],
    teleport_dir: str | os.PathLike[str] | None = None,
) -> list[str]:
    folder = Path(teleport_dir) if teleport_dir is not None else Path(config.app_path("tools", "points_get", "teleport"))
    return default_teleport_type_ids_from_folder(annotation_file, folder)


def annotate_route_payload(
    payload: dict,
    matcher: AnnotationMatchIndex,
    options: RouteAnnotationOptions,
    *,
    source: Path | None = None,
) -> tuple[dict, RouteAnnotationStats, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("路线 JSON 顶层必须是对象")

    output = dict(payload)
    stats = RouteAnnotationStats()
    messages: list[str] = []
    match_type_ids = set(normalize_type_ids(options.match_type_ids))
    teleport_type_ids = set(normalize_type_ids(options.teleport_type_ids)) & match_type_ids

    for key in ("points", "nodes"):
        points = output.get(key)
        if not isinstance(points, list):
            continue
        output[key] = _copy_route_points_with_annotations(
            points,
            matcher=matcher,
            match_type_ids=match_type_ids,
            teleport_type_ids=teleport_type_ids,
            max_radius=options.max_radius,
            ambiguous_distance_delta=options.ambiguous_distance_delta,
            stats=stats,
            messages=messages,
            source=source,
            bucket_name=key,
        )
    return output, stats, messages


def convert_route_folder(
    input_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    recursive: bool = True,
    overwrite: bool = False,
) -> RouteConversionReport:
    source_root = Path(input_dir).expanduser().resolve(strict=False)
    target_root = Path(output_dir).expanduser().resolve(strict=False)
    if not source_root.is_dir():
        raise ValueError(f"输入目录不存在：{source_root}")
    validate_distinct_output_dir(source_root, target_root, recursive=recursive)

    report = RouteConversionReport()
    target_root.mkdir(parents=True, exist_ok=True)

    for source in _iter_source_files(source_root, recursive):
        if source.name in {_PROGRESS_FILE, _VISIBILITY_FILE} or source.stem.endswith(_OUTPUT_SUFFIX):
            report.ignored += 1
            continue

        target = _target_path(source, source_root, target_root)
        if target.exists() and not overwrite:
            report.skipped += 1
            report.messages.append(f"[跳过] 输出已存在：{target}")
            continue

        try:
            with source.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not _is_route_payload(payload):
                report.ignored += 1
                report.messages.append(f"[忽略] 非路线文件：{source}")
                continue
            converted, point_count = convert_old_big_map_route_payload(payload)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as handle:
                json.dump(converted, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            report.errors += 1
            report.messages.append(f"[错误] {source}: {exc}")
            continue

        report.converted += 1
        report.points_converted += point_count
        report.messages.append(f"[完成] {source} -> {target}")

    return report


def convert_old_big_map_routes_in_place(
    input_dir: str | os.PathLike[str],
    *,
    recursive: bool = True,
) -> RouteConversionReport:
    source_root = Path(input_dir).expanduser().resolve(strict=False)
    if not source_root.is_dir():
        raise ValueError(f"输入目录不存在：{source_root}")

    report = RouteConversionReport()
    for source in _iter_source_files(source_root, recursive):
        if source.name in {_PROGRESS_FILE, _VISIBILITY_FILE} or source.stem.endswith(_OUTPUT_SUFFIX):
            report.ignored += 1
            continue

        try:
            with source.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not _is_route_payload(payload):
                report.ignored += 1
                report.messages.append(f"[忽略] 非路线文件：{source}")
                continue
            converted, point_count = convert_old_big_map_route_payload(payload)
            if point_count <= 0:
                report.skipped += 1
                report.messages.append(f"[跳过] 没有可转换的 x/y 点位：{source}")
                continue
            _write_json_atomic(source, converted)
        except Exception as exc:
            report.errors += 1
            report.messages.append(f"[错误] {source}: {exc}")
            continue

        report.converted += 1
        report.points_converted += point_count
        report.messages.append(f"[完成] {source}，转换 {point_count} 个点")

    return report


def annotate_route_folder(
    input_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str] | None,
    options: RouteAnnotationOptions,
    *,
    recursive: bool = True,
    overwrite: bool = False,
    in_place: bool = False,
) -> RouteConversionReport:
    source_root = Path(input_dir).expanduser().resolve(strict=False)
    if not source_root.is_dir():
        raise ValueError(f"输入目录不存在：{source_root}")

    match_type_ids = normalize_type_ids(options.match_type_ids)
    if not match_type_ids:
        raise ValueError("请至少选择一个要匹配的标注类型。")
    annotation_file = Path(options.annotation_file).expanduser().resolve(strict=False)
    if not annotation_file.is_file():
        raise ValueError(f"标注文件不存在：{annotation_file}")

    target_root: Path | None = None
    if not in_place:
        if output_dir is None:
            raise ValueError("请先选择输出目录。")
        target_root = Path(output_dir).expanduser().resolve(strict=False)
        validate_distinct_output_dir(source_root, target_root, recursive=recursive)
        target_root.mkdir(parents=True, exist_ok=True)

    matcher = AnnotationMatchIndex.from_file(annotation_file)
    normalized_options = RouteAnnotationOptions(
        annotation_file=str(annotation_file),
        match_type_ids=tuple(match_type_ids),
        teleport_type_ids=tuple(normalize_type_ids(options.teleport_type_ids)),
        max_radius=options.max_radius,
        ambiguous_distance_delta=options.ambiguous_distance_delta,
    )

    report = RouteConversionReport()
    for source in _iter_source_files(source_root, recursive):
        if source.name in {_PROGRESS_FILE, _VISIBILITY_FILE} or source.stem.endswith(_OUTPUT_SUFFIX):
            report.ignored += 1
            continue

        try:
            with source.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not _is_route_payload(payload):
                report.ignored += 1
                report.messages.append(f"[忽略] 非路线文件：{source}")
                continue
            converted, stats, messages = annotate_route_payload(
                payload,
                matcher,
                normalized_options,
                source=source,
            )
            target = source if in_place else _same_name_target_path(source, source_root, target_root)  # type: ignore[arg-type]
            if not in_place and target.exists() and not overwrite:
                report.skipped += 1
                report.messages.append(f"[跳过] 输出已存在：{target}")
                continue
            if in_place and stats.changed <= 0:
                report.skipped += 1
                _accumulate_annotation_stats(report, stats)
                report.messages.extend(messages)
                report.messages.append(f"[跳过] 没有可写入的标注或节点类型：{source}")
                continue

            if in_place:
                _write_json_atomic(source, converted)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding="utf-8") as handle:
                    json.dump(converted, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            report.errors += 1
            report.messages.append(f"[错误] {source}: {exc}")
            continue

        report.converted += 1
        _accumulate_annotation_stats(report, stats)
        report.messages.extend(messages)
        action = "覆盖" if in_place else f"输出到 {target}"
        report.messages.append(
            f"[完成] {source}，{action}，匹配 {stats.matched}，未匹配 {stats.unmatched}，"
            f"跳过已有 {stats.existing_skipped}，跳过引路点 {stats.virtual_skipped}"
        )

    return report

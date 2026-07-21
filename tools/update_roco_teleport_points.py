"""Generate GMT-N teleport-point JSON files from current Roco data.

Five categories are copied from a user-reviewed GMT-N annotation file.  Boss
markers are rebuilt from the current unpacked game configuration.  The same
serialized bytes are written to the source data directory and its release
mirror so a release cannot silently ship stale teleport data.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "tools" / "points_get" / "teleport"
DEFAULT_MIRROR_DIR = PROJECT_ROOT / "docs" / "update" / "tools" / "points_get" / "teleport"
DEFAULT_ROCO_MAP_GET_ROOT = PROJECT_ROOT.parent / "RocoMapGet"
DEFAULT_SCENE_RES_ID = 10003
DEFAULT_LOGICAL_MAP_SIZE = 8192
POINT_RADIUS = 30
BOSS_SUFFIX = "（首领战）"


ANNOTATION_EXPORTS = (
    {
        "filename": "魔力之源（传送点）.json",
        "name": "魔力之源（传送点）",
        "type_ids": ("5",),
        "type_names": ("魔力之源",),
        "annotation_types": ("魔力之源",),
        "review_status": "已按用户校准结果写入",
    },
    {
        "filename": "炼金台.json",
        "name": "炼金台",
        "type_ids": ("6",),
        "type_names": ("炼金釜",),
        "annotation_types": ("炼金釜",),
        "review_status": "已按用户校准结果写入",
    },
    {
        "filename": "眠枭庇护所.json",
        "name": "眠枭庇护所",
        "type_ids": ("9", "10"),
        "type_names": ("大型眠枭庇护所", "小型眠枭庇护所"),
        "annotation_types": ("大型眠枭庇护所", "小型眠枭庇护所"),
        "review_status": "已按用户校准结果写入",
    },
    {
        "filename": "副本.json",
        "name": "副本",
        "type_ids": ("7",),
        "type_names": ("副本",),
        "annotation_types": ("副本",),
        "review_status": "当前配置结果，尚未人工校对",
    },
    {
        "filename": "稀兽花种.json",
        "name": "稀兽花种",
        "type_ids": ("8",),
        "type_names": ("稀兽花种",),
        "annotation_types": ("稀兽花种",),
        "review_status": "当前配置结果，尚未人工校对",
    },
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从校准标注和当前游戏配置更新 GMT-N 的六份传送点数据。"
    )
    parser.add_argument("--annotation", type=Path, required=True, help="用户校准的 GMT-N 标注 JSON")
    parser.add_argument("--game-root", type=Path, required=True, help="当前游戏完整解包目录")
    parser.add_argument(
        "--roco-map-get-root",
        type=Path,
        default=DEFAULT_ROCO_MAP_GET_ROOT,
        help=f"RocoMapGet 项目目录（默认：{DEFAULT_ROCO_MAP_GET_ROOT}）",
    )
    parser.add_argument(
        "--logical-map-size",
        type=int,
        default=DEFAULT_LOGICAL_MAP_SIZE,
        help=f"输出坐标系边长（默认：{DEFAULT_LOGICAL_MAP_SIZE}）",
    )
    parser.add_argument(
        "--scene-res-id",
        type=int,
        default=DEFAULT_SCENE_RES_ID,
        help=f"游戏场景资源 ID（默认：{DEFAULT_SCENE_RES_ID}）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"仓库源数据目录（默认：{DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--mirror-dir",
        type=Path,
        action="append",
        default=None,
        help="发布镜像目录；可重复。未提供时写入仓库默认发布镜像。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只报告来源、数量和排除原因，不写文件")
    args = parser.parse_args(argv)
    if args.logical_map_size <= 0:
        parser.error("--logical-map-size must be positive")
    if args.mirror_dir is None:
        args.mirror_dir = [DEFAULT_MIRROR_DIR]
    return args


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"JSON file does not exist: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _integer_coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text and text.lstrip("-").isdigit():
            return int(text)
    raise ValueError(f"{field} must be an integer: {value!r}")


def _type_index(annotation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    type_rows = annotation.get("types")
    if not isinstance(type_rows, list):
        raise ValueError("Annotation is missing the types array")
    result: dict[str, dict[str, Any]] = {}
    for row in type_rows:
        if not isinstance(row, dict):
            continue
        type_id = str(row.get("typeId") or "").strip()
        if not type_id:
            continue
        if type_id in result:
            raise ValueError(f"Duplicate annotation typeId: {type_id}")
        result[type_id] = row
    return result


def annotation_points(
    annotation: dict[str, Any],
    *,
    type_ids: Iterable[str],
    expected_names: Iterable[str],
) -> list[dict[str, Any]]:
    """Copy selected annotation points without changing calibrated XY/labels."""

    selected_ids = tuple(str(value) for value in type_ids)
    selected_names = tuple(expected_names)
    if len(selected_ids) != len(selected_names):
        raise ValueError("type_ids and expected_names must have the same length")
    types = _type_index(annotation)
    points_by_type = annotation.get("pointsByType")
    if not isinstance(points_by_type, dict):
        raise ValueError("Annotation is missing the pointsByType object")

    result: list[dict[str, Any]] = []
    seen_xy: set[tuple[int, int]] = set()
    for type_id, expected_name in zip(selected_ids, selected_names):
        type_row = types.get(type_id)
        if type_row is None:
            raise ValueError(f"Annotation is missing required typeId={type_id}")
        actual_name = str(type_row.get("type") or "").strip()
        if actual_name != expected_name:
            raise ValueError(
                f"Annotation typeId={type_id} is {actual_name!r}, expected {expected_name!r}"
            )
        source_points = points_by_type.get(type_id)
        if not isinstance(source_points, list):
            raise ValueError(f"Annotation pointsByType[{type_id!r}] must be an array")
        declared_count = type_row.get("count")
        if declared_count is not None and _integer_coordinate(declared_count, "type.count") != len(source_points):
            raise ValueError(
                f"Annotation typeId={type_id} declares {declared_count} points but contains {len(source_points)}"
            )
        for index, source in enumerate(source_points):
            if not isinstance(source, dict):
                raise ValueError(f"Annotation typeId={type_id} point {index} is not an object")
            x = _integer_coordinate(source.get("x"), "point.x")
            y = _integer_coordinate(source.get("y"), "point.y")
            label = str(source.get("label") or "").strip()
            if not label:
                raise ValueError(f"Annotation typeId={type_id} point {index} has no label")
            xy = (x, y)
            if xy in seen_xy:
                raise ValueError(f"Duplicate XY in combined {selected_ids}: {xy}")
            seen_xy.add(xy)
            result.append({"x": x, "y": y, "label": label, "radius": POINT_RADIUS})
    return result


def teleport_payload(
    *,
    name: str,
    notes: str,
    annotation_types: Iterable[str],
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    aliases = [value for value in annotation_types if isinstance(value, str) and value.strip()]
    if not aliases:
        raise ValueError(f"Teleport payload {name!r} has no annotation type aliases")
    validate_points(points, name=name)
    return {
        "name": name,
        "loop": False,
        "notes": notes,
        "annotationTypes": aliases,
        "points": points,
    }


def build_annotation_payloads(
    annotation: dict[str, Any], *, logical_map_size: int
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for spec in ANNOTATION_EXPORTS:
        points = annotation_points(
            annotation,
            type_ids=spec["type_ids"],
            expected_names=spec["type_names"],
        )
        source_ids = "/".join(spec["type_ids"])
        notes = (
            f"来源：用户校准标注 typeId={source_ids}；"
            f"校准状态：{spec['review_status']}；"
            f"坐标系：{logical_map_size}×{logical_map_size}；数量：{len(points)}。"
        )
        result[spec["filename"]] = teleport_payload(
            name=spec["name"],
            notes=notes,
            annotation_types=spec["annotation_types"],
            points=points,
        )
    return result


def import_roco_exporter(roco_map_get_root: Path) -> Any:
    root = roco_map_get_root.expanduser().resolve()
    exporter = root / "getAnn" / "extract_roco_gathering_annotations.py"
    if not exporter.is_file():
        raise FileNotFoundError(f"RocoMapGet exporter was not found: {exporter}")
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return importlib.import_module("getAnn.extract_roco_gathering_annotations")


def load_game_configs(game_root: Path, roco_module: Any) -> dict[str, dict[str, Any]]:
    root = game_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Game unpack root does not exist: {root}")
    discovery = roco_module.discover_configs([root])
    sources = roco_module.select_sources(discovery)
    return roco_module.load_selected_configs(sources)


def _config_rows(configs: dict[str, dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    try:
        value = configs[name]["RocoDataRows"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Game configs are missing {name}.RocoDataRows") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name}.RocoDataRows must be an object")
    return {str(key): row for key, row in value.items() if isinstance(row, dict)}


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_boss_points(
    configs: dict[str, dict[str, Any]],
    *,
    roco_module: Any,
    scene_res_id: int,
    logical_map_size: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Resolve boss markers through catalog -> gathering -> refresh -> area."""

    catalog_rows = _config_rows(configs, "MEGAMAP_CONF")
    gathering_rows = _config_rows(configs, "MEGAMAP_GATHERING_CONF")
    refresh_rows = _config_rows(configs, "NPC_REFRESH_CONTENT_CONF")
    rule_rows = _config_rows(configs, "NPC_REFRESH_RULE_CONF")
    area_rows = _config_rows(configs, "AREA_CONF")
    npc_rows = _config_rows(configs, "NPC_CONF")
    block_rows = _config_rows(configs, "WORLD_MAP_BLOCK_CONF")

    transform, _ = roco_module.get_scene_transform(block_rows, scene_res_id)
    transform = replace(transform, logical_size=logical_map_size)
    catalogs = sorted(
        (
            row
            for row in catalog_rows.values()
            if _to_int(row.get("class")) == 3
            and str(row.get("genre") or "").strip().endswith(BOSS_SUFFIX)
        ),
        key=lambda row: (_to_int(row.get("id")) or 10**18, str(row.get("genre") or "")),
    )

    excluded: Counter[str] = Counter()
    built: list[tuple[tuple[int, int, int, int, int], dict[str, Any]]] = []
    seen_xy: set[tuple[int, int]] = set()
    for catalog in catalogs:
        catalog_id = _to_int(catalog.get("id"))
        genre = str(catalog.get("genre") or "").strip()
        label = f"首领·{genre.removesuffix(BOSS_SUFFIX)}"
        entries = sorted(
            (
                row
                for row in gathering_rows.values()
                if str(row.get("genre") or "").strip() == genre
                and _to_int(row.get("index_method")) == 5
            ),
            key=lambda row: _to_int(row.get("id")) or 10**18,
        )
        if not entries:
            excluded["missing_index_method_5_entry"] += 1
            continue
        for entry in entries:
            gathering_id = _to_int(entry.get("id"))
            refresh_id = _to_int(entry.get("param_id"))
            refresh = refresh_rows.get(str(refresh_id)) if refresh_id is not None else None
            if refresh is None:
                excluded["missing_refresh"] += 1
                continue
            if _to_int(refresh.get("refresh_type")) not in (None, 1):
                excluded["unsupported_refresh_type"] += 1
                continue
            area_id = _to_int(refresh.get("refresh_param"))
            area = area_rows.get(str(area_id)) if area_id is not None else None
            if area is None:
                excluded["missing_area"] += 1
                continue
            if _to_int(area.get("scene_res_id")) != scene_res_id:
                excluded["other_scene"] += 1
                continue
            npc_id = _to_int(refresh.get("npc_id"))
            npc = npc_rows.get(str(npc_id)) if npc_id is not None else None
            rule_id = _to_int(refresh.get("refresh_rule"))
            rule = rule_rows.get(str(rule_id)) if rule_id is not None else None
            reasons = list(
                roco_module.config_rejection_reasons(
                    refresh,
                    npc=npc,
                    location=area,
                    rule=rule,
                    extra_text=genre,
                )
            )
            positions = area.get("pos")
            if not isinstance(positions, list) or not positions:
                reasons.append("missing_position")
                excluded.update(set(reasons))
                continue
            for position_index, position in enumerate(positions):
                raw = position.get("position_xyz") if isinstance(position, dict) else None
                xyz = roco_module.parse_xyz(raw)
                point_reasons = list(reasons)
                if xyz is None:
                    point_reasons.append("invalid_position")
                if point_reasons:
                    excluded.update(set(point_reasons))
                    continue
                x, y = transform.convert(xyz[0], xyz[1])
                if not (0 <= x < logical_map_size and 0 <= y < logical_map_size):
                    excluded["out_of_map_bounds"] += 1
                    continue
                xy = (x, y)
                if xy in seen_xy:
                    excluded["duplicate_position"] += 1
                    continue
                seen_xy.add(xy)
                point = {"x": x, "y": y, "label": label, "radius": POINT_RADIUS}
                sort_key = (
                    catalog_id if catalog_id is not None else 10**18,
                    gathering_id if gathering_id is not None else 10**18,
                    refresh_id if refresh_id is not None else 10**18,
                    position_index,
                    x,
                )
                built.append((sort_key, point))
    built.sort(key=lambda item: item[0])
    return [point for _, point in built], excluded


def build_boss_payload(
    configs: dict[str, dict[str, Any]],
    *,
    roco_module: Any,
    scene_res_id: int,
    logical_map_size: int,
) -> tuple[dict[str, Any], Counter[str]]:
    points, excluded = build_boss_points(
        configs,
        roco_module=roco_module,
        scene_res_id=scene_res_id,
        logical_map_size=logical_map_size,
    )
    notes = (
        "来源：当前游戏配置 "
        "MEGAMAP_CONF → MEGAMAP_GATHERING_CONF(index_method=5) → "
        "NPC_REFRESH_CONTENT_CONF → AREA_CONF；"
        f"场景：{scene_res_id}；坐标系：{logical_map_size}×{logical_map_size}；数量：{len(points)}。"
    )
    return (
        teleport_payload(
            name="BOSS（精灵首领）",
            notes=notes,
            annotation_types=("BOSS（精灵首领）",),
            points=points,
        ),
        excluded,
    )


def validate_points(points: list[dict[str, Any]], *, name: str) -> None:
    seen: set[tuple[int, int]] = set()
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError(f"{name} point {index} is not an object")
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, bool) or not isinstance(x, int):
            raise ValueError(f"{name} point {index} x is not an integer")
        if isinstance(y, bool) or not isinstance(y, int):
            raise ValueError(f"{name} point {index} y is not an integer")
        if point.get("radius") != POINT_RADIUS:
            raise ValueError(f"{name} point {index} radius must be {POINT_RADIUS}")
        xy = (x, y)
        if xy in seen:
            raise ValueError(f"{name} contains duplicate XY: {xy}")
        seen.add(xy)


def serialize_payload(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_payloads(
    payloads: dict[str, dict[str, Any]], *, output_dir: Path, mirror_dirs: Iterable[Path]
) -> list[Path]:
    targets = [output_dir, *mirror_dirs]
    resolved_targets: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        resolved = target.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        resolved_targets.append(resolved)
    written: list[Path] = []
    for directory in resolved_targets:
        directory.mkdir(parents=True, exist_ok=True)
        for filename, payload in payloads.items():
            path = directory / filename
            path.write_bytes(serialize_payload(payload))
            written.append(path)
    return written


def summary_payload(
    payloads: dict[str, dict[str, Any]],
    *,
    annotation_path: Path,
    game_root: Path,
    logical_map_size: int,
    scene_res_id: int,
    boss_excluded: Counter[str],
    dry_run: bool,
    output_dir: Path,
    mirror_dirs: Iterable[Path],
) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "annotation": str(annotation_path.expanduser().resolve()),
        "game_root": str(game_root.expanduser().resolve()),
        "scene_res_id": scene_res_id,
        "logical_map_size": logical_map_size,
        "counts": {filename: len(payload["points"]) for filename, payload in payloads.items()},
        "boss_excluded_reasons": dict(sorted(boss_excluded.items())),
        "output_dir": str(output_dir.expanduser().resolve()),
        "mirror_dirs": [str(path.expanduser().resolve()) for path in mirror_dirs],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    annotation = load_json_object(args.annotation.expanduser().resolve())
    payloads = build_annotation_payloads(annotation, logical_map_size=args.logical_map_size)
    roco_module = import_roco_exporter(args.roco_map_get_root)
    configs = load_game_configs(args.game_root, roco_module)
    boss, boss_excluded = build_boss_payload(
        configs,
        roco_module=roco_module,
        scene_res_id=args.scene_res_id,
        logical_map_size=args.logical_map_size,
    )
    payloads["BOSS（精灵首领）.json"] = boss
    summary = summary_payload(
        payloads,
        annotation_path=args.annotation,
        game_root=args.game_root,
        logical_map_size=args.logical_map_size,
        scene_res_id=args.scene_res_id,
        boss_excluded=boss_excluded,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        mirror_dirs=args.mirror_dir,
    )
    if not args.dry_run:
        write_payloads(payloads, output_dir=args.output_dir, mirror_dirs=args.mirror_dir)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Add canonical layer keys to GMT annotation and route points.

Existing non-empty layers are preserved. Missing layers receive the catalog's
default layer. Only annotation ``pointsByType[*]`` and route top-level
``points[*]`` are touched; external-edge ``nodes[*]`` are excluded.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


@dataclass(frozen=True)
class LayerCatalog:
    default_layer: str
    layers: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "LayerCatalog":
        payload = load_json_object(path)
        default_layer = str(payload.get("default_layer") or "").strip()
        layers = payload.get("layers")
        if not default_layer or not isinstance(layers, dict) or default_layer not in layers:
            raise ValueError(f"Invalid layer catalog: {path}")
        for name, metadata in layers.items():
            if not isinstance(metadata, dict):
                raise ValueError(f"Layer metadata must be an object: {name!r}")
            background_id = metadata.get("background_id")
            if isinstance(background_id, bool) or not isinstance(background_id, int) or background_id <= 0:
                raise ValueError(f"Layer has invalid background_id: {name!r}")
        return cls(default_layer=default_layer, layers=layers)


@dataclass
class MigrationStats:
    files_scanned: int = 0
    files_changed: int = 0
    points_scanned: int = 0
    points_changed: int = 0
    existing_preserved: int = 0

    def add(self, other: "MigrationStats") -> None:
        self.files_scanned += other.files_scanned
        self.files_changed += other.files_changed
        self.points_scanned += other.points_scanned
        self.points_changed += other.points_changed
        self.existing_preserved += other.existing_preserved


def annotation_points(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    points_by_type = payload.get("pointsByType")
    if not isinstance(points_by_type, dict):
        raise ValueError("Annotation is missing pointsByType")
    for points in points_by_type.values():
        if not isinstance(points, list):
            continue
        for point in points:
            if isinstance(point, dict):
                yield point


def route_points(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    points = payload.get("points")
    if not isinstance(points, list):
        raise ValueError("Route is missing top-level points")
    for point in points:
        if isinstance(point, dict):
            yield point


def _store_layer(point: dict[str, Any], layer: str) -> None:
    """Place layer before the last existing key to keep JSON diffs minimal."""

    items = [(key, value) for key, value in point.items() if key != "layer"]
    point.clear()
    if not items:
        point["layer"] = layer
        return
    for key, value in items[:-1]:
        point[key] = value
    point["layer"] = layer
    last_key, last_value = items[-1]
    point[last_key] = last_value


def apply_layer_fields(
    points: Iterable[dict[str, Any]],
    *,
    catalog: LayerCatalog,
    default_layer: str | None = None,
) -> MigrationStats:
    target_default = default_layer or catalog.default_layer
    if target_default not in catalog.layers:
        raise ValueError(f"Unknown default layer: {target_default!r}")

    stats = MigrationStats()
    for point in points:
        stats.points_scanned += 1
        existing = str(point.get("layer") or "").strip()
        layer = existing or target_default
        if layer not in catalog.layers:
            raise ValueError(f"Unknown point layer: {layer!r}")
        if existing:
            stats.existing_preserved += 1
        else:
            stats.points_changed += 1
        _store_layer(point, layer)
    return stats


def _serialized_like(path: Path, payload: dict[str, Any]) -> tuple[bytes, bytes]:
    original = path.read_bytes()
    has_bom = original.startswith(b"\xef\xbb\xbf")
    original_body = original[3:] if has_bom else original
    has_final_newline = original_body.endswith(b"\n")
    newline = "\r\n" if b"\r\n" in original else "\n"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    if has_final_newline:
        text += newline
    encoded = text.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    return original, encoded


def _atomic_write(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def migrate_file(
    path: Path,
    *,
    kind: str,
    catalog: LayerCatalog,
    default_layer: str | None,
    write: bool,
) -> MigrationStats:
    payload = load_json_object(path)
    points = annotation_points(payload) if kind == "annotation" else route_points(payload)
    stats = apply_layer_fields(points, catalog=catalog, default_layer=default_layer)
    stats.files_scanned = 1
    original, serialized = _serialized_like(path, payload)
    if serialized != original:
        stats.files_changed = 1
        if write:
            _atomic_write(path, serialized)
    return stats


def _resolve_path(value: Path, root: Path) -> Path:
    return value if value.is_absolute() else root / value


def _default_annotation(config_path: Path, root: Path) -> Path:
    config = load_json_object(config_path)
    value = config.get("ANNOTATION_FILE")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ANNOTATION_FILE is missing from {config_path}")
    return _resolve_path(Path(value), root)


def _route_files(routes_root: Path) -> list[Path]:
    result: list[Path] = []
    for path in sorted(routes_root.rglob("*.json")):
        try:
            payload = load_json_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload.get("points"), list):
            result.append(path)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add layer keys to GMT point files")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--mapping", type=Path, default=Path("maps/layer_maps.json"))
    parser.add_argument("--annotation", type=Path, action="append")
    parser.add_argument("--route", type=Path, action="append")
    parser.add_argument("--routes-root", type=Path, default=Path("routes"))
    parser.add_argument("--skip-routes", action="store_true")
    parser.add_argument("--default-layer")
    parser.add_argument("--write", action="store_true", help="Write changes; the default is dry-run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.project_root.resolve()
    catalog = LayerCatalog.load(_resolve_path(args.mapping, root))
    annotations = args.annotation or [_default_annotation(_resolve_path(args.config, root), root)]
    annotation_paths = [_resolve_path(path, root) for path in annotations]

    if args.skip_routes:
        route_paths: list[Path] = []
    elif args.route:
        route_paths = [_resolve_path(path, root) for path in args.route]
    else:
        route_paths = _route_files(_resolve_path(args.routes_root, root))

    total = MigrationStats()
    for kind, paths in (("annotation", annotation_paths), ("route", route_paths)):
        for path in paths:
            total.add(
                migrate_file(
                    path,
                    kind=kind,
                    catalog=catalog,
                    default_layer=args.default_layer,
                    write=args.write,
                )
            )

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"[{mode}] files={total.files_scanned}, changed_files={total.files_changed}")
    print(
        f"points={total.points_scanned}, changed_points={total.points_changed}, "
        f"preserved_existing={total.existing_preserved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

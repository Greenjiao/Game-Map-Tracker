"""Shared helpers for route/annotation resource metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

from ui_island.app.app_info import APP_ENABLE_VERSIONS, APP_FORMAT_VERSION

HASH_RE = re.compile(r"^[0-9a-f]{32}$")


def md5_file(path: str | os.PathLike[str] | None) -> str:
    if not path:
        return ""
    digest = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _dedupe_versions(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values or []:
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def default_enable_versions() -> list[str]:
    values = APP_ENABLE_VERSIONS
    try:
        import config

        runtime_values = getattr(config, "APP_ENABLE_VERSIONS", None)
        if isinstance(runtime_values, list) and runtime_values:
            values = runtime_values
    except Exception:
        pass
    return _dedupe_versions(values)


def normalize_enable_versions(values) -> list[str]:
    return _dedupe_versions(values)


def format_version_as_enable_version(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("format_version") or "").strip()


def enable_versions_with_format_version(payload: dict | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return _dedupe_versions(
        [
            format_version_as_enable_version(payload),
            *normalize_enable_versions(payload.get("enable_versions")),
        ]
    )


def route_enable_version_options(existing_versions=None) -> list[str]:
    return _dedupe_versions([*default_enable_versions(), *(existing_versions or [])])


def ensure_metadata(
    payload: dict,
    *,
    include_id: bool = False,
    include_route_defaults: bool = False,
    preserve_format_version: bool = False,
    fill_missing_format_version: bool = False,
    enable_versions_policy: str = "default",
) -> dict:
    if enable_versions_policy not in {"default", "append_current_if_list", "preserve"}:
        raise ValueError(f"Unknown enable_versions policy: {enable_versions_policy}")

    if not preserve_format_version or (
        fill_missing_format_version and not str(payload.get("format_version") or "").strip()
    ):
        payload["format_version"] = APP_FORMAT_VERSION

    if enable_versions_policy == "default":
        enable_versions = _dedupe_versions(payload.get("enable_versions", []))
        for item in default_enable_versions():
            if item not in enable_versions:
                enable_versions.append(item)
        if APP_FORMAT_VERSION not in enable_versions:
            enable_versions.append(APP_FORMAT_VERSION)
        payload["enable_versions"] = enable_versions
    elif enable_versions_policy == "append_current_if_list":
        raw_enable_versions = payload.get("enable_versions")
        if isinstance(raw_enable_versions, list):
            enable_versions = _dedupe_versions(raw_enable_versions)
            if APP_FORMAT_VERSION not in enable_versions:
                enable_versions.append(APP_FORMAT_VERSION)
            payload["enable_versions"] = enable_versions

    if include_route_defaults:
        raw_loop = payload.get("loop", False)
        if isinstance(raw_loop, bool):
            payload["loop"] = raw_loop
        elif isinstance(raw_loop, str):
            payload["loop"] = raw_loop.strip().casefold() in {"1", "true", "yes", "on"}
        else:
            payload["loop"] = bool(raw_loop)
        notes = payload.get("notes", "")
        payload["notes"] = "" if notes is None else (notes if isinstance(notes, str) else str(notes))

    if include_id:
        raw_id = str(payload.get("id") or "").strip().lower()
        if not HASH_RE.fullmatch(raw_id):
            payload["id"] = uuid.uuid4().hex
        else:
            payload["id"] = raw_id
    return payload


def read_json_payload(path: str | os.PathLike[str] | None) -> dict | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@lru_cache(maxsize=16)
def _default_point_layer_cached(path: str, modified_ns: int, file_size: int) -> str:
    del modified_ns, file_size
    payload = read_json_payload(path)
    if not isinstance(payload, dict):
        return ""
    value = payload.get("default_layer")
    return value.strip() if isinstance(value, str) else ""


def default_point_layer(base_dir: str | os.PathLike[str] | None = None) -> str:
    """Return the configured default point layer, reloading after file changes."""
    if base_dir is None:
        try:
            import config

            base_dir = config.BASE_DIR
        except Exception:
            return ""
    path = Path(base_dir) / "maps" / "layer_maps.json"
    try:
        stat = path.stat()
    except OSError:
        return ""
    return _default_point_layer_cached(str(path), stat.st_mtime_ns, stat.st_size)


def point_layer_or_default(
    value: object,
    base_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Normalize a point layer and fall back to the configured default layer."""
    layer = value.strip() if isinstance(value, str) else ""
    return layer or default_point_layer(base_dir)


_COORD_TRANSFORM_KEY = "coord_transform"
_COORD_TRANSFORM_FIELDS = ("scale_x", "scale_y", "offset_x", "offset_y")
_COORD_TRANSFORM_DEFAULTS = {
    "scale_x": 1.0,
    "scale_y": 1.0,
    "offset_x": 0.0,
    "offset_y": 0.0,
}


def _coerce_coord_value(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coord_transform_from_payload(payload: object) -> dict | None:
    """Return the explicit coord_transform dict from a payload, or None if absent."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get(_COORD_TRANSFORM_KEY)
    if not isinstance(raw, dict):
        return None
    return {
        field: _coerce_coord_value(raw.get(field), _COORD_TRANSFORM_DEFAULTS[field])
        for field in _COORD_TRANSFORM_FIELDS
    }


def is_identity_coord_transform(transform: object) -> bool:
    if not isinstance(transform, dict):
        return True
    for field, default in _COORD_TRANSFORM_DEFAULTS.items():
        if _coerce_coord_value(transform.get(field), default) != default:
            return False
    return True


def apply_coord_transform_to_payload(payload: dict, transform: object) -> None:
    """Write coord_transform into payload; identity values are stripped."""
    if not isinstance(payload, dict):
        return
    if transform is None or is_identity_coord_transform(transform):
        payload.pop(_COORD_TRANSFORM_KEY, None)
        return
    if not isinstance(transform, dict):
        return
    payload[_COORD_TRANSFORM_KEY] = {
        field: _coerce_coord_value(transform.get(field), _COORD_TRANSFORM_DEFAULTS[field])
        for field in _COORD_TRANSFORM_FIELDS
    }


def annotation_output_name(root: str | os.PathLike[str], *, prefix: str = "17173points") -> str:
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    directory = Path(root)
    for index in range(1, 100):
        name = f"{prefix}_{today}{index:02d}.json"
        if not (directory / name).exists():
            return name
    return f"{prefix}_{today}99.json"

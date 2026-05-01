"""Shared types and small helpers for annotation converters."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnnotationConversionReport:
    output_path: str = ""
    converted_points: int = 0
    skipped_points: int = 0
    deduplicated_points: int = 0
    errors: int = 0
    messages: list[str] = field(default_factory=list)


class UnsupportedAnnotationFormatError(ValueError):
    """Raised when a source annotation file is not supported by a converter."""


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("标注 JSON 顶层必须是对象")
    return payload


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def source_format_version(path: str | os.PathLike[str] | None) -> str:
    if not path:
        return ""
    source_path = Path(path).expanduser().resolve(strict=False)
    if not source_path.is_file():
        return ""
    try:
        payload = read_json(source_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    return str(payload.get("format_version") or "").strip()

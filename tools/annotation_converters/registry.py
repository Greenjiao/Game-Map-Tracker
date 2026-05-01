"""Registry for annotation conversion modes."""

from __future__ import annotations

import importlib
import os
import pkgutil
from pathlib import Path
from typing import Callable

from ui_island.services import resource_metadata

from .base import AnnotationConversionReport, UnsupportedAnnotationFormatError, read_json, source_format_version
from .legacy_coordinate_convert import convert_annotation_file as convert_legacy_coordinate_file

MODE_LEGACY_COORDINATES = "legacy_coordinates"
MODE_OUTSIDE_FORMAT = "outside_format"

OutsideConverter = Callable[[dict], dict]
_OUTSIDE_CONVERTERS: dict[str, OutsideConverter] = {}
_OUTSIDE_CONVERTERS_DISCOVERED = False


def register_outside_converter(format_version: str, converter: OutsideConverter) -> None:
    clean = str(format_version or "").strip()
    if not clean:
        raise ValueError("format_version is required")
    _OUTSIDE_CONVERTERS[clean] = converter


def discover_outside_converters() -> None:
    global _OUTSIDE_CONVERTERS_DISCOVERED
    if _OUTSIDE_CONVERTERS_DISCOVERED:
        return
    package_name = f"{__package__}.outside_convert"
    package = importlib.import_module(package_name)
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.ispkg or not module_info.name.endswith("_convert"):
            continue
        importlib.import_module(f"{package_name}.{module_info.name}")
    _OUTSIDE_CONVERTERS_DISCOVERED = True


def is_supported_source_format(path: str | os.PathLike[str] | None) -> bool:
    version = source_format_version(path)
    return bool(version and version in resource_metadata.default_enable_versions())


def convert_outside_annotation_file(
    source_file: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> AnnotationConversionReport:
    source_path = Path(source_file).expanduser().resolve(strict=False)
    if not source_path.is_file():
        raise FileNotFoundError(f"原标注文件不存在：{source_path}")

    payload = read_json(source_path)
    format_version = str(payload.get("format_version") or "").strip()
    if not format_version:
        raise UnsupportedAnnotationFormatError("原标注文件缺少 format_version，暂未兼容转换")
    if format_version not in resource_metadata.default_enable_versions():
        raise UnsupportedAnnotationFormatError(f"此格式版本暂未兼容转换：{format_version}")

    discover_outside_converters()
    converter = _OUTSIDE_CONVERTERS.get(format_version)
    if converter is None:
        raise UnsupportedAnnotationFormatError(f"未找到此格式版本的外部转换方法：{format_version}")

    converted_payload = converter(payload)
    if not isinstance(converted_payload, dict):
        raise ValueError("外部格式转换结果必须是 JSON 对象")
    resource_metadata.ensure_metadata(converted_payload, include_id=True)

    output_root = Path(output_dir).expanduser().resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / resource_metadata.annotation_output_name(output_root, prefix="annotations_outside_converted")

    from .base import write_json_atomic

    write_json_atomic(output_path, converted_payload)
    return AnnotationConversionReport(
        output_path=str(output_path),
        messages=[f"[完成] 已写入：{output_path}"],
    )


def convert_annotation_file(
    mode: str,
    source_file: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    merge: bool = True,
    merge_with: str | os.PathLike[str] | None = None,
) -> AnnotationConversionReport:
    if mode == MODE_LEGACY_COORDINATES:
        return convert_legacy_coordinate_file(source_file, output_dir, merge=merge, merge_with=merge_with)
    if mode == MODE_OUTSIDE_FORMAT:
        return convert_outside_annotation_file(source_file, output_dir)
    raise ValueError(f"未知标注转换模式：{mode}")

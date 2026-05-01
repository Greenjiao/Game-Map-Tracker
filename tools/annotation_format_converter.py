"""Compatibility entrypoints for annotation conversion."""

from __future__ import annotations

from tools.annotation_converters.base import AnnotationConversionReport
from tools.annotation_converters.legacy_coordinate_convert import (
    convert_annotation_file,
    convert_manual_old_big_map_annotation_payload,
    convert_old_big_map_annotation_payload,
    merge_annotation_payloads,
)

__all__ = [
    "AnnotationConversionReport",
    "convert_annotation_file",
    "convert_manual_old_big_map_annotation_payload",
    "convert_old_big_map_annotation_payload",
    "merge_annotation_payloads",
]

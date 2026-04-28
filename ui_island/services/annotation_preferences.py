"""Helpers for annotation type selection."""

from __future__ import annotations


def normalize_type_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        type_id = str(value or "").strip()
        if not type_id or type_id in seen:
            continue
        seen.add(type_id)
        result.append(type_id)
    return result

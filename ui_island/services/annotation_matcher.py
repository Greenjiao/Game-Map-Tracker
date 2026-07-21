"""Reusable coordinate matching helpers for annotation points."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_MATCH_RADIUS = 12.0
AMBIGUOUS_DISTANCE_DELTA = 5.0


@dataclass(frozen=True)
class AnnotationMatchCandidate:
    type_id: str
    type_name: str
    point_index: int
    x: float
    y: float
    distance: float
    label: str = ""
    point: dict | None = None


@dataclass(frozen=True)
class _AnnotationEntry:
    type_id: str
    type_name: str
    point_index: int
    x: float
    y: float
    label: str
    point: dict


def load_annotation_payload(path: str | Path) -> dict:
    file_path = Path(path).expanduser()
    with file_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("标注 JSON 顶层必须是对象")
    if not isinstance(payload.get("types"), list) or not isinstance(payload.get("pointsByType"), dict):
        raise ValueError("标注 JSON 缺少 types 或 pointsByType")
    return payload


def normalize_type_ids(type_ids: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in type_ids or []:
        type_id = str(value or "").strip()
        if not type_id or type_id in seen:
            continue
        seen.add(type_id)
        result.append(type_id)
    return result


def annotation_type_items(payload: dict) -> list[dict]:
    types = payload.get("types") if isinstance(payload, dict) else None
    if not isinstance(types, list):
        return []
    result: list[dict] = []
    for item in types:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("typeId") or "").strip()
        if not type_id:
            continue
        copied = dict(item)
        copied["typeId"] = type_id
        copied["type"] = str(copied.get("type") or type_id)
        result.append(copied)
    return result


def load_annotation_type_items(path: str | Path) -> list[dict]:
    return annotation_type_items(load_annotation_payload(path))


class AnnotationMatchIndex:
    def __init__(self, payload: dict) -> None:
        self.type_items = annotation_type_items(payload)
        self._type_names = {
            str(item.get("typeId") or ""): str(item.get("type") or item.get("typeId") or "")
            for item in self.type_items
        }
        self._type_order = {str(item.get("typeId") or ""): index for index, item in enumerate(self.type_items)}
        self._entries = self._build_entries(payload)

    @classmethod
    def from_file(cls, path: str | Path) -> "AnnotationMatchIndex":
        return cls(load_annotation_payload(path))

    def _build_entries(self, payload: dict) -> list[_AnnotationEntry]:
        points_by_type = payload.get("pointsByType")
        if not isinstance(points_by_type, dict):
            return []
        ordered_type_ids = [str(item.get("typeId") or "") for item in self.type_items]
        ordered_type_ids.extend(
            str(type_id)
            for type_id in points_by_type
            if str(type_id) not in set(ordered_type_ids)
        )

        entries: list[_AnnotationEntry] = []
        for type_id in ordered_type_ids:
            points = points_by_type.get(type_id)
            if not isinstance(points, list):
                continue
            type_name = self._type_names.get(type_id, type_id)
            for point_index, point in enumerate(points):
                if not isinstance(point, dict):
                    continue
                try:
                    x = float(point["x"])
                    y = float(point["y"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                entries.append(
                    _AnnotationEntry(
                        type_id=type_id,
                        type_name=type_name or str(point.get("type") or type_id),
                        point_index=point_index,
                        x=x,
                        y=y,
                        label=str(point.get("label") or ""),
                        point=point,
                    )
                )
        return entries

    def find_candidates(
        self,
        x: float,
        y: float,
        type_ids: Iterable[object] | None,
        *,
        max_radius: float = DEFAULT_MATCH_RADIUS,
    ) -> list[AnnotationMatchCandidate]:
        radius = float(max_radius)
        if radius <= 0:
            return []
        allowed = set(normalize_type_ids(type_ids))
        if not allowed:
            return []

        result: list[AnnotationMatchCandidate] = []
        px = float(x)
        py = float(y)
        for entry in self._entries:
            if entry.type_id not in allowed:
                continue
            distance = math.hypot(entry.x - px, entry.y - py)
            if distance > radius:
                continue
            result.append(
                AnnotationMatchCandidate(
                    type_id=entry.type_id,
                    type_name=entry.type_name,
                    point_index=entry.point_index,
                    x=entry.x,
                    y=entry.y,
                    distance=distance,
                    label=entry.label,
                    point=dict(entry.point),
                )
            )
        result.sort(key=lambda item: (item.distance, self._type_order.get(item.type_id, 1_000_000), item.point_index))
        return result


def suspicious_candidates(
    candidates: list[AnnotationMatchCandidate],
    *,
    distance_delta: float = AMBIGUOUS_DISTANCE_DELTA,
) -> list[AnnotationMatchCandidate]:
    if len(candidates) < 2:
        return []
    best_distance = candidates[0].distance
    return [candidate for candidate in candidates[1:] if candidate.distance - best_distance <= float(distance_delta)]


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _teleport_source_names(teleport_dir: str | Path) -> set[str]:
    folder = Path(teleport_dir).expanduser()
    if not folder.is_dir():
        return set()
    names: set[str] = set()
    for path in sorted(folder.glob("*.json")):
        stem = _normalized_name(path.stem)
        if stem:
            names.add(stem)
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        name = _normalized_name(payload.get("name"))
        if name:
            names.add(name)
        aliases = payload.get("annotationTypes")
        if isinstance(aliases, list):
            for alias in aliases:
                if not isinstance(alias, str):
                    continue
                normalized_alias = _normalized_name(alias)
                if normalized_alias:
                    names.add(normalized_alias)
    return names


def default_teleport_type_ids_from_folder(annotation_file: str | Path, teleport_dir: str | Path) -> list[str]:
    names = _teleport_source_names(teleport_dir)
    if not names:
        return []
    result: list[str] = []
    for item in load_annotation_type_items(annotation_file):
        type_name = _normalized_name(item.get("type"))
        if type_name in names:
            result.append(str(item.get("typeId") or ""))
    return normalize_type_ids(result)

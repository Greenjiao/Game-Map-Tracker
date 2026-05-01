"""Dataclass state containers for island window subsystems."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QCheckBox, QFrame, QLineEdit, QPushButton

from ui_island.state.tracking import TrackResult, TrackState


@dataclass
class WindowModeState:
    mode_before_max: object | None = None
    applying_mode: bool = False
    preferred_right_edge: int | None = None


@dataclass
class WindowLayoutPrefs:
    sidebar_collapsed: bool = False
    sidebar_width: int = 320
    paused_sidebar_width: int = 320
    normal_minimum_width: int = 0
    normal_minimum_height: int = 0
    compact_minimum_height: int = 0
    sidebar_collapsed_before_pause: bool | None = None
    sidebar_width_before_pause: int | None = None
    sidebar_collapsed_before_max: bool | None = None
    sidebar_width_before_max: int | None = None
    sidebar_expand_restore_geometry: QRect | None = None
    geometry_before_max: QRect | None = None
    size_prefs: dict[object, tuple[int, int]] = field(default_factory=dict)


@dataclass
class RoutePanelState:
    route_checkboxes: dict[str, list[QCheckBox]] = field(default_factory=dict)
    route_widgets_by_category: dict[str, list[tuple[str, object]]] = field(default_factory=dict)
    route_sections: dict[str, object] = field(default_factory=dict)
    route_section_expanded: dict[str, bool] = field(default_factory=dict)
    active_route_rename_item: object | None = None
    adding_category: bool = False
    add_category_row: QFrame | None = None
    add_category_input: QLineEdit | None = None
    add_category_confirm_btn: QPushButton | None = None
    add_category_cancel_btn: QPushButton | None = None
    search_term: str = ""


@dataclass
class RouteDrawingState:
    active: bool = False
    paused: bool = False
    route_id: str = ""
    category: str = ""
    name: str = ""
    original_points: list[dict] = field(default_factory=list)
    draft_points: list[dict] = field(default_factory=list)
    original_count: int = 0
    loop: bool = False
    original_loop: bool = False
    node_type: str = "collect"
    insert_at_end: bool = True
    add_node_annotation: bool = False
    same_annotation_type: bool = False
    annotation_type: str = ""
    annotation_type_id: str = ""
    hide_other_routes: bool = False
    undo_stack: list[dict] = field(default_factory=list)
    dirty: bool = False
    added_count: int = 0

    def reset(self) -> None:
        self.active = False
        self.paused = False
        self.route_id = ""
        self.category = ""
        self.name = ""
        self.original_points = []
        self.draft_points = []
        self.original_count = 0
        self.loop = False
        self.original_loop = False
        self.node_type = "collect"
        self.insert_at_end = True
        self.add_node_annotation = False
        self.same_annotation_type = False
        self.annotation_type = ""
        self.annotation_type_id = ""
        self.hide_other_routes = False
        self.undo_stack = []
        self.dirty = False
        self.added_count = 0

    def begin(
        self,
        *,
        route_id: str,
        category: str,
        name: str,
        points: list[dict],
        loop: bool = False,
    ) -> None:
        copied = deepcopy(points)
        self.reset()
        self.active = True
        self.route_id = route_id
        self.category = category
        self.name = name
        self.original_points = deepcopy(copied)
        self.draft_points = copied
        self.original_count = len(copied)
        self.loop = bool(loop)
        self.original_loop = bool(loop)


@dataclass
class TrackingState:
    locked: bool = False
    running: bool = True
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=30))
    last_result: TrackResult | None = None
    last_player_xy: tuple[int, int] | None = None
    display_stable_xy: tuple[int, int] | None = None
    display_pending_locked_xy: tuple[int, int] | None = None
    display_pending_locked_count: int = 0
    display_needs_lock_confirmation: bool = False
    latest_minimap: np.ndarray | None = None
    tracking_attempts_paused: bool = False
    tracking_paused_state: TrackState = TrackState.SEARCHING
    jump_anomaly_count: int = 0
    preferred_locked: bool = False
    lock_state_before_lost: bool | None = None
    restore_lock_after_relocate: bool | None = None
    tracking_bootstrap_pending: bool = False


@dataclass
class HotkeyState:
    listener: object | None = None
    thread: object | None = None
    thread_id: int | None = None
    last_hotkey_at: float = 0.0
    alt_pressed: bool = False

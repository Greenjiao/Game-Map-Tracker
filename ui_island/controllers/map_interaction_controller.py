"""Controller that glues map interactions (right-click insert) to RouteManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

import config
from ..design import strings
from ..dialogs import toast
from ..dialogs.annotation_type_picker import open_annotation_type_picker
from ..dialogs.insert_point_dialog import open_insert_point_dialog
from ..dialogs.settings_dialog import styled_confirm, styled_info
from ..services.annotation_preferences import normalize_type_ids
from ..widgets.node_type_popup import node_type_label, normalize_node_type, show_node_type_popup

if TYPE_CHECKING:
    from ..app.window import IslandWindow


class MapInteractionController:
    def __init__(self, window: "IslandWindow") -> None:
        self.window = window

    def _refresh_annotation_ui(self) -> None:
        self.window.annotation_panel.load_index(config.app_path("tools", "points_all", "points.json"))
        self.window.annotation_panel.set_preferences(self.window.annotation_type_ids)
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def on_add_point_requested(self, x: int, y: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active:
            self.window.route_panel_controller.append_drawing_point(x, y)
            return
        self.add_point_to_routes(x, y)

    def add_annotation_point(self, x: int, y: int) -> None:
        route_mgr = self.window.route_mgr
        items = route_mgr.annotation_type_items()
        if not items:
            styled_info(
                self.window,
                strings.ANNOTATION_TYPE_PICKER_TITLE,
                strings.ANNOTATION_TYPE_PICKER_EMPTY,
            )
            return

        selected = open_annotation_type_picker(self.window, items, "")
        if selected is None:
            return

        type_id = str(selected.get("typeId") or "")
        type_name = str(selected.get("type") or type_id)
        if not route_mgr.add_annotation_point(x, y, type_id, type_name):
            styled_info(
                self.window,
                strings.MAP_ADD_ANNOTATION_FAIL_TITLE,
                strings.MAP_ADD_ANNOTATION_FAIL_BODY,
            )
            return

        selected_type_ids = normalize_type_ids([*self.window.annotation_type_ids, type_id])
        self.window.annotation_type_ids = selected_type_ids
        route_mgr.set_annotation_type_ids(selected_type_ids)
        self.window.window_prefs_store.save_annotation_preferences(selected_type_ids)
        self._refresh_annotation_ui()

        toast(self.window, strings.MAP_ADD_ANNOTATION_SUCCESS_FMT.format(name=type_name))

    def change_map_annotation(self, type_id: str, point_index: int) -> None:
        route_mgr = self.window.route_mgr
        items = route_mgr.annotation_type_items()
        if not items:
            styled_info(
                self.window,
                strings.ANNOTATION_TYPE_PICKER_TITLE,
                strings.ANNOTATION_TYPE_PICKER_EMPTY,
            )
            return

        selected = open_annotation_type_picker(self.window, items, type_id)
        if selected is None:
            return

        new_type_id = str(selected.get("typeId") or "")
        new_type_name = str(selected.get("type") or new_type_id)
        if not route_mgr.change_annotation_point_type(type_id, point_index, new_type_id, new_type_name):
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_CHANGE_FAIL_BODY,
            )
            return

        selected_type_ids = normalize_type_ids([*self.window.annotation_type_ids, new_type_id])
        self.window.annotation_type_ids = selected_type_ids
        route_mgr.set_annotation_type_ids(selected_type_ids)
        self.window.window_prefs_store.save_annotation_preferences(selected_type_ids)
        self._refresh_annotation_ui()
        toast(self.window, strings.MAP_ANNOTATION_CHANGE_SUCCESS_FMT.format(name=new_type_name))

    def add_annotation_to_route(self, type_id: str, point_index: int) -> None:
        point = self.window.route_mgr.annotation_point(type_id, point_index)
        if point is None:
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_ROUTE_FAIL_BODY,
            )
            return
        try:
            x = int(round(float(point["x"])))
            y = int(round(float(point["y"])))
        except (KeyError, TypeError, ValueError):
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_ROUTE_FAIL_BODY,
            )
            return
        self.add_point_to_routes(x, y, point_fields=point)

    def delete_map_annotation(self, type_id: str, point_index: int) -> None:
        confirmed = styled_confirm(
            self.window,
            strings.MAP_ANNOTATION_DELETE_TITLE,
            strings.MAP_ANNOTATION_DELETE_BODY,
            confirm_text=strings.DELETE_POINT_CONFIRM,
            cancel_text=strings.DELETE_POINT_CANCEL,
        )
        if not confirmed:
            return

        if not self.window.route_mgr.delete_annotation_point(type_id, point_index):
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_DELETE_FAIL_BODY,
            )
            return

        self._refresh_annotation_ui()
        toast(self.window, strings.MAP_ANNOTATION_DELETE_SUCCESS)

    def on_delete_point_requested(self, route_id: str, point_index: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.delete_drawing_point(point_index)
            return
        self.delete_points_from_routes({route_id: [point_index]})

    def mark_point_visited(self, route_id: str, point_index: int, visited: bool) -> None:
        if not self.window.route_mgr.set_point_visited(route_id, point_index, visited):
            print(f"Mark point visited failed route_id={route_id} point_index={point_index}")
            return
        self._refresh_route_point_ui()

    def _refresh_route_point_ui(self) -> None:
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

    def change_point_node_type(self, route_id: str, point_index: int, global_pos) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.change_drawing_point_node_type(point_index, global_pos)
            return

        route_mgr = self.window.route_mgr
        route = route_mgr.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or not isinstance(point_index, int) or not (0 <= point_index < len(points)):
            styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
            return
        point = points[point_index]
        if not isinstance(point, dict):
            styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
            return

        current = normalize_node_type(point.get("node_type"))
        if normalize_node_type(point.get("node_type")) != point.get("node_type"):
            if not route_mgr.set_point_node_type(route_id, point_index, current):
                styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
                return
            self._refresh_route_point_ui()

        def apply_node_type(node_type: str) -> None:
            normalized = normalize_node_type(node_type)
            if normalized == current:
                return
            if not route_mgr.set_point_node_type(route_id, point_index, normalized):
                styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
                return
            self._refresh_route_point_ui()
            toast(self.window, strings.POINT_NODE_TYPE_SUCCESS_FMT.format(name=node_type_label(normalized)))

        self.window._node_type_popup = show_node_type_popup(
            self.window.map_view,
            global_pos,
            current,
            apply_node_type,
        )

    def change_point_annotation(self, route_id: str, point_index: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.change_drawing_point_annotation(point_index)
            return

        route_mgr = self.window.route_mgr
        items = route_mgr.annotation_type_items()
        if not items:
            styled_info(
                self.window,
                strings.ANNOTATION_TYPE_PICKER_TITLE,
                strings.ANNOTATION_TYPE_PICKER_EMPTY,
            )
            return

        current_type_id = route_mgr.route_point_annotation_type_id(route_id, point_index)
        selected = open_annotation_type_picker(self.window, items, current_type_id)
        if selected is None:
            return

        type_id = str(selected.get("typeId") or "")
        type_name = str(selected.get("type") or type_id)
        if not route_mgr.set_point_annotation(route_id, point_index, type_id, type_name):
            styled_info(
                self.window,
                strings.POINT_ANNOTATION_FAIL_TITLE,
                strings.POINT_ANNOTATION_FAIL_BODY,
            )
            return

        toast(self.window, strings.POINT_ANNOTATION_SUCCESS_FMT.format(name=type_name))
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

    def delete_point_annotation(self, route_id: str, point_index: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.clear_drawing_point_annotation(point_index)
            return

        if not self.window.route_mgr.clear_point_annotation(route_id, point_index):
            styled_info(
                self.window,
                strings.POINT_ANNOTATION_FAIL_TITLE,
                strings.POINT_ANNOTATION_DELETE_FAIL_BODY,
            )
            return

        toast(self.window, strings.POINT_ANNOTATION_DELETE_SUCCESS)
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

    def delete_points_from_routes(self, deletions: dict[str, list[int]]) -> None:
        """可复用的批量删除入口:命中节点右键、未来的批量选择器都走这里。
        负责 confirm + 调用数据层 + toast 反馈 + 视图刷新。
        """
        route_mgr = self.window.route_mgr
        normalized: dict[str, list[int]] = {}
        for rid, idx_list in (deletions or {}).items():
            if not rid:
                continue
            idx_clean = [i for i in (idx_list or []) if isinstance(i, int) and not isinstance(i, bool)]
            if idx_clean:
                normalized[rid] = sorted(set(idx_clean))
        if not normalized:
            return

        requested = sum(len(v) for v in normalized.values())
        route_count = len(normalized)
        if route_count == 1:
            only_rid, only_idx = next(iter(normalized.items()))
            summary = route_mgr.summarize_route(only_rid)
            name = summary["display_label"] if summary else ""
            if len(only_idx) == 1:
                body = strings.DELETE_POINT_SINGLE_BODY_FMT.format(name=name, pos=only_idx[0] + 1)
            else:
                body = strings.DELETE_POINT_MULTI_SINGLE_ROUTE_FMT.format(name=name, count=len(only_idx))
        else:
            body = strings.DELETE_POINT_MULTI_ROUTES_FMT.format(routes=route_count, count=requested)

        confirmed = styled_confirm(
            self.window,
            strings.DELETE_POINT_TITLE,
            body,
            confirm_text=strings.DELETE_POINT_CONFIRM,
            cancel_text=strings.DELETE_POINT_CANCEL,
        )
        if not confirmed:
            return

        outcomes = route_mgr.delete_points_from_routes(normalized)
        ok_count = sum(len(v) for v in outcomes.values())
        fail_count = requested - ok_count

        if ok_count == 0:
            styled_info(
                self.window,
                strings.DELETE_POINT_FAIL_TITLE,
                strings.DELETE_POINT_FAIL_BODY,
            )
            return

        if fail_count > 0:
            toast(self.window, strings.DELETE_POINT_PARTIAL_FMT.format(ok=ok_count, fail=fail_count))
        else:
            toast(self.window, strings.DELETE_POINT_SUCCESS_FMT.format(count=ok_count))

        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

    def add_point_to_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str] | None = None,
        show_dialog: bool = True,
        point_fields: dict | None = None,
    ) -> None:
        """可复用入口:右键菜单与未来的"加入玩家定位"按钮都走这里。
        route_ids=None 时默认所有当前可见(追踪中)的路线。
        """
        route_mgr = self.window.route_mgr
        if route_ids is None:
            candidate_ids = route_mgr.visible_route_ids()
        else:
            candidate_ids = [rid for rid in route_ids if rid]

        if not candidate_ids:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return

        candidates = []
        for rid in candidate_ids:
            summary = route_mgr.summarize_route(rid)
            if summary is None:
                continue
            suggested = route_mgr.suggest_insertion_index(rid, x, y)
            if suggested is None:
                suggested = summary["points_count"]
            candidates.append({
                "route_id": rid,
                "display_label": summary["display_label"],
                "points_count": summary["points_count"],
                "suggested_index": int(suggested),
            })

        if not candidates:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return

        if show_dialog:
            result = open_insert_point_dialog(self.window, x, y, candidates)
            if result is None:
                return
            selected_ids, overrides = result
            if not selected_ids:
                return
        else:
            selected_ids = [candidate["route_id"] for candidate in candidates]
            overrides = {}

        if show_dialog and len(selected_ids) > 1:
            confirmed = styled_confirm(
                self.window,
                strings.INSERT_POINT_MULTI_WARN_TITLE,
                strings.INSERT_POINT_MULTI_WARN_BODY,
                confirm_text=strings.INSERT_POINT_CONFIRM,
                cancel_text=strings.INSERT_POINT_CANCEL,
            )
            if not confirmed:
                return

        outcomes = route_mgr.insert_point_into_routes(x, y, selected_ids, overrides, point_fields=point_fields)
        ok_count = sum(1 for v in outcomes.values() if v is not None)
        fail_count = len(outcomes) - ok_count

        if ok_count == 0:
            styled_info(
                self.window,
                strings.INSERT_POINT_FAIL_TITLE,
                strings.INSERT_POINT_FAIL_BODY,
            )
            return

        if fail_count > 0:
            toast(self.window, strings.INSERT_POINT_PARTIAL_FMT.format(ok=ok_count, fail=fail_count))
        else:
            toast(self.window, strings.INSERT_POINT_SUCCESS_FMT.format(count=ok_count))

        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

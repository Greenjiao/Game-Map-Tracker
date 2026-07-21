"""Controller that glues map interactions (right-click insert) to RouteManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

import config
from ..design import strings
from ..dialogs import toast
from ..dialogs.annotation_type_picker import open_annotation_match_candidate_picker, open_annotation_type_picker
from ..dialogs.insert_point_dialog import open_insert_point_dialog
from ..dialogs.point_order_dialog import open_point_order_dialog
from ..dialogs.settings_dialog import styled_confirm, styled_info
from ..dialogs.text_input_dialog import prompt_text_input
from ..services.annotation_preferences import normalize_type_ids
from ..services.annotation_matcher import (
    AMBIGUOUS_DISTANCE_DELTA,
    DEFAULT_MATCH_RADIUS,
    AnnotationMatchCandidate,
    AnnotationMatchIndex,
    suspicious_candidates,
)
from ..services.route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL
from ..widgets.node_type_popup import node_type_label, normalize_node_type, show_node_type_popup

if TYPE_CHECKING:
    from ..app.window import IslandWindow


class MapInteractionController:
    def __init__(self, window: "IslandWindow") -> None:
        self.window = window
        self._last_point_move_undo: dict | None = None

    def _coordinate_adapter(self):
        getter = getattr(getattr(self.window, "map_view", None), "coordinate_adapter", None)
        return getter() if callable(getter) else None

    def _set_point_position(self, *args, coord_adapter=None, **kwargs) -> bool:
        try:
            return self.window.route_mgr.set_point_position(*args, coord_adapter=coord_adapter, **kwargs)
        except TypeError:
            return self.window.route_mgr.set_point_position(*args, **kwargs)

    def _refresh_annotation_ui(self) -> None:
        self.window.annotation_panel.load_index(config.selected_annotation_path_from_settings())
        self.window.annotation_panel.set_preferences(self.window.annotation_type_ids)
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def _annotation_file_path(self) -> str:
        return config.selected_annotation_path_from_settings()

    def _annotation_match_index(self) -> AnnotationMatchIndex | None:
        path = self._annotation_file_path()
        if not path:
            return None
        try:
            return AnnotationMatchIndex.from_file(path)
        except Exception as exc:
            print(f"Load annotation matcher failed {path}: {exc}")
            return None

    def _teleport_type_ids(self) -> set[str]:
        path = self._annotation_file_path()
        if not path:
            return set()
        try:
            from tools.route_format_converter import default_route_teleport_type_ids

            return set(default_route_teleport_type_ids(path))
        except Exception as exc:
            print(f"Load route teleport type ids failed {path}: {exc}")
            return set()

    def _all_annotation_type_ids(self) -> set[str]:
        result: set[str] = set()
        for item in self.window.route_mgr.annotation_type_items():
            if not isinstance(item, dict):
                continue
            type_id = str(item.get("typeId") or "").strip()
            if type_id:
                result.add(type_id)
        return result

    @staticmethod
    def _filter_annotation_items(items: list[dict], type_ids: set[str]) -> list[dict]:
        if not type_ids:
            return []
        return [dict(item) for item in items if str(item.get("typeId") or "") in type_ids]

    @staticmethod
    def _point_fields_from_candidate(candidate: AnnotationMatchCandidate, node_type: str) -> dict:
        return {
            "typeId": candidate.type_id,
            "type": candidate.type_name or candidate.type_id,
            "node_type": node_type,
        }

    def _node_type_for_annotation_type(self, type_id: str) -> str:
        return NODE_TYPE_TELEPORT if str(type_id or "") in self._teleport_type_ids() else NODE_TYPE_COLLECT

    def _annotation_type_name(self, type_id: str) -> str:
        type_id = str(type_id or "").strip()
        if not type_id:
            return ""
        for item in self.window.route_mgr.annotation_type_items():
            if not isinstance(item, dict) or str(item.get("typeId") or "").strip() != type_id:
                continue
            return str(item.get("type") or type_id).strip() or type_id
        return type_id

    def _point_fields_for_annotation_type(
        self,
        type_id: str,
        type_name: str | None = None,
        source_fields: dict | None = None,
    ) -> dict:
        type_id = str(type_id or "").strip()
        type_name = str(type_name or self._annotation_type_name(type_id) or type_id).strip() or type_id
        fields = dict(source_fields or {})
        fields["typeId"] = type_id
        fields["type"] = type_name
        fields["node_type"] = self._node_type_for_annotation_type(type_id)
        return fields

    def _candidate_type_ids_for_node_type(self, node_type: str) -> set[str]:
        all_ids = self._all_annotation_type_ids()
        teleport_ids = self._teleport_type_ids()
        if node_type == NODE_TYPE_TELEPORT:
            return all_ids & teleport_ids
        if node_type == NODE_TYPE_COLLECT:
            return all_ids - teleport_ids
        return set()

    def _annotation_fields_for_route_node(self, x: int, y: int, node_type: str) -> dict | None:
        allowed_ids = self._candidate_type_ids_for_node_type(node_type)
        items = self._filter_annotation_items(self.window.route_mgr.annotation_type_items(), allowed_ids)
        if not allowed_ids or not items:
            styled_info(
                self.window,
                strings.ANNOTATION_TYPE_PICKER_TITLE,
                strings.ANNOTATION_TYPE_PICKER_EMPTY,
            )
            return None

        matcher = self._annotation_match_index()
        if matcher is not None:
            candidates = matcher.find_candidates(
                x,
                y,
                allowed_ids,
                max_radius=DEFAULT_MATCH_RADIUS,
            )
            if candidates:
                ambiguous = suspicious_candidates(candidates, distance_delta=AMBIGUOUS_DISTANCE_DELTA)
                if ambiguous:
                    selected = open_annotation_match_candidate_picker(
                        self.window,
                        candidates,
                        title=strings.ANNOTATION_TYPE_PICKER_TITLE,
                    )
                    if selected is None:
                        return None
                    return self._point_fields_from_candidate(selected, node_type)
                return self._point_fields_from_candidate(candidates[0], node_type)

        selected = open_annotation_type_picker(self.window, items, "")
        if selected is None:
            return None
        type_id = str(selected.get("typeId") or "").strip()
        if not type_id:
            return None
        return {
            "typeId": type_id,
            "type": str(selected.get("type") or type_id).strip() or type_id,
            "node_type": node_type,
        }

    def on_add_point_requested(self, x: int, y: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active:
            self.window.route_panel_controller.append_drawing_point_from_context_menu(x, y)
            return
        self.add_point_to_routes(x, y)

    def add_route_node_from_context_menu(
        self,
        x: int,
        y: int,
        node_type: object,
        route_ids: list[str] | None = None,
        show_dialog: bool = True,
    ) -> None:
        normalized = normalize_node_type(node_type)
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and drawing.paused:
            return
        candidate_route_ids = (
            self.window.route_mgr.visible_route_ids()
            if route_ids is None
            else [route_id for route_id in route_ids if route_id]
        )
        if not (drawing is not None and drawing.active) and not candidate_route_ids:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return
        point_fields: dict = {"node_type": normalized}
        if normalized in {NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT}:
            annotation_fields = self._annotation_fields_for_route_node(x, y, normalized)
            if annotation_fields is None:
                return
            point_fields.update(annotation_fields)

        if drawing is not None and drawing.active:
            self.window.route_panel_controller.append_drawing_point_from_context_menu(
                x,
                y,
                point_fields=point_fields,
                node_type_override=normalized,
            )
            return
        if route_ids is None and show_dialog:
            self.add_point_to_routes(x, y, point_fields=point_fields)
        else:
            self.add_point_to_routes(
                x,
                y,
                route_ids=route_ids,
                show_dialog=show_dialog,
                point_fields=point_fields,
            )

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
        try:
            added = route_mgr.add_annotation_point(
                x,
                y,
                type_id,
                type_name,
                coord_adapter=self._coordinate_adapter(),
            )
        except TypeError:
            added = route_mgr.add_annotation_point(x, y, type_id, type_name)
        if not added:
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

    def add_annotated_point_to_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str] | None = None,
        show_dialog: bool = True,
    ) -> None:
        route_mgr = self.window.route_mgr
        candidate_route_ids = (
            route_mgr.visible_route_ids()
            if route_ids is None
            else [route_id for route_id in route_ids if route_id]
        )
        if not candidate_route_ids:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return

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

        type_id = str(selected.get("typeId") or "").strip()
        if not type_id:
            return
        type_name = str(selected.get("type") or type_id).strip() or type_id
        point_fields = self._point_fields_for_annotation_type(type_id, type_name)
        if route_ids is None and show_dialog:
            self.add_point_to_routes(x, y, point_fields=point_fields)
        else:
            self.add_point_to_routes(
                x,
                y,
                route_ids=route_ids,
                show_dialog=show_dialog,
                point_fields=point_fields,
            )

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

    def change_map_annotation_label(self, type_id: str, point_index: int) -> None:
        point = self.window.route_mgr.annotation_point(type_id, point_index)
        if point is None:
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_LABEL_CHANGE_FAIL_BODY,
            )
            return

        accepted, new_label = prompt_text_input(
            self.window,
            title=strings.MAP_ANNOTATION_LABEL_DIALOG_TITLE,
            label=strings.MAP_ANNOTATION_LABEL_PROMPT,
            value=str(point.get("label") or ""),
            placeholder=str(point.get("type") or type_id),
            confirm_text="确认修改",
        )
        if not accepted:
            return
        if not self.window.route_mgr.change_annotation_point_label(type_id, point_index, new_label):
            styled_info(
                self.window,
                strings.MAP_ANNOTATION_FAIL_TITLE,
                strings.MAP_ANNOTATION_LABEL_CHANGE_FAIL_BODY,
            )
            return

        self._refresh_annotation_ui()
        toast(
            self.window,
            strings.MAP_ANNOTATION_LABEL_CHANGE_SUCCESS
            if new_label
            else strings.MAP_ANNOTATION_LABEL_CLEAR_SUCCESS,
        )

    def add_annotation_to_route(self, type_id: str, point_index: int) -> None:
        try:
            point = self.window.route_mgr.annotation_point(
                type_id,
                point_index,
                coord_adapter=self._coordinate_adapter(),
            )
        except TypeError:
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
        type_id = str(point.get("typeId") or type_id).strip()
        point_fields = self._point_fields_for_annotation_type(type_id, point.get("type"), point)
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active:
            self.window.route_panel_controller.append_drawing_point_from_context_menu(
                x,
                y,
                point_fields=point_fields,
                node_type_override=point_fields.get("node_type"),
            )
            return
        self.add_point_to_routes(x, y, point_fields=point_fields)

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

    def _set_point_move_undo(self, action: dict | None) -> None:
        self._last_point_move_undo = action
        try:
            self.window.map_view.set_route_point_move_undo_available(action is not None)
        except Exception:
            pass

    def clear_route_point_move_undo(self) -> None:
        self._set_point_move_undo(None)

    def has_route_point_move_undo(self) -> bool:
        return self._last_point_move_undo is not None

    def _route_notes_controller(self):
        controller = getattr(self.window, "route_panel_controller", None)
        return controller if controller is not None else None

    def _has_route_notes_draft(self, route_id: str) -> bool:
        controller = self._route_notes_controller()
        checker = getattr(controller, "has_active_route_notes_draft", None)
        return bool(callable(checker) and checker(route_id))

    def _route_notes_draft_nodes(self, route_id: str) -> list[dict] | None:
        controller = self._route_notes_controller()
        getter = getattr(controller, "route_notes_draft_nodes", None)
        return getter(route_id) if callable(getter) else None

    def move_route_point_preview(self, route_id: str, point_index: int, x: int, y: int) -> None:
        if self._has_route_notes_draft(route_id):
            controller = self._route_notes_controller()
            mover = getattr(controller, "move_route_notes_point", None)
            if callable(mover) and mover(
                route_id,
                point_index,
                x,
                y,
                coord_adapter=self._coordinate_adapter(),
                refresh_panel=False,
            ):
                self._refresh_route_point_ui()
            return

        if not self._set_point_position(
            route_id,
            point_index,
            x,
            y,
            persist=False,
            coord_adapter=self._coordinate_adapter(),
        ):
            return
        self._refresh_route_point_ui()

    def finish_move_route_point(
        self,
        route_id: str,
        point_index: int,
        before_x: int,
        before_y: int,
        after_x: int,
        after_y: int,
    ) -> None:
        before = (int(before_x), int(before_y))
        after = (int(after_x), int(after_y))
        if before == after:
            return

        if self._has_route_notes_draft(route_id):
            controller = self._route_notes_controller()
            mover = getattr(controller, "move_route_notes_point", None)
            if callable(mover):
                mover(
                    route_id,
                    point_index,
                    after[0],
                    after[1],
                    coord_adapter=self._coordinate_adapter(),
                    refresh_panel=True,
                )
            self.clear_route_point_move_undo()
            self._refresh_route_point_ui()
            return

        route_mgr = self.window.route_mgr
        adapter = self._coordinate_adapter()
        self._set_point_position(route_id, point_index, before[0], before[1], persist=False, coord_adapter=adapter)
        if not self._set_point_position(route_id, point_index, after[0], after[1], persist=True, coord_adapter=adapter):
            self._set_point_position(route_id, point_index, before[0], before[1], persist=False, coord_adapter=adapter)
            self._refresh_route_point_ui()
            styled_info(self.window, strings.POINT_MOVE_FAIL_TITLE, strings.POINT_MOVE_FAIL_BODY)
            return

        self._set_point_move_undo({
            "op": "move",
            "route_id": route_id,
            "point_index": int(point_index),
            "before": before,
            "after": after,
        })
        self._refresh_route_point_ui()
        toast(self.window, strings.POINT_MOVE_SUCCESS)

    def undo_route_point_move(self) -> None:
        action = self._last_point_move_undo
        if not isinstance(action, dict):
            return
        route_id = str(action.get("route_id") or "")
        op = str(action.get("op") or "move")
        if op == "reorder":
            try:
                from_index = int(action.get("from_index"))
                to_index = int(action.get("to_index"))
            except (TypeError, ValueError):
                self.clear_route_point_move_undo()
                return
            if not self.window.route_mgr.reorder_route_point(route_id, to_index, from_index):
                styled_info(self.window, strings.POINT_ORDER_FAIL_TITLE, strings.POINT_ORDER_FAIL_BODY)
                return
            self.clear_route_point_move_undo()
            self._refresh_route_point_ui()
            toast(self.window, strings.POINT_ORDER_UNDO_SUCCESS)
            return

        try:
            point_index = int(action.get("point_index"))
            before = tuple(action.get("before") or ())
        except (TypeError, ValueError):
            self.clear_route_point_move_undo()
            return
        if len(before) != 2:
            self.clear_route_point_move_undo()
            return

        if not self._set_point_position(
            route_id,
            point_index,
            before[0],
            before[1],
            persist=True,
            coord_adapter=self._coordinate_adapter(),
        ):
            styled_info(self.window, strings.POINT_MOVE_FAIL_TITLE, strings.POINT_MOVE_FAIL_BODY)
            return

        self.clear_route_point_move_undo()
        self._refresh_route_point_ui()
        toast(self.window, strings.POINT_MOVE_UNDO_SUCCESS)

    def change_point_order(self, route_id: str, point_index: int) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.change_drawing_point_order(point_index)
            return
        if self._has_route_notes_draft(route_id):
            points = self._route_notes_draft_nodes(route_id) or []
            if not isinstance(point_index, int) or not (0 <= point_index < len(points)) or len(points) < 2:
                return
            route_mgr = self.window.route_mgr
            route = route_mgr.route_for_id(route_id)
            summary = route_mgr.summarize_route(route_id)
            route_name = str((summary or {}).get("display_label") or (route or {}).get("display_name") or route_id)
            target = open_point_order_dialog(self.window, route_name, point_index, len(points))
            if target is None or target == point_index:
                return
            controller = self._route_notes_controller()
            reorder = getattr(controller, "reorder_route_notes_point", None)
            if callable(reorder) and reorder(route_id, point_index, target):
                self.clear_route_point_move_undo()
                self._refresh_route_point_ui()
            return

        route_mgr = self.window.route_mgr
        route = route_mgr.route_for_id(route_id)
        points = route.get("points", []) if route is not None else []
        if route is None or not isinstance(points, list) or not isinstance(point_index, int):
            styled_info(self.window, strings.POINT_ORDER_FAIL_TITLE, strings.POINT_ORDER_FAIL_BODY)
            return
        if not (0 <= point_index < len(points)) or len(points) < 2:
            return

        summary = route_mgr.summarize_route(route_id)
        route_name = str((summary or {}).get("display_label") or route.get("display_name") or route_id)
        target = open_point_order_dialog(self.window, route_name, point_index, len(points))
        if target is None or target == point_index:
            return

        try:
            target = max(0, min(len(points) - 1, int(target)))
        except (TypeError, ValueError):
            return
        if target == point_index:
            return
        if not route_mgr.reorder_route_point(route_id, point_index, target):
            styled_info(self.window, strings.POINT_ORDER_FAIL_TITLE, strings.POINT_ORDER_FAIL_BODY)
            return

        self._set_point_move_undo({
            "op": "reorder",
            "route_id": route_id,
            "from_index": int(point_index),
            "to_index": int(target),
        })
        self._refresh_route_point_ui()
        toast(self.window, strings.POINT_ORDER_SUCCESS)

    def change_point_node_type(self, route_id: str, point_index: int, global_pos) -> None:
        drawing = getattr(self.window, "route_drawing_state", None)
        if drawing is not None and drawing.active and route_id == drawing.route_id:
            self.window.route_panel_controller.change_drawing_point_node_type(point_index, global_pos)
            return
        if self._has_route_notes_draft(route_id):
            points = self._route_notes_draft_nodes(route_id) or []
            if not isinstance(point_index, int) or not (0 <= point_index < len(points)):
                styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
                return
            point = points[point_index]
            if not isinstance(point, dict):
                styled_info(self.window, strings.POINT_NODE_TYPE_FAIL_TITLE, strings.POINT_NODE_TYPE_FAIL_BODY)
                return
            current = normalize_node_type(point.get("node_type"))
            controller = self._route_notes_controller()
            setter = getattr(controller, "set_route_notes_point_node_type", None)

            def apply_node_type(node_type: str) -> None:
                normalized = normalize_node_type(node_type)
                if normalized == current:
                    return
                if callable(setter) and setter(route_id, point_index, normalized):
                    self._refresh_route_point_ui()
                    toast(self.window, strings.POINT_NODE_TYPE_SUCCESS_FMT.format(name=node_type_label(normalized)))

            self.window._node_type_popup = show_node_type_popup(
                self.window.map_view,
                global_pos,
                current,
                apply_node_type,
            )
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
            self.window.route_panel_controller.change_drawing_point_annotation(
                point_index,
                node_type_resolver=self._node_type_for_annotation_type,
            )
            return
        if self._has_route_notes_draft(route_id):
            route_mgr = self.window.route_mgr
            items = route_mgr.annotation_type_items()
            if not items:
                styled_info(
                    self.window,
                    strings.ANNOTATION_TYPE_PICKER_TITLE,
                    strings.ANNOTATION_TYPE_PICKER_EMPTY,
                )
                return
            points = self._route_notes_draft_nodes(route_id) or []
            current_type_id = ""
            if isinstance(point_index, int) and 0 <= point_index < len(points) and isinstance(points[point_index], dict):
                current_type_id = str(points[point_index].get("typeId") or "")
            selected = open_annotation_type_picker(self.window, items, current_type_id)
            if selected is None:
                return
            type_id = str(selected.get("typeId") or "")
            type_name = str(selected.get("type") or type_id)
            node_type = self._node_type_for_annotation_type(type_id)
            controller = self._route_notes_controller()
            setter = getattr(controller, "set_route_notes_point_annotation", None)
            if not callable(setter) or not setter(route_id, point_index, type_id, type_name, node_type=node_type):
                styled_info(
                    self.window,
                    strings.POINT_ANNOTATION_FAIL_TITLE,
                    strings.POINT_ANNOTATION_FAIL_BODY,
                )
                return
            toast(self.window, strings.POINT_ANNOTATION_SUCCESS_FMT.format(name=type_name))
            self._refresh_route_point_ui()
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
        node_type = self._node_type_for_annotation_type(type_id)
        if not route_mgr.set_point_annotation(route_id, point_index, type_id, type_name, node_type=node_type):
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
        if self._has_route_notes_draft(route_id):
            controller = self._route_notes_controller()
            clearer = getattr(controller, "clear_route_notes_point_annotation", None)
            if not callable(clearer) or not clearer(route_id, point_index):
                styled_info(
                    self.window,
                    strings.POINT_ANNOTATION_FAIL_TITLE,
                    strings.POINT_ANNOTATION_DELETE_FAIL_BODY,
                )
                return
            toast(self.window, strings.POINT_ANNOTATION_DELETE_SUCCESS)
            self._refresh_route_point_ui()
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

        draft_ok_count = 0
        for route_id, indexes in list(normalized.items()):
            if not self._has_route_notes_draft(route_id):
                continue
            controller = self._route_notes_controller()
            deleter = getattr(controller, "delete_route_notes_points", None)
            if callable(deleter):
                count = int(deleter(route_id, indexes) or 0)
                draft_ok_count += count
            normalized.pop(route_id, None)

        if draft_ok_count and not normalized:
            if draft_ok_count != requested:
                toast(self.window, strings.DELETE_POINT_PARTIAL_FMT.format(ok=draft_ok_count, fail=requested - draft_ok_count))
            else:
                toast(self.window, strings.DELETE_POINT_SUCCESS_FMT.format(count=draft_ok_count))
            self.clear_route_point_move_undo()
            self._refresh_route_point_ui()
            return

        outcomes = route_mgr.delete_points_from_routes(normalized)
        ok_count = draft_ok_count + sum(len(v) for v in outcomes.values())
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

        self.clear_route_point_move_undo()
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
            try:
                suggested = route_mgr.suggest_insertion_index(
                    rid,
                    x,
                    y,
                    coord_adapter=self._coordinate_adapter(),
                )
            except TypeError:
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

        draft_success: dict[str, int | None] = {}
        persist_ids: list[str] = []
        for rid in selected_ids:
            if not self._has_route_notes_draft(rid):
                persist_ids.append(rid)
                continue
            nodes = self._route_notes_draft_nodes(rid) or []
            try:
                resource_x, resource_y = x, y
                adapter = self._coordinate_adapter()
                adapter_getter = getattr(route_mgr, "route_coordinate_adapter", None)
                if callable(adapter_getter):
                    adapter = adapter_getter(rid, adapter) or adapter
                if adapter is not None:
                    resource_x, resource_y = adapter.to_internal(float(x), float(y))
            except Exception:
                resource_x, resource_y = x, y
            new_point = {
                "id": route_mgr.new_route_point_id(),
                "x": int(round(float(resource_x))),
                "y": int(round(float(resource_y))),
                "node_type": "collect",
                "visited": False,
            }
            if isinstance(point_fields, dict):
                for key in ("label", "type", "typeId", "radius", "sourceId", "manual", "node_type"):
                    if key in point_fields:
                        new_point[key] = point_fields[key]
            target = overrides.get(rid)
            if target is None:
                try:
                    target = route_mgr.suggest_insertion_index(rid, x, y, coord_adapter=self._coordinate_adapter())
                except TypeError:
                    target = route_mgr.suggest_insertion_index(rid, x, y)
            try:
                target = int(target if target is not None else len(nodes))
            except (TypeError, ValueError):
                target = len(nodes)
            target = max(0, min(len(nodes), target))
            nodes.insert(target, new_point)
            controller = self._route_notes_controller()
            updater = getattr(controller, "update_route_notes_draft_nodes", None)
            if callable(updater) and updater(rid, nodes):
                draft_success[rid] = target
            else:
                draft_success[rid] = None

        if draft_success and not persist_ids:
            ok_count = sum(1 for value in draft_success.values() if value is not None)
            fail_count = len(draft_success) - ok_count
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
            self.clear_route_point_move_undo()
            self._refresh_route_point_ui()
            return

        try:
            outcomes = route_mgr.insert_point_into_routes(
                x,
                y,
                persist_ids if draft_success else selected_ids,
                overrides,
                point_fields=point_fields,
                coord_adapter=self._coordinate_adapter(),
            )
        except TypeError:
            outcomes = route_mgr.insert_point_into_routes(
                x,
                y,
                persist_ids if draft_success else selected_ids,
                overrides,
                point_fields=point_fields,
            )
        if draft_success:
            outcomes.update(draft_success)
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

        self.clear_route_point_move_undo()
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

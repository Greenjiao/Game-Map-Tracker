"""Shared parsing and validation for configurable global hotkeys."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

DEFAULT_TOGGLE_LOCK_HOTKEY = {
    "sequence": "Alt+`",
    "label": "Alt+`",
    "modifiers": ["Alt"],
    "key": "QuoteLeft",
    "vk": 0xC0,
}

ACTION_HOTKEY_ACTIONS = (
    "reset_view",
    "relocate",
    "start_navigation",
    "terminate_navigation",
    "jump_current_route_node",
    "add_current_position_to_current_route",
)

ACTION_HOTKEY_LABELS = {
    "reset_view": "重置视图",
    "relocate": "重定位",
    "start_navigation": "开始导航",
    "terminate_navigation": "终止导航",
    "jump_current_route_node": "跳转当前路线节点",
    "add_current_position_to_current_route": "角色位置加入当前路线",
}

DEFAULT_ACTION_HOTKEYS = {action: None for action in ACTION_HOTKEY_ACTIONS}

_MODIFIER_BITS = {
    "Ctrl": Qt.ControlModifier.value,
    "Alt": Qt.AltModifier.value,
    "Shift": Qt.ShiftModifier.value,
    "Meta": Qt.MetaModifier.value,
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Meta")
_WINDOWS_MODIFIER_FLAGS = {
    "Alt": 0x0001,
    "Ctrl": 0x0002,
    "Shift": 0x0004,
    "Meta": 0x0008,
}

_SPECIAL_QT_TO_VK = {
    Qt.Key_QuoteLeft.value: 0xC0,
    Qt.Key_AsciiTilde.value: 0xC0,
    Qt.Key_Escape.value: 0x1B,
    Qt.Key_Tab.value: 0x09,
    Qt.Key_Backtab.value: 0x09,
    Qt.Key_Backspace.value: 0x08,
    Qt.Key_Return.value: 0x0D,
    Qt.Key_Enter.value: 0x0D,
    Qt.Key_Insert.value: 0x2D,
    Qt.Key_Delete.value: 0x2E,
    Qt.Key_Home.value: 0x24,
    Qt.Key_End.value: 0x23,
    Qt.Key_PageUp.value: 0x21,
    Qt.Key_PageDown.value: 0x22,
    Qt.Key_Left.value: 0x25,
    Qt.Key_Up.value: 0x26,
    Qt.Key_Right.value: 0x27,
    Qt.Key_Down.value: 0x28,
    Qt.Key_Space.value: 0x20,
}


def default_hotkey() -> dict:
    return dict(DEFAULT_TOGGLE_LOCK_HOTKEY)


def _valid_hotkey_payload(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None

    modifiers = raw.get("modifiers")
    vk = raw.get("vk")
    key = raw.get("key")
    label = str(raw.get("label") or "").strip()
    sequence = str(raw.get("sequence") or "").strip()
    if (
        not isinstance(modifiers, list)
        or any(modifier not in _MODIFIER_BITS for modifier in modifiers)
        or not isinstance(vk, int)
        or not 1 <= vk <= 0xFE
        or not isinstance(key, str)
        or not key.strip()
    ):
        return None

    modifiers_set = set(modifiers)
    return {
        "sequence": sequence or label,
        "label": label or sequence,
        "modifiers": [modifier for modifier in _MODIFIER_ORDER if modifier in modifiers_set],
        "key": key.strip(),
        "vk": int(vk),
    }


def normalize_hotkey_payload(raw: object) -> dict:
    """Return a valid hotkey payload, falling back to the default when needed."""
    payload = _valid_hotkey_payload(raw)
    if payload is None:
        return default_hotkey()

    payload["sequence"] = payload["sequence"] or DEFAULT_TOGGLE_LOCK_HOTKEY["sequence"]
    payload["label"] = payload["label"] or DEFAULT_TOGGLE_LOCK_HOTKEY["label"]
    return payload


def normalize_optional_hotkey_payload(raw: object) -> dict | None:
    return _valid_hotkey_payload(raw)


def normalize_action_hotkeys(raw: object) -> dict[str, dict | None]:
    source = raw if isinstance(raw, dict) else {}
    return {
        action: normalize_optional_hotkey_payload(source.get(action))
        for action in ACTION_HOTKEY_ACTIONS
    }


def hotkey_label(raw: object) -> str:
    return str(normalize_hotkey_payload(raw)["label"])


def hotkey_sequence(raw: object, *, allow_empty: bool = False) -> QKeySequence:
    payload = normalize_optional_hotkey_payload(raw)
    if payload is None:
        if allow_empty:
            return QKeySequence()
        payload = default_hotkey()
    sequence = QKeySequence(str(payload["sequence"]))
    if sequence.count() == 0:
        sequence = QKeySequence(str(payload["label"]))
    if sequence.count() == 0:
        sequence = QKeySequence(DEFAULT_TOGGLE_LOCK_HOTKEY["sequence"])
    return sequence


def payload_from_key_sequence(
    sequence: QKeySequence,
    *,
    allow_empty: bool = False,
) -> tuple[dict | None, str | None]:
    if sequence.count() == 0:
        if allow_empty:
            return None, None
        return None, "请录入一个快捷键。"
    if sequence.count() != 1:
        return None, "快捷键必须是单个组合键。"

    combo = sequence[0]
    key_value = combo.key().value
    modifiers = _modifiers_from_flags(_flag_value(combo.keyboardModifiers()))
    vk = vk_from_qt_key(key_value)
    if vk is None:
        return None, "这个按键暂不支持注册为全局快捷键，请换一个组合。"

    key_name = key_name_from_qt_key(key_value)
    if key_name is None:
        return None, "这个按键暂不支持注册为全局快捷键，请换一个组合。"

    label = sequence.toString(QKeySequence.NativeText).strip()
    portable = sequence.toString(QKeySequence.PortableText).strip()
    if not label:
        label = portable
    return {
        "sequence": portable or label,
        "label": label or portable,
        "modifiers": modifiers,
        "key": key_name,
        "vk": vk,
    }, None


def hotkey_signature(raw: object) -> tuple[tuple[str, ...], int] | None:
    payload = normalize_optional_hotkey_payload(raw)
    if payload is None:
        return None
    return tuple(str(modifier) for modifier in payload["modifiers"]), int(payload["vk"])


def duplicate_hotkey_labels(items: list[tuple[str, object]]) -> tuple[str, str] | None:
    seen: dict[tuple[tuple[str, ...], int], str] = {}
    for label, payload in items:
        signature = hotkey_signature(payload)
        if signature is None:
            continue
        if signature in seen:
            return seen[signature], label
        seen[signature] = label
    return None


def key_name_from_qt_key(key_value: int) -> str | None:
    if key_value in (Qt.Key_QuoteLeft.value, Qt.Key_AsciiTilde.value):
        return "QuoteLeft"
    if Qt.Key_A.value <= key_value <= Qt.Key_Z.value:
        return chr(key_value)
    if Qt.Key_0.value <= key_value <= Qt.Key_9.value:
        return chr(key_value)
    if Qt.Key_F1.value <= key_value <= Qt.Key_F24.value:
        return f"F{key_value - Qt.Key_F1.value + 1}"
    for qt_key, name in (
        (Qt.Key_Escape.value, "Escape"),
        (Qt.Key_Tab.value, "Tab"),
        (Qt.Key_Backtab.value, "Tab"),
        (Qt.Key_Backspace.value, "Backspace"),
        (Qt.Key_Return.value, "Enter"),
        (Qt.Key_Enter.value, "Enter"),
        (Qt.Key_Insert.value, "Insert"),
        (Qt.Key_Delete.value, "Delete"),
        (Qt.Key_Home.value, "Home"),
        (Qt.Key_End.value, "End"),
        (Qt.Key_PageUp.value, "PageUp"),
        (Qt.Key_PageDown.value, "PageDown"),
        (Qt.Key_Left.value, "Left"),
        (Qt.Key_Up.value, "Up"),
        (Qt.Key_Right.value, "Right"),
        (Qt.Key_Down.value, "Down"),
        (Qt.Key_Space.value, "Space"),
    ):
        if key_value == qt_key:
            return name
    return None


def vk_from_qt_key(key_value: int) -> int | None:
    if Qt.Key_A.value <= key_value <= Qt.Key_Z.value:
        return key_value
    if Qt.Key_0.value <= key_value <= Qt.Key_9.value:
        return key_value
    if Qt.Key_F1.value <= key_value <= Qt.Key_F24.value:
        return 0x70 + (key_value - Qt.Key_F1.value)
    return _SPECIAL_QT_TO_VK.get(key_value)


def native_modifier_flags(raw: object) -> int:
    payload = normalize_hotkey_payload(raw)
    flags = 0
    for modifier in payload["modifiers"]:
        flags |= _WINDOWS_MODIFIER_FLAGS.get(str(modifier), 0)
    return flags


def modifier_names(raw: object) -> set[str]:
    return set(normalize_hotkey_payload(raw)["modifiers"])


def key_vk(raw: object) -> int:
    return int(normalize_hotkey_payload(raw)["vk"])


def qt_event_matches_hotkey(event, raw: object) -> bool:
    payload = normalize_optional_hotkey_payload(raw)
    if payload is None:
        return False
    event_modifiers = _modifiers_from_flags(_flag_value(event.modifiers()))
    if set(payload["modifiers"]) != set(event_modifiers):
        return False
    key_value = _flag_value(event.key())
    return key_value in compatible_qt_keys(payload)


def compatible_qt_keys(raw: object) -> set[int]:
    payload = normalize_hotkey_payload(raw)
    key = str(payload["key"])
    if key == "QuoteLeft":
        return {Qt.Key_QuoteLeft.value, Qt.Key_AsciiTilde.value}
    if len(key) == 1 and key.isalpha():
        return {ord(key.upper())}
    if len(key) == 1 and key.isdigit():
        return {ord(key)}
    if key.startswith("F") and key[1:].isdigit():
        index = int(key[1:])
        if 1 <= index <= 24:
            return {Qt.Key_F1.value + index - 1}
    mapping = {
        "Escape": {Qt.Key_Escape.value},
        "Tab": {Qt.Key_Tab.value, Qt.Key_Backtab.value},
        "Backspace": {Qt.Key_Backspace.value},
        "Enter": {Qt.Key_Return.value, Qt.Key_Enter.value},
        "Insert": {Qt.Key_Insert.value},
        "Delete": {Qt.Key_Delete.value},
        "Home": {Qt.Key_Home.value},
        "End": {Qt.Key_End.value},
        "PageUp": {Qt.Key_PageUp.value},
        "PageDown": {Qt.Key_PageDown.value},
        "Left": {Qt.Key_Left.value},
        "Up": {Qt.Key_Up.value},
        "Right": {Qt.Key_Right.value},
        "Down": {Qt.Key_Down.value},
        "Space": {Qt.Key_Space.value},
    }
    return mapping.get(key, {Qt.Key_QuoteLeft.value, Qt.Key_AsciiTilde.value})


def _modifiers_from_flags(flags: int) -> list[str]:
    return [modifier for modifier in _MODIFIER_ORDER if flags & _MODIFIER_BITS[modifier]]


def _flag_value(value: object) -> int:
    if hasattr(value, "value"):
        return int(value.value)
    return int(value)

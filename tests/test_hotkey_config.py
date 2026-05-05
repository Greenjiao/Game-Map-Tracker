import unittest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from ui_island.services.hotkey_config import (
    ACTION_HOTKEY_ACTIONS,
    DEFAULT_TOGGLE_LOCK_HOTKEY,
    duplicate_hotkey_labels,
    key_vk,
    normalize_action_hotkeys,
    normalize_hotkey_payload,
    payload_from_key_sequence,
    qt_event_matches_hotkey,
)


class HotkeyConfigTests(unittest.TestCase):
    def test_payload_from_key_sequence_accepts_supported_combinations(self) -> None:
        payload, error = payload_from_key_sequence(QKeySequence("Ctrl+Alt+L"))

        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["modifiers"], ["Ctrl", "Alt"])
        self.assertEqual(payload["key"], "L")
        self.assertEqual(payload["vk"], 0x4C)

    def test_payload_from_key_sequence_maps_default_grave_key_to_windows_vk(self) -> None:
        payload, error = payload_from_key_sequence(QKeySequence("Alt+`"))

        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["modifiers"], ["Alt"])
        self.assertEqual(payload["key"], "QuoteLeft")
        self.assertEqual(payload["vk"], 0xC0)

    def test_payload_from_key_sequence_accepts_single_key(self) -> None:
        payload, error = payload_from_key_sequence(QKeySequence("L"))

        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["modifiers"], [])
        self.assertEqual(payload["key"], "L")
        self.assertEqual(payload["vk"], 0x4C)

    def test_payload_from_key_sequence_allows_empty_optional_hotkey(self) -> None:
        payload, error = payload_from_key_sequence(QKeySequence(), allow_empty=True)

        self.assertIsNone(payload)
        self.assertIsNone(error)

    def test_payload_from_key_sequence_rejects_multi_step_sequence(self) -> None:
        payload, error = payload_from_key_sequence(QKeySequence("Ctrl+K, Ctrl+C"))

        self.assertIsNone(payload)
        self.assertIn("单个组合键", error)

    def test_normalize_hotkey_payload_falls_back_for_invalid_values(self) -> None:
        self.assertEqual(normalize_hotkey_payload("Alt+`"), DEFAULT_TOGGLE_LOCK_HOTKEY)
        self.assertEqual(key_vk({"modifiers": [], "vk": 0, "key": "", "label": ""}), 0xC0)

    def test_qt_event_matches_configured_hotkey(self) -> None:
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_L, Qt.ControlModifier | Qt.AltModifier)
        payload = {
            "sequence": "Ctrl+Alt+L",
            "label": "Ctrl+Alt+L",
            "modifiers": ["Ctrl", "Alt"],
            "key": "L",
            "vk": 0x4C,
        }

        self.assertTrue(qt_event_matches_hotkey(event, payload))

    def test_qt_event_requires_exact_modifiers(self) -> None:
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_L, Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        payload = {
            "sequence": "Ctrl+Alt+L",
            "label": "Ctrl+Alt+L",
            "modifiers": ["Ctrl", "Alt"],
            "key": "L",
            "vk": 0x4C,
        }

        self.assertFalse(qt_event_matches_hotkey(event, payload))

    def test_action_hotkeys_default_to_empty_and_detect_duplicates(self) -> None:
        normalized = normalize_action_hotkeys({})

        self.assertEqual(set(normalized), set(ACTION_HOTKEY_ACTIONS))
        self.assertTrue(all(value is None for value in normalized.values()))

        first = {
            "sequence": "L",
            "label": "L",
            "modifiers": [],
            "key": "L",
            "vk": 0x4C,
        }
        duplicate = dict(first)
        self.assertEqual(
            duplicate_hotkey_labels([("A", first), ("B", duplicate)]),
            ("A", "B"),
        )


if __name__ == "__main__":
    unittest.main()

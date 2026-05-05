import unittest
from unittest.mock import patch

from ui_island.controllers.hotkey_controller import HotkeyController


class _Signal:
    def __init__(self) -> None:
        self.values: list[str] = []

    def emit(self, value: str) -> None:
        self.values.append(value)


class _FakeWindow:
    _HOTKEY_DEBOUNCE_SEC = 0.0

    def __init__(self) -> None:
        self._hotkeys_suspended = False
        self._last_hotkey_at = 0.0
        self._hotkey_action_requested = _Signal()


class HotkeyControllerTests(unittest.TestCase):
    def test_configured_hotkeys_include_toggle_and_enabled_actions_only(self) -> None:
        action_payload = {
            "sequence": "R",
            "label": "R",
            "modifiers": [],
            "key": "R",
            "vk": 0x52,
        }
        with patch("config.ACTION_HOTKEYS", {"reset_view": action_payload, "relocate": None}, create=True):
            hotkeys = HotkeyController(_FakeWindow()).configured_hotkeys()

        self.assertEqual([action for action, _payload in hotkeys], ["toggle_lock", "reset_view"])

    def test_request_action_respects_suspension(self) -> None:
        window = _FakeWindow()
        controller = HotkeyController(window)

        controller.request_action("reset_view")
        self.assertEqual(window._hotkey_action_requested.values, ["reset_view"])

        controller.set_suspended(True)
        controller.request_action("relocate")
        self.assertEqual(window._hotkey_action_requested.values, ["reset_view"])


if __name__ == "__main__":
    unittest.main()

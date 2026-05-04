import unittest

from PySide6.QtCore import QPoint

from ui_island.app.window import IslandWindow


class _FakePanel:
    def __init__(self) -> None:
        self._pos = QPoint(0, 0)
        self.raised = False

    def move(self, pos) -> None:
        self._pos = QPoint(pos)

    def pos(self) -> QPoint:
        return QPoint(self._pos)

    def raise_(self) -> None:
        self.raised = True


class _FakePrefs:
    def __init__(self, *, follow: bool = True) -> None:
        self.follow = follow
        self.offsets = {False: None, True: None}
        self.positions = {False: None, True: None}
        self.saved_offsets: list[tuple[bool, dict]] = []
        self.saved_positions: list[tuple[bool, dict]] = []

    def load_annotation_panel_follow_window(self) -> bool:
        return self.follow

    def load_annotation_panel_offset(self, maximized: bool = False):
        return self.offsets[bool(maximized)]

    def load_annotation_panel_position(self, maximized: bool = False):
        return self.positions[bool(maximized)]

    def save_annotation_panel_offset(self, offset: dict, maximized: bool = False) -> None:
        self.saved_offsets.append((bool(maximized), dict(offset)))

    def save_annotation_panel_position(self, position: dict, maximized: bool = False) -> None:
        self.saved_positions.append((bool(maximized), dict(position)))


class _FakeWindow:
    def __init__(self, *, maximized: bool = False, follow: bool = True) -> None:
        self._maximized = maximized
        self.annotation_panel = _FakePanel()
        self.window_prefs_store = _FakePrefs(follow=follow)
        self.anchors = {
            False: QPoint(100, 200),
            True: QPoint(300, 40),
        }

    def _annotation_panel_is_maximized_context(self) -> bool:
        return self._maximized

    def _annotation_panel_default_anchor(self, maximized: bool) -> QPoint:
        return QPoint(self.anchors[bool(maximized)])

    def _clamp_annotation_panel_pos(self, pos: QPoint) -> QPoint:
        x = min(max(pos.x(), 0), 500)
        y = min(max(pos.y(), 0), 400)
        return QPoint(x, y)


class AnnotationPanelPositioningTests(unittest.TestCase):
    def test_follow_window_uses_mode_specific_relative_offset(self) -> None:
        window = _FakeWindow(follow=True)
        window.window_prefs_store.offsets[False] = {"x": 12, "y": -8}

        IslandWindow._position_annotation_panel(window)

        self.assertEqual(window.annotation_panel.pos(), QPoint(112, 192))
        self.assertTrue(window.annotation_panel.raised)

    def test_free_floating_uses_mode_specific_absolute_position(self) -> None:
        window = _FakeWindow(follow=False, maximized=True)
        window.window_prefs_store.positions[True] = {"x": 450, "y": 360}

        IslandWindow._position_annotation_panel(window)

        self.assertEqual(window.annotation_panel.pos(), QPoint(450, 360))

    def test_normal_and_maximized_memories_do_not_overlap(self) -> None:
        window = _FakeWindow(follow=True, maximized=True)
        window.window_prefs_store.offsets[False] = {"x": 10, "y": 10}
        window.window_prefs_store.offsets[True] = {"x": -20, "y": 30}

        IslandWindow._position_annotation_panel(window)

        self.assertEqual(window.annotation_panel.pos(), QPoint(280, 70))

    def test_drag_finish_saves_relative_offset_when_following_window(self) -> None:
        window = _FakeWindow(follow=True)

        IslandWindow._on_annotation_panel_drag_finished(window, 130, 240)

        self.assertEqual(window.window_prefs_store.saved_offsets, [(False, {"x": 30, "y": 40})])
        self.assertEqual(window.window_prefs_store.saved_positions, [])

    def test_drag_finish_saves_absolute_position_when_free_floating(self) -> None:
        window = _FakeWindow(follow=False, maximized=True)

        IslandWindow._on_annotation_panel_drag_finished(window, 900, 900)

        self.assertEqual(window.annotation_panel.pos(), QPoint(500, 400))
        self.assertEqual(window.window_prefs_store.saved_offsets, [])
        self.assertEqual(window.window_prefs_store.saved_positions, [(True, {"x": 500, "y": 400})])


if __name__ == "__main__":
    unittest.main()

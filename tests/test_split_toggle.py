from __future__ import annotations

import unittest

from app.windows.main_window import MainWindow


class FakeFocusView:
    def __init__(self, visible: bool) -> None:
        self.visible = visible
        self.show_calls = 0
        self.hide_calls = 0

    def is_split_panel_visible(self) -> bool:
        return self.visible

    def show_split_panel(self) -> None:
        self.show_calls += 1
        self.visible = True

    def hide_split_panel(self) -> None:
        self.hide_calls += 1
        self.visible = False


class FakeWindow:
    def __init__(self, *, visible: bool, focused: int = 4, split: int | None = None) -> None:
        self._focused_tile_id = focused
        self._split_tile_id = split
        self._split_pairs: dict[int, int] = {}
        self.focus_view = FakeFocusView(visible)
        self.returned_to_grid: list[int] = []
        self.sync_calls = 0
        self.refresh_calls = 0
        self.restore_calls = 0

    def _restore_saved_split_for_tile(self, _tile_id: int) -> bool:
        self.restore_calls += 1
        return False

    def _return_split_tile_to_grid(self, tile_id: int) -> None:
        self.returned_to_grid.append(tile_id)

    def _forget_split_pairs_for_tile(self, tile_id: int) -> None:
        MainWindow._forget_split_pairs_for_tile(self, tile_id)

    def _sync_focus_flags(self) -> None:
        self.sync_calls += 1

    def _refresh_top_state(self) -> None:
        self.refresh_calls += 1


class SplitToggleRegressionTest(unittest.TestCase):
    def test_second_click_closes_panel_and_forgets_all_pairs_for_main_tile(self) -> None:
        window = FakeWindow(visible=True, focused=4, split=7)
        window._split_pairs = {4: 7, 7: 4, 8: 4, 20: 21, 21: 20}

        MainWindow.toggle_split_panel_for_focused_tile(window, 4)

        self.assertEqual(window.returned_to_grid, [7])
        self.assertIsNone(window._split_tile_id)
        self.assertFalse(window.focus_view.visible)
        self.assertEqual(window.focus_view.show_calls, 0)
        self.assertEqual(window.focus_view.hide_calls, 1)
        self.assertEqual(window._split_pairs, {20: 21, 21: 20})
        self.assertEqual(window.sync_calls, 1)
        self.assertEqual(window.refresh_calls, 1)

    def test_first_click_opens_selector_when_no_saved_pair_exists(self) -> None:
        window = FakeWindow(visible=False, focused=4)

        MainWindow.toggle_split_panel_for_focused_tile(window, 4)

        self.assertTrue(window.focus_view.visible)
        self.assertEqual(window.focus_view.show_calls, 1)
        self.assertEqual(window.focus_view.hide_calls, 0)
        self.assertEqual(window.restore_calls, 1)
        self.assertEqual(window.sync_calls, 1)
        self.assertEqual(window.refresh_calls, 1)

    def test_click_from_non_focused_tile_is_ignored(self) -> None:
        window = FakeWindow(visible=True, focused=4, split=7)
        window._split_pairs = {4: 7, 7: 4}

        MainWindow.toggle_split_panel_for_focused_tile(window, 3)

        self.assertTrue(window.focus_view.visible)
        self.assertEqual(window._split_tile_id, 7)
        self.assertEqual(window._split_pairs, {4: 7, 7: 4})
        self.assertEqual(window.sync_calls, 0)
        self.assertEqual(window.refresh_calls, 0)


if __name__ == '__main__':
    unittest.main()

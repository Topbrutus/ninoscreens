from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.widgets.web_tile import WebTile  # noqa: E402
from app.windows.main_window import TILES_PER_PAGE, MainWindow  # noqa: E402


class _FakeView:
    def __init__(self) -> None:
        self.stop_count = 0
        self.delete_later_count = 0

    def stop(self) -> None:
        self.stop_count += 1

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _FakeProfile:
    def __init__(self) -> None:
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _LifecycleStates:
    Active = "Active"
    Frozen = "Frozen"
    Discarded = "Discarded"


class _ActiveOnlyLifecycleStates:
    Active = "Active"


class _LifecyclePage:
    LifecycleState = _LifecycleStates

    def __init__(self, *, raise_on_set: bool = False) -> None:
        self.popup_url_ready = _FakeSignal()
        self.fullScreenRequested = _FakeSignal()
        self.iconChanged = _FakeSignal()
        self.loadStarted = _FakeSignal()
        self.loadFinished = _FakeSignal()
        self.loadProgress = _FakeSignal()
        self.urlChanged = _FakeSignal()
        self.titleChanged = _FakeSignal()
        self.state = self.LifecycleState.Active
        self.raise_on_set = raise_on_set
        self.lifecycle_calls: list[str] = []
        self.javascript_calls: list[str] = []
        self.javascript_callbacks: list[object] = []
        self._profile = _FakeProfile()

    def setLifecycleState(self, state: str) -> None:
        if self.raise_on_set:
            raise RuntimeError("native lifecycle unavailable")
        self.lifecycle_calls.append(state)
        self.state = state

    def lifecycleState(self) -> str:
        return self.state

    def runJavaScript(self, script: str, callback=None) -> None:
        self.javascript_calls.append(script)
        if callback is not None:
            self.javascript_callbacks.append(callback)

    def profile(self) -> _FakeProfile:
        return self._profile

    def parent(self):
        return _FakeView()


class _ActiveOnlyLifecyclePage(_LifecyclePage):
    LifecycleState = _ActiveOnlyLifecycleStates


class _NoLifecyclePage:
    def __init__(self) -> None:
        self.popup_url_ready = _FakeSignal()
        self.fullScreenRequested = _FakeSignal()
        self.iconChanged = _FakeSignal()
        self.loadStarted = _FakeSignal()
        self.loadFinished = _FakeSignal()
        self.loadProgress = _FakeSignal()
        self.urlChanged = _FakeSignal()
        self.titleChanged = _FakeSignal()
        self.javascript_calls: list[str] = []
        self.javascript_callbacks: list[object] = []

    def runJavaScript(self, script: str, callback=None) -> None:
        self.javascript_calls.append(script)
        if callback is not None:
            self.javascript_callbacks.append(callback)

    def parent(self):
        return _FakeView()


class _FakeSignal:
    def disconnect(self, _slot) -> None:
        raise TypeError("not connected")


class _ClosablePage(_LifecyclePage):
    popup_url_ready = _FakeSignal()
    fullScreenRequested = _FakeSignal()
    iconChanged = _FakeSignal()
    loadStarted = _FakeSignal()
    loadFinished = _FakeSignal()
    loadProgress = _FakeSignal()
    urlChanged = _FakeSignal()
    titleChanged = _FakeSignal()

    def parent(self):
        return _FakeView()


class _TrackableTile(WebTile):
    def __init__(self) -> None:
        super().__init__(tile_id=0, profile=None)
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


def _tile_with_page(page) -> WebTile:
    tile = WebTile(tile_id=0, profile=None)
    tile._page = page
    tile._web_view = _FakeView()
    tile._state.has_content = True
    return tile


class _FakeStack:
    def __init__(self, current=None, index: int = 0) -> None:
        self._current = current
        self._index = index

    def currentWidget(self):
        return self._current

    def setCurrentWidget(self, widget) -> None:
        self._current = widget

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        self._index = index


class _FakeFocusView:
    def __init__(self, split_visible: bool = False) -> None:
        self._split_visible = split_visible

    def is_split_panel_visible(self) -> bool:
        return self._split_visible


class _FocusTile:
    def __init__(self, tile_id: int) -> None:
        self.tile_id = tile_id
        self.state = SimpleNamespace(is_focused=False)
        self.resume_count = 0
        self.suspend_count = 0

    def resume_background_activity(self) -> None:
        self.resume_count += 1

    def suspend_background_activity(self) -> None:
        self.suspend_count += 1


class WebTileSuspensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_runtime_detection_frozen_available(self) -> None:
        tile = _tile_with_page(_LifecyclePage())

        self.assertEqual(tile._webengine_lifecycle_capability("Active"), "Active")
        self.assertEqual(tile._webengine_lifecycle_capability("Frozen"), "Frozen")
        self.assertEqual(tile._webengine_lifecycle_capability("Discarded"), "Discarded")

    def test_runtime_detection_api_absent_uses_no_native_state(self) -> None:
        page = _NoLifecyclePage()
        tile = _tile_with_page(page)

        self.assertIsNone(tile._webengine_lifecycle_capability("Frozen"))

    def test_runtime_detection_method_present_but_frozen_absent(self) -> None:
        tile = _tile_with_page(_ActiveOnlyLifecyclePage())

        self.assertIsNone(tile._webengine_lifecycle_capability("Frozen"))

    def test_native_runtime_error_falls_back_to_javascript(self) -> None:
        page = _LifecyclePage(raise_on_set=True)
        tile = _tile_with_page(page)

        tile.suspend_background_activity()

        self.assertEqual(tile._background_activity_state, WebTile.ACTIVITY_SUSPENDED)
        self.assertEqual(tile._background_activity_strategy, "media-fallback")
        self.assertEqual(len(page.javascript_calls), 1)

    def test_native_suspend_resume_are_idempotent_and_never_discard(self) -> None:
        page = _LifecyclePage()
        tile = _tile_with_page(page)

        tile.suspend_background_activity()
        tile.suspend_background_activity()
        tile.resume_background_activity()
        tile.resume_background_activity()

        self.assertEqual(page.lifecycle_calls, ["Frozen", "Active"])
        self.assertNotIn("Discarded", page.lifecycle_calls)
        self.assertEqual(tile._background_activity_state, WebTile.ACTIVITY_ACTIVE)

    def test_visible_tile_resume_restores_active(self) -> None:
        page = _LifecyclePage()
        tile = _tile_with_page(page)
        tile.suspend_background_activity()

        tile.resume_background_activity()

        self.assertEqual(page.lifecycle_calls[-1], "Active")
        self.assertEqual(page.lifecycleState(), "Active")

    def test_fallback_script_pauses_only_active_media(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)

        tile.suspend_background_activity()

        script = page.javascript_calls[0]
        self.assertIn('querySelectorAll("audio, video")', script)
        self.assertIn("!media.paused && !media.ended", script)
        self.assertIn("media.pause()", script)

    def test_fallback_resume_only_targets_previously_active_media_and_handles_rejection(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)

        tile.suspend_background_activity()
        tile.resume_background_activity()

        script = page.javascript_calls[-1]
        self.assertIn("previouslyPlayingIds", script)
        self.assertIn("targetIds.has(mediaId)", script)
        self.assertIn("media.play()", script)
        self.assertIn("result.catch", script)

    def test_fallback_script_injected_once_per_generation(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)

        tile.suspend_background_activity()
        tile.suspend_background_activity()

        self.assertEqual(len(page.javascript_calls), 1)

    def test_late_callback_after_close_is_ignored(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)
        tile.suspend_background_activity()
        callback = page.javascript_callbacks[0]

        tile.close_tile()
        callback('{"ok": true}')

        self.assertIsNone(tile._last_suspension_result_generation)

    def test_late_callback_after_reset_is_ignored(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)
        tile.suspend_background_activity()
        callback = page.javascript_callbacks[0]

        tile.reset_to_empty()
        callback('{"ok": true}')

        self.assertIsNone(tile._last_suspension_result_generation)
        self.assertEqual(tile._background_activity_state, WebTile.ACTIVITY_ACTIVE)

    def test_late_callback_after_new_navigation_is_ignored(self) -> None:
        page = _ActiveOnlyLifecyclePage()
        tile = _tile_with_page(page)
        tile.suspend_background_activity()
        callback = page.javascript_callbacks[0]

        tile._invalidate_suspension_callbacks()
        callback('{"ok": true}')

        self.assertIsNone(tile._last_suspension_result_generation)

    def test_suspend_and_resume_after_close_are_noops(self) -> None:
        page = _ClosablePage()
        tile = _TrackableTile()
        tile._page = page
        tile._web_view = _FakeView()
        tile._state.has_content = True

        tile.close_tile()
        tile.suspend_background_activity()
        tile.resume_background_activity()

        self.assertEqual(tile.delete_later_count, 1)
        self.assertEqual(page.profile().delete_later_count, 0)
        self.assertEqual(page.lifecycle_calls, [])

    def _make_window_for_focus(self, *, current, page_index: int = 0, split_visible: bool = False):
        window = MainWindow.__new__(MainWindow)
        focus_view = _FakeFocusView(split_visible=split_visible)
        page_stack = _FakeStack(index=page_index)
        main_stack = _FakeStack(current=current)
        if current == "focus":
            main_stack.setCurrentWidget(focus_view)
        elif current == "pages":
            main_stack.setCurrentWidget(page_stack)
        window.focus_view = focus_view
        window.page_stack = page_stack
        window.main_stack = main_stack
        window.tiles = {tile_id: _FocusTile(tile_id) for tile_id in range(TILES_PER_PAGE + 2)}
        window.app_state = SimpleNamespace(
            tile_id_to_slot=list(range(TILES_PER_PAGE + 2)),
            slot_to_tile_id=list(range(TILES_PER_PAGE + 2)),
        )
        window._focused_tile_id = None
        window._split_tile_id = None
        return window

    def test_focus_active_tile_resumed_and_hidden_tiles_suspended(self) -> None:
        window = self._make_window_for_focus(current="focus")
        window._focused_tile_id = 1

        MainWindow._sync_tile_background_activity(window)

        self.assertEqual(window.tiles[1].resume_count, 1)
        self.assertEqual(window.tiles[0].suspend_count, 1)
        self.assertEqual(window.tiles[2].suspend_count, 1)

    def test_focus_visible_split_tile_is_resumed_as_secondary(self) -> None:
        window = self._make_window_for_focus(current="focus", split_visible=True)
        window._focused_tile_id = 1
        window._split_tile_id = 2

        MainWindow._sync_tile_background_activity(window)

        self.assertEqual(window.tiles[1].resume_count, 1)
        self.assertEqual(window.tiles[2].resume_count, 1)
        self.assertEqual(window.tiles[0].suspend_count, 1)

    def test_return_to_grid_resumes_only_visible_page_tiles(self) -> None:
        window = self._make_window_for_focus(current="pages", page_index=0)

        MainWindow._sync_tile_background_activity(window)

        self.assertEqual(window.tiles[0].resume_count, 1)
        self.assertEqual(window.tiles[TILES_PER_PAGE - 1].resume_count, 1)
        self.assertEqual(window.tiles[TILES_PER_PAGE].suspend_count, 1)

    def test_no_visible_tile_is_suspended(self) -> None:
        window = self._make_window_for_focus(current="pages", page_index=0)

        MainWindow._sync_tile_background_activity(window)

        visible_suspend_counts = [
            window.tiles[tile_id].suspend_count for tile_id in range(TILES_PER_PAGE)
        ]
        self.assertEqual(visible_suspend_counts, [0] * TILES_PER_PAGE)


if __name__ == "__main__":
    unittest.main()

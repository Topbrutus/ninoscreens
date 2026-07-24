from __future__ import annotations

import gc
import os
import unittest
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.widgets.dashboard_grid import DashboardGrid  # noqa: E402
from app.widgets.web_tile import WebTile  # noqa: E402


def _ci_requires_webengine_failure() -> bool:
    return os.environ.get("CI", "").lower() == "true" or (
        os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    )


def _handle_webengine_unavailable(test_case, message: str) -> None:
    if _ci_requires_webengine_failure():
        test_case.fail(message)
        return
    test_case.skipTest(message)


class _FakeSignal:
    def __init__(self) -> None:
        self._slots: list[object] = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot) -> None:
        if slot not in self._slots:
            raise TypeError("slot is not connected")
        self._slots.remove(slot)

    def has_slot(self, slot) -> bool:
        return slot in self._slots


class _FakeTimer:
    def __init__(self) -> None:
        self.stop_count = 0
        self.active = True

    def stop(self) -> None:
        self.stop_count += 1
        self.active = False


class _FakeProfile:
    def __init__(self) -> None:
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _FakePage:
    def __init__(self, parent, profile: _FakeProfile) -> None:
        self.popup_url_ready = _FakeSignal()
        self.fullScreenRequested = _FakeSignal()
        self.iconChanged = _FakeSignal()
        self.loadStarted = _FakeSignal()
        self.loadFinished = _FakeSignal()
        self.loadProgress = _FakeSignal()
        self.urlChanged = _FakeSignal()
        self.titleChanged = _FakeSignal()
        self.delete_later_count = 0
        self.javascript_call_count = 0
        self._parent = parent
        self._profile = profile

    def parent(self):
        return self._parent

    def profile(self) -> _FakeProfile:
        return self._profile

    def runJavaScript(self, _script: str, callback=None) -> None:
        self.javascript_call_count += 1
        if callback is not None:
            callback(None)

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _FakeView:
    def __init__(self) -> None:
        self.stop_count = 0
        self.delete_later_count = 0

    def stop(self) -> None:
        self.stop_count += 1

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _TrackableWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _TrackableTile(WebTile):
    def __init__(self, tile_id: int = 0, profile=None) -> None:
        super().__init__(tile_id=tile_id, profile=profile)
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class WebTileLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _install_fake_browser(self, tile: WebTile, *, page_parent: str = "view"):
        container = _TrackableWidget()
        tile.stack.addWidget(container)
        view = _FakeView()
        profile = _FakeProfile()
        parent = tile if page_parent == "tile" else view
        page = _FakePage(parent, profile)

        external_slot = object()
        for signal, slot in (
            (page.popup_url_ready, tile._load_qurl),
            (page.fullScreenRequested, tile._handle_page_fullscreen_request),
            (page.iconChanged, tile._on_icon_changed),
            (page.loadStarted, tile._on_load_started),
            (page.loadFinished, tile._on_load_finished),
            (page.loadProgress, tile._on_load_progress),
            (page.urlChanged, tile._on_url_changed),
            (page.titleChanged, tile._on_title_changed),
        ):
            signal.connect(slot)
            signal.connect(external_slot)

        tile._browser_container = container
        tile._web_view = view
        tile._page = page
        tile._state.has_content = True
        return container, view, page, profile, external_slot

    def test_close_tile_is_idempotent_and_stops_loading_once(self) -> None:
        tile = _TrackableTile()
        timers = [_FakeTimer(), _FakeTimer(), _FakeTimer(), _FakeTimer()]
        (
            tile._toolbar_feedback_timer,
            tile._browser_focus_timer,
            tile.thumbnail_timer,
            tile.media_poll_timer,
        ) = timers
        container, view, page, _profile, _external_slot = self._install_fake_browser(tile)

        tile.close_tile()
        tile.close_tile()

        self.assertTrue(tile._is_closing)
        self.assertEqual(view.stop_count, 1)
        self.assertEqual(view.delete_later_count, 1)
        self.assertEqual(container.delete_later_count, 1)
        self.assertEqual(page.delete_later_count, 0)
        self.assertEqual(tile.delete_later_count, 1)
        self.assertEqual([timer.stop_count for timer in timers], [1, 1, 1, 1])

    def test_close_tile_disconnects_only_tile_owned_page_signals(self) -> None:
        tile = _TrackableTile()
        _container, _view, page, _profile, external_slot = self._install_fake_browser(tile)

        tile.close_tile()

        self.assertFalse(page.urlChanged.has_slot(tile._on_url_changed))
        self.assertTrue(page.urlChanged.has_slot(external_slot))
        self.assertFalse(page.loadFinished.has_slot(tile._on_load_finished))
        self.assertTrue(page.loadFinished.has_slot(external_slot))

    def test_tile_parented_page_is_deleted_once(self) -> None:
        tile = _TrackableTile()
        _container, _view, page, _profile, _external_slot = self._install_fake_browser(
            tile, page_parent="tile"
        )

        tile.close_tile()
        tile.close_tile()

        self.assertEqual(page.delete_later_count, 1)

    def test_shared_profile_is_not_destroyed(self) -> None:
        tile = _TrackableTile()
        _container, _view, _page, profile, _external_slot = self._install_fake_browser(tile)

        tile.close_tile()

        self.assertEqual(profile.delete_later_count, 0)

    def test_dashboard_grid_removes_reference_and_closes_tile(self) -> None:
        grid = DashboardGrid()
        tile = _TrackableTile()

        grid.place_tile(tile, 0)
        self.assertNotEqual(grid.layout_.indexOf(tile), -1)

        grid.remove_tile(tile)

        self.assertEqual(grid.layout_.indexOf(tile), -1)
        self.assertIsNone(tile.parent())
        self.assertEqual(tile.delete_later_count, 1)

    def test_late_media_callback_does_not_reuse_closed_tile(self) -> None:
        tile = _TrackableTile()
        self._install_fake_browser(tile)

        tile.close_tile()
        tile._apply_polled_media_state('{"audioActive": true, "videoActive": true}')

        self.assertFalse(tile._media_audio_active)
        self.assertFalse(tile._media_video_active)

    def test_real_qtwebengine_20_open_close_cycles(self) -> None:
        refs: list[weakref.ReferenceType[WebTile]] = []

        try:
            for tile_id in range(20):
                tile = WebTile(tile_id=tile_id, profile=None)
                tile._ensure_browser_page()
                self.assertIsNotNone(tile._page)
                refs.append(weakref.ref(tile))
                tile.close_tile()
                tile = None
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                gc.collect()
        except Exception as exc:
            _handle_webengine_unavailable(
                self,
                f"QtWebEngine real lifecycle unavailable: {type(exc).__name__}",
            )

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        gc.collect()
        self.assertTrue(all(ref() is None for ref in refs))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import time
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QShowEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.state import TileVisualStatus  # noqa: E402
from app.widgets.pages_bridge_workspace import PagesBridgeWorkspace, _BridgeRefreshTask  # noqa: E402


def _make_snapshot() -> dict[str, object]:
    return {
        "workers_active": 2,
        "nino_active": True,
        "core": {
            "status": "READY",
            "jules": {"status": "READY", "pid": 1234},
            "bridge": {"status": "READY", "pid": 4321},
        },
        "jobs": [{"job_id": "JOB-001"}],
        "d_only": {"last_refusal": "aucun"},
    }


class _FakeTile:
    def __init__(self, tile_id: int) -> None:
        self.tile_id = tile_id
        self.state = SimpleNamespace(
            display_title=f"Tile {tile_id + 1}",
            current_url="",
            status=TileVisualStatus.EMPTY,
            is_loading=False,
            has_content=False,
        )


class _FakeController:
    def __init__(self, snapshot: dict[str, object] | None = None, *, exc: Exception | None = None) -> None:
        self._snapshot = deepcopy(snapshot or _make_snapshot())
        self._exc = exc
        self.snapshot_calls = 0

    def snapshot(self) -> dict[str, object]:
        self.snapshot_calls += 1
        if self._exc is not None:
            raise self._exc
        return deepcopy(self._snapshot)


class PagesBridgeWorkspaceRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _build_workspace(self, controller: _FakeController | None = None) -> tuple[PagesBridgeWorkspace, _FakeController]:
        controller = controller or _FakeController()
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(4)}
        app_state = SimpleNamespace(bridge_target_tile_id=None)
        workspace = PagesBridgeWorkspace(tiles, app_state, controller)
        return workspace, controller

    def test_constructing_workspace_does_not_collect(self) -> None:
        workspace, controller = self._build_workspace()
        self.assertEqual(controller.snapshot_calls, 0)
        self.assertFalse(workspace._refresh_in_progress)
        self.assertFalse(workspace._refresh_requested)
        self.assertIsNone(workspace._cached_snapshot)

    def test_refresh_from_cache_is_ui_only_and_fast(self) -> None:
        workspace, controller = self._build_workspace()
        workspace._cached_snapshot = _make_snapshot()
        workspace._cached_snapshot_at = time.monotonic()

        with patch.object(controller, "snapshot", wraps=controller.snapshot) as snapshot_mock:
            start = time.perf_counter()
            workspace.refresh_from_cache()
            elapsed = time.perf_counter() - start

        snapshot_mock.assert_not_called()
        self.assertLess(elapsed, 0.05)

    def test_refresh_view_remains_cache_only(self) -> None:
        workspace, controller = self._build_workspace()
        with patch.object(workspace, "request_refresh") as request_mock:
            workspace.refresh_view()

        request_mock.assert_not_called()
        self.assertEqual(controller.snapshot_calls, 0)

    def test_request_refresh_view_keeps_manual_refresh_and_coalesces(self) -> None:
        workspace, _controller = self._build_workspace()
        with patch.object(workspace, "refresh_from_cache") as cache_mock, patch.object(
            workspace, "request_refresh", return_value=True
        ) as request_mock:
            workspace.request_refresh_view()

        cache_mock.assert_called_once()
        request_mock.assert_called_once_with(force=True)

    def test_ten_refresh_requests_launch_one_collection(self) -> None:
        workspace, controller = self._build_workspace()
        with patch.object(workspace._refresh_debounce_timer, "start") as debounce_mock, patch.object(
            workspace._bridge_refresh_pool, "start"
        ) as pool_mock:
            self.assertTrue(workspace.request_refresh(force=True))
            workspace._start_refresh_collection()
            for _ in range(9):
                self.assertFalse(workspace.request_refresh(force=True))

        debounce_mock.assert_called()
        pool_mock.assert_called_once()
        self.assertTrue(workspace._refresh_in_progress)
        self.assertEqual(controller.snapshot_calls, 0)

    def test_stale_collection_result_is_ignored(self) -> None:
        workspace, _controller = self._build_workspace()
        cached_snapshot = _make_snapshot()
        workspace._cached_snapshot = deepcopy(cached_snapshot)
        workspace._cached_snapshot_at = time.monotonic()
        workspace._refresh_generation = 5
        workspace._active_generation = 4
        workspace._refresh_in_progress = True
        workspace._refresh_requested = True

        with patch.object(workspace._refresh_debounce_timer, "start") as debounce_mock:
            workspace._on_refresh_snapshot_ready(4, {"core": {"status": "BROKEN"}})

        self.assertEqual(workspace._cached_snapshot, cached_snapshot)
        self.assertFalse(workspace._refresh_in_progress)
        debounce_mock.assert_called_once()

    def test_snapshot_exception_keeps_ui_usable(self) -> None:
        workspace, _controller = self._build_workspace(_FakeController(exc=RuntimeError("boom")))
        task_signals = SimpleNamespace(
            snapshot_ready=SimpleNamespace(emit=MagicMock()),
            snapshot_failed=SimpleNamespace(emit=MagicMock()),
        )
        task = _BridgeRefreshTask(workspace.arena_controller, 1, task_signals)
        task.run()

        task_signals.snapshot_failed.emit.assert_called_once_with(1, "boom")

        workspace._refresh_generation = 1
        workspace._active_generation = 1
        workspace._refresh_in_progress = True
        workspace._refresh_requested = False
        workspace._on_refresh_snapshot_failed(1, "boom")
        workspace.refresh_from_cache()

        self.assertIn(workspace.state_badge.text(), {"ERROR", "DEGRADED"})
        self.assertEqual(workspace.subtitle_label.text(), "Bridge indisponible: boom")

    def test_hidden_workspace_waits_until_shown(self) -> None:
        workspace, controller = self._build_workspace()
        with patch.object(workspace, "request_refresh") as request_mock:
            workspace.showEvent(QShowEvent())

        request_mock.assert_called_once_with(force=False)
        self.assertEqual(controller.snapshot_calls, 0)

    def test_activate_requests_deferred_collection(self) -> None:
        workspace, controller = self._build_workspace()
        with patch.object(workspace, "request_refresh", return_value=True) as request_mock:
            workspace.activate()

        request_mock.assert_called_once_with(force=False)
        self.assertEqual(controller.snapshot_calls, 0)


if __name__ == "__main__":
    unittest.main()

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
from app.widgets.pages_bridge_workspace import (  # noqa: E402
    PagesBridgeWorkspace,
    _BridgeRefreshTask,
)


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
    def __init__(
        self,
        tile_id: int,
        *,
        title: str | None = None,
        current_url: str = "",
        status: TileVisualStatus = TileVisualStatus.EMPTY,
        is_loading: bool = False,
        has_content: bool = False,
        ) -> None:
        self.tile_id = tile_id
        self.opened_urls: list[str] = []
        self.state = SimpleNamespace(
            display_title=title or f"Tile {tile_id + 1}",
            current_url=current_url,
            status=status,
            is_loading=is_loading,
            has_content=has_content,
        )

    def open_url_text(self, raw_text: str) -> None:
        self.opened_urls.append(raw_text)


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

    def _set_chatgpt_tile(self, workspace: PagesBridgeWorkspace, tile_id: int, url: str = "https://chatgpt.com/") -> None:
        tile = workspace.tiles[tile_id]
        tile.state.display_title = "ChatGPT"
        tile.state.current_url = url
        tile.state.status = TileVisualStatus.READY
        tile.state.is_loading = False
        tile.state.has_content = True

    def _set_loaded_tile(self, workspace: PagesBridgeWorkspace, tile_id: int, url: str) -> None:
        tile = workspace.tiles[tile_id]
        tile.state.display_title = "ChatGPT"
        tile.state.current_url = url
        tile.state.status = TileVisualStatus.READY
        tile.state.is_loading = False
        tile.state.has_content = True

    def _assert_action_buttons(
        self,
        workspace: PagesBridgeWorkspace,
        *,
        test_enabled: bool,
        prepare_enabled: bool,
        send_enabled: bool,
    ) -> None:
        self.assertEqual(workspace.test_target_button.isEnabled(), test_enabled)
        self.assertEqual(workspace.prepare_button.isEnabled(), prepare_enabled)
        self.assertEqual(workspace.send_button.isEnabled(), send_enabled)

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

    def test_persisted_target_zero_restores_visible_target(self) -> None:
        controller = _FakeController()
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(4)}
        app_state = SimpleNamespace(bridge_target_tile_id=0)
        tile = tiles[0]
        tile.state.display_title = "ChatGPT"
        tile.state.current_url = "https://chatgpt.com/"
        tile.state.status = TileVisualStatus.READY
        tile.state.has_content = True
        workspace = PagesBridgeWorkspace(tiles, app_state, controller)

        self.assertEqual(workspace.selected_target_value.text(), "Tile 1 • ChatGPT")
        self.assertEqual(workspace.app_state.bridge_target_tile_id, 0)
        self.assertIn(workspace.state_badge.text(), {"IDLE", "READY"})
        self._assert_action_buttons(
            workspace,
            test_enabled=True,
            prepare_enabled=True,
            send_enabled=True,
        )
        self.assertEqual(workspace.target_edit.text(), "1")
        self.assertEqual(workspace.current_tile_value.text(), "Tile 1 • ChatGPT")
        self.assertEqual(workspace.current_index_value.text(), "1")
        self.assertEqual(workspace.current_url_value.text(), "https://chatgpt.com/")

    def test_no_explicit_target_with_multiple_candidates_is_ambiguous(self) -> None:
        controller = _FakeController()
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(4)}
        app_state = SimpleNamespace(bridge_target_tile_id=None)
        for tile_id in (0, 1):
            tiles[tile_id].state.display_title = "ChatGPT"
            tiles[tile_id].state.current_url = "https://chatgpt.com/"
            tiles[tile_id].state.status = TileVisualStatus.READY
            tiles[tile_id].state.is_loading = False
            tiles[tile_id].state.has_content = True
        workspace = PagesBridgeWorkspace(tiles, app_state, controller)

        self.assertEqual(workspace.selected_target_value.text(), "AMBIGU")
        self.assertEqual(workspace.app_state.bridge_target_tile_id, None)
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_explicit_invalid_target_stays_selected_and_invalid(self) -> None:
        controller = _FakeController()
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(4)}
        app_state = SimpleNamespace(bridge_target_tile_id=0)
        tiles[0].state.display_title = "ChatGPT"
        tiles[0].state.current_url = "https://example.com/"
        tiles[0].state.status = TileVisualStatus.READY
        tiles[0].state.is_loading = False
        tiles[0].state.has_content = True
        workspace = PagesBridgeWorkspace(tiles, app_state, controller)

        self.assertEqual(workspace.selected_target_value.text(), "Tile 1 • INVALIDE")
        self.assertEqual(workspace.app_state.bridge_target_tile_id, 0)
        self.assertEqual(workspace.state_badge.text(), "ERROR")
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_empty_target_disables_all_actions(self) -> None:
        workspace, _controller = self._build_workspace()

        self.assertEqual(workspace.selected_target_value.text(), "Aucune cible explicite")
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_editable_target_updates_persisted_selection(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_chatgpt_tile(workspace, 2)

        workspace.target_edit.setText("3")
        workspace.apply_target_from_editor()

        self.assertEqual(workspace.app_state.bridge_target_tile_id, 2)
        self.assertEqual(workspace.selected_target_value.text(), "Tile 3 • ChatGPT")
        self.assertEqual(workspace.current_tile_value.text(), "Tile 3 • ChatGPT")

    def test_lock_and_emergency_unlock_gate_actions(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_chatgpt_tile(workspace, 0)
        workspace.app_state.bridge_target_tile_id = 0
        workspace.sync_target_from_state()

        workspace.toggle_lock()

        self.assertTrue(workspace._bridge_locked)
        self.assertFalse(workspace.test_target_button.isEnabled())
        self.assertFalse(workspace.send_button.isEnabled())
        self.assertTrue(workspace.emergency_unlock_button.isEnabled())

        workspace.emergency_unlock()

        self.assertFalse(workspace._bridge_locked)
        self.assertTrue(workspace.test_target_button.isEnabled())
        self.assertTrue(workspace.send_button.isEnabled())
        self.assertFalse(workspace.emergency_unlock_button.isEnabled())

    def test_new_conversation_opens_chatgpt_root_on_selected_tile(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_chatgpt_tile(workspace, 1)
        workspace.app_state.bridge_target_tile_id = 1
        workspace.sync_target_from_state()

        workspace.open_new_conversation()

        self.assertEqual(workspace.tiles[1].opened_urls, ["https://chatgpt.com/"])

    def test_missing_tile_disables_all_actions(self) -> None:
        controller = _FakeController()
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(4)}
        app_state = SimpleNamespace(bridge_target_tile_id=99)
        workspace = PagesBridgeWorkspace(tiles, app_state, controller)

        self.assertEqual(workspace.selected_target_value.text(), "Tile 100 • INVALIDE")
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_wrong_origin_disables_all_actions(self) -> None:
        controller = _FakeController()
        workspace, _ = self._build_workspace(controller)
        self._set_loaded_tile(workspace, 0, "https://example.com/")
        workspace.app_state.bridge_target_tile_id = 0
        workspace.sync_target_from_state()

        self.assertEqual(workspace.selected_target_value.text(), "Tile 1 • INVALIDE")
        self.assertEqual(workspace.state_badge.text(), "ERROR")
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_valid_refresh_stores_last_valid_snapshot(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_chatgpt_tile(workspace, 0)
        workspace.app_state.bridge_target_tile_id = 0
        workspace.sync_target_from_state()
        snapshot = _make_snapshot()
        workspace._refresh_generation = 1
        workspace._active_generation = 1
        workspace._refresh_in_progress = True
        workspace._refresh_requested = False

        workspace._on_refresh_snapshot_ready(1, snapshot)

        self.assertEqual(workspace._cached_snapshot, snapshot)
        self.assertEqual(workspace._last_valid_snapshot, snapshot)
        self.assertEqual(workspace.state_badge.text(), "READY")
        self._assert_action_buttons(
            workspace,
            test_enabled=True,
            prepare_enabled=True,
            send_enabled=True,
        )

    def test_invalid_refresh_preserves_last_valid_snapshot(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_chatgpt_tile(workspace, 0)
        workspace.app_state.bridge_target_tile_id = 0
        workspace.sync_target_from_state()
        valid_snapshot = _make_snapshot()
        workspace._set_last_valid_snapshot(valid_snapshot)
        workspace._refresh_generation = 2
        workspace._active_generation = 2
        workspace._refresh_in_progress = True
        workspace._refresh_requested = False

        self._set_loaded_tile(workspace, 0, "https://example.com/")
        invalid_snapshot = _make_snapshot()
        invalid_snapshot["workers_active"] = 1

        workspace._on_refresh_snapshot_ready(2, invalid_snapshot)

        self.assertEqual(workspace._cached_snapshot, valid_snapshot)
        self.assertEqual(workspace._last_valid_snapshot, valid_snapshot)
        self.assertEqual(workspace.state_badge.text(), "DEGRADED")
        self.assertIn("example.com", workspace.last_block_value.text())
        self._assert_action_buttons(
            workspace,
            test_enabled=False,
            prepare_enabled=False,
            send_enabled=False,
        )

    def test_recovery_to_chatgpt_returns_ready_and_updates_cache(self) -> None:
        workspace, _controller = self._build_workspace()
        self._set_loaded_tile(workspace, 0, "https://example.com/")
        workspace.app_state.bridge_target_tile_id = 0
        workspace.sync_target_from_state()
        invalid_snapshot = _make_snapshot()
        workspace._set_last_valid_snapshot(_make_snapshot())
        workspace._refresh_generation = 2
        workspace._active_generation = 2
        workspace._refresh_in_progress = True
        workspace._refresh_requested = False
        workspace._on_refresh_snapshot_ready(2, invalid_snapshot)

        self._set_chatgpt_tile(workspace, 0)
        workspace.sync_target_from_state()
        ready_snapshot = _make_snapshot()
        ready_snapshot["workers_active"] = 3
        workspace._refresh_generation = 3
        workspace._active_generation = 3
        workspace._refresh_in_progress = True
        workspace._refresh_requested = False
        workspace._on_refresh_snapshot_ready(3, ready_snapshot)

        self.assertEqual(workspace._cached_snapshot, ready_snapshot)
        self.assertEqual(workspace._last_valid_snapshot, ready_snapshot)
        self.assertEqual(workspace.state_badge.text(), "READY")
        self.assertEqual(workspace.selected_target_value.text(), "Tile 1 • ChatGPT")
        self._assert_action_buttons(
            workspace,
            test_enabled=True,
            prepare_enabled=True,
            send_enabled=True,
        )


if __name__ == "__main__":
    unittest.main()

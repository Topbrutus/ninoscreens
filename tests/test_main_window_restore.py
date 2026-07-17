from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.config import TILE_COUNT  # noqa: E402
from app.windows.main_window import MainWindow  # noqa: E402


class _FakeStyle:
    def unpolish(self, *_args) -> None:
        return None

    def polish(self, *_args) -> None:
        return None


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.properties: dict[str, object] = {}
        self.tooltip = ""
        self.enabled = True
        self._style = _FakeStyle()

    def setText(self, text: str) -> None:
        self.text = text

    def setProperty(self, key: str, value: object) -> None:
        self.properties[key] = value

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def style(self) -> _FakeStyle:
        return self._style

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _FakePageMatrix:
    def __init__(self) -> None:
        self.split_pairs = None
        self.slot_states = None
        self.active_slot = None

    def set_split_pairs(self, split_pairs, slot_states) -> None:
        self.split_pairs = split_pairs
        self.slot_states = slot_states

    def refresh_all_slots(self, slot_states) -> None:
        self.slot_states = slot_states

    def set_active_slot(self, slot, run_active=False) -> None:
        self.active_slot = (slot, run_active)


class _FakeController:
    def __init__(self, snapshot: dict[str, object] | None = None) -> None:
        self._snapshot = snapshot
        self.request_calls = 0
        self.start_calls = 0
        self.in_progress = False
        self.snapshot_calls = 0

    def snapshot(self) -> dict[str, object]:
        self.snapshot_calls += 1
        raise AssertionError("snapshot() must not be called from UI refresh paths")

    def cached_snapshot(self) -> dict[str, object] | None:
        return self._snapshot

    def request_snapshot_refresh(self, *, force: bool = False) -> bool:
        self.request_calls += 1
        if self.in_progress:
            return False
        self.in_progress = True
        self.start_calls += 1
        return True

    def snapshot_refresh_in_progress(self) -> bool:
        return self.in_progress


class _FakeTile:
    def __init__(self, tile_id: int) -> None:
        self.tile_id = tile_id
        self.restore_calls: list[tuple[str, float]] = []

    def restore_from_session(self, current_url: str, zoom_factor: float) -> None:
        self.restore_calls.append((current_url, zoom_factor))


class MainWindowRestoreTests(unittest.TestCase):
    def _build_restore_fake(self, controller: _FakeController) -> SimpleNamespace:
        tiles = {tile_id: _FakeTile(tile_id) for tile_id in range(TILE_COUNT)}
        app_state = SimpleNamespace(
            tiles=[SimpleNamespace(has_content=False, is_loading=False, memory_mb=0) for _ in range(TILE_COUNT)],
            last_selected_tile_id=0,
            current_page_index=0,
            active_view="tiles",
            bridge_target_tile_id=None,
            is_fullscreen=False,
            focused_tile_id=None,
            split_panel_visible=False,
            window_size=None,
        )
        return SimpleNamespace(
            _restoring_session=True,
            tiles=tiles,
            app_state=app_state,
            arena_controller=controller,
            page_matrix=_FakePageMatrix(),
            focus_view=SimpleNamespace(refresh_slots=lambda *args, **kwargs: None, is_split_panel_visible=lambda: False),
            fullscreen_button=_FakeButton(),
            main_stack=SimpleNamespace(currentWidget=lambda: None),
            page_stack=SimpleNamespace(setCurrentIndex=lambda *_args, **_kwargs: None),
            _tile_positions_from_payload=lambda _payload: list(range(TILE_COUNT)),
            _apply_slot_order=lambda *_args, **_kwargs: None,
            _rebuild_tile_layout=lambda: None,
            _sync_focus_flags=lambda: None,
            _refresh_top_state=lambda: None,
            _show_active_workspace=lambda: None,
            _tile_page_index=lambda tile_id: 0 if tile_id >= 0 else 0,
            show_tile_page=lambda *_args, **_kwargs: None,
            show_run_page=lambda: None,
            show_pages_bridge_page=lambda: None,
            show_arena_page=lambda: None,
            enter_focus_mode=lambda *_args, **_kwargs: None,
            showNormal=lambda: None,
            showFullScreen=lambda: None,
        )

    def test_restore_session_with_36_empty_tiles_defers_arena_refresh(self) -> None:
        payload = {
            "tiles": [
                {"tile_id": tile_id, "current_url": "", "zoom_factor": 1.0}
                for tile_id in range(TILE_COUNT)
            ],
            "last_selected_tile_id": 0,
            "current_page_index": 0,
            "active_view": "tiles",
            "focused_tile_id": None,
            "split_panel_visible": False,
            "is_fullscreen": False,
        }
        controller = _FakeController()
        fake_window = self._build_restore_fake(controller)

        with patch("app.windows.main_window.load_session_payload", return_value=payload):
            MainWindow._restore_session(fake_window)

        self.assertFalse(fake_window._restoring_session)
        self.assertEqual(controller.request_calls, 1)
        self.assertEqual(controller.start_calls, 1)
        self.assertEqual(controller.in_progress, True)
        self.assertEqual(controller.snapshot_calls, 0)
        self.assertTrue(all(tile.restore_calls == [("", 1.0)] for tile in fake_window.tiles.values()))

    def test_refresh_top_state_reuses_async_arena_collection(self) -> None:
        snapshot = None
        controller = _FakeController(snapshot=snapshot)
        fake_window = SimpleNamespace(
            app_state=SimpleNamespace(
                tiles=[SimpleNamespace(has_content=False, is_loading=False, memory_mb=0) for _ in range(TILE_COUNT)],
                active_view="tiles",
                current_page_index=0,
            ),
            arena_controller=controller,
            page_matrix=_FakePageMatrix(),
            arena_button=_FakeButton(),
            pages_button=_FakeButton(),
            focus_exit_button=_FakeButton(),
            mode_label=_FakeButton(),
            summary_label=_FakeButton(),
            _grid_interchange_source_tile_id=None,
            _focused_tile_id=None,
            _split_tile_id=None,
            _last_selected_tile_id=0,
            main_stack=SimpleNamespace(currentWidget=lambda: None),
            arena_workspace=SimpleNamespace(),
            focus_view=SimpleNamespace(is_split_panel_visible=lambda: False),
            _slot_states=lambda: [],
            _slot_split_pairs=lambda: {},
            _current_matrix_slot=lambda: None,
            _restoring_session=False,
        )

        MainWindow._refresh_top_state(fake_window)
        MainWindow._refresh_top_state(fake_window)

        self.assertEqual(controller.request_calls, 2)
        self.assertEqual(controller.start_calls, 1)
        self.assertEqual(controller.snapshot_calls, 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.state import TileVisualStatus  # noqa: E402
from app.widgets.web_tile import WebTile  # noqa: E402


class WebTileRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_restore_from_session_empty_tile_is_noop(self) -> None:
        tile = WebTile(tile_id=0, profile=None)

        with patch.object(tile, "reset_to_empty") as reset_mock, patch.object(tile, "_emit_state") as emit_mock, patch.object(
            tile, "_ensure_browser_page"
        ) as ensure_mock:
            tile.restore_from_session("", 1.0)

        reset_mock.assert_not_called()
        emit_mock.assert_not_called()
        ensure_mock.assert_not_called()
        self.assertIsNone(tile._browser_container)
        self.assertIs(tile.stack.currentWidget(), tile.empty_page)

    def test_reset_to_empty_on_already_empty_tile_is_noop(self) -> None:
        tile = WebTile(tile_id=1, profile=None)

        with patch.object(tile, "_emit_state") as emit_mock, patch.object(tile, "queue_thumbnail_capture") as queue_mock:
            tile.reset_to_empty()

        emit_mock.assert_not_called()
        queue_mock.assert_not_called()
        self.assertIsNone(tile._browser_container)
        self.assertIs(tile.stack.currentWidget(), tile.empty_page)

    def test_reset_to_empty_from_loaded_tile_emits_state_change(self) -> None:
        tile = WebTile(tile_id=2, profile=None)
        browser_container = QWidget()
        tile._browser_container = browser_container
        tile.stack.addWidget(browser_container)
        tile._state.current_url = "https://example.com"
        tile._state.title = "Example"
        tile._state.domain = "example.com"
        tile._state.has_content = True
        tile._state.status = TileVisualStatus.READY

        with patch.object(tile, "_stop_media_capture") as stop_capture_mock, patch.object(
            tile, "_stop_media_probe"
        ) as stop_probe_mock, patch.object(tile, "clear_media_message") as clear_media_mock, patch.object(
            tile, "queue_thumbnail_capture"
        ) as queue_mock, patch.object(
            tile, "_emit_state"
        ) as emit_mock:
            tile.reset_to_empty()

        stop_capture_mock.assert_called_once()
        stop_probe_mock.assert_called_once()
        clear_media_mock.assert_called_once()
        queue_mock.assert_called_once()
        emit_mock.assert_called_once()
        self.assertEqual(tile._state.current_url, "")
        self.assertEqual(tile._state.title, "")
        self.assertEqual(tile._state.domain, "")
        self.assertFalse(tile._state.has_content)
        self.assertFalse(tile._state.is_loading)
        self.assertEqual(tile._state.status, TileVisualStatus.EMPTY)
        self.assertIsNone(tile._browser_container)
        self.assertIs(tile.stack.currentWidget(), tile.empty_page)


if __name__ == "__main__":
    unittest.main()

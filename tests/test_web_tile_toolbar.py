from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QWidget  # noqa: E402

from app.widgets.web_tile import WebTile  # noqa: E402


class _FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _FakeBrowserView:
    def __init__(self) -> None:
        self.focused = False
        self.activated = False

    def setFocus(self, _reason) -> None:
        self.focused = True

    def activateWindow(self) -> None:
        self.activated = True


class _FakeVisibleBrowserView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.focused = False
        self.activated = False

    def setFocus(self, _reason) -> None:
        self.focused = True

    def activateWindow(self) -> None:
        self.activated = True


class WebTileToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_google_shortcut_uses_exact_url_and_requests_focus(self) -> None:
        tile = WebTile(tile_id=0, profile=None)

        with patch.object(tile, "_navigate_from_text", return_value=True) as navigate_mock, patch.object(
            tile, "request_browser_focus"
        ) as focus_mock:
            tile.load_google_page()

        navigate_mock.assert_called_once_with("https://www.google.com/")
        focus_mock.assert_called_once()

    def test_direct_load_requests_focus_once(self) -> None:
        tile = WebTile(tile_id=4, profile=None)
        tile._ensure_browser_page()
        tile.browser_url_edit.setText("https://example.org")

        with patch.object(tile, "_navigate_from_text", return_value=True) as navigate_mock, patch.object(
            tile, "request_browser_focus"
        ) as focus_mock:
            tile.load_from_browser_input()

        navigate_mock.assert_called_once_with(tile.browser_url_edit.text())
        focus_mock.assert_called_once()

    def test_empty_page_load_requests_focus_once(self) -> None:
        tile = WebTile(tile_id=5, profile=None)
        tile.empty_url_edit.setText("https://example.com")

        with patch.object(tile, "_navigate_from_text", return_value=True) as navigate_mock, patch.object(
            tile, "request_browser_focus"
        ) as focus_mock:
            tile.load_from_empty_input()

        navigate_mock.assert_called_once_with("https://example.com")
        focus_mock.assert_called_once()

    def test_copy_displayed_url_copies_the_visible_address(self) -> None:
        tile = WebTile(tile_id=1, profile=None)
        tile._browser_container = QWidget()
        tile.stack.addWidget(tile._browser_container)
        tile.browser_url_edit = QLineEdit()
        tile.browser_url_edit.setText("https://example.com/path?a=1")
        fake_clipboard = _FakeClipboard()

        with patch("app.widgets.web_tile.QApplication.clipboard", return_value=fake_clipboard), patch.object(
            tile, "_show_toolbar_feedback"
        ) as feedback_mock:
            tile.copy_displayed_url()

        self.assertEqual(fake_clipboard.text, "https://example.com/path?a=1")
        feedback_mock.assert_called_once_with("URL copiée")

    def test_request_browser_focus_runs_on_next_qt_turn(self) -> None:
        tile = WebTile(tile_id=2, profile=None)
        tile._ensure_browser_page()
        tile.stack.setCurrentWidget(tile._browser_container)
        tile._web_view = _FakeVisibleBrowserView(tile._browser_container)
        tile._web_view.show()
        tile.show()

        with patch.object(tile._browser_focus_timer, "start") as start_mock:
            tile.request_browser_focus()

        start_mock.assert_called_once_with(0)
        tile._browser_focus_timer.timeout.emit()
        self.assertTrue(tile._web_view.focused)
        self.assertTrue(tile._web_view.activated)

    def test_request_browser_focus_can_be_called_repeatedly(self) -> None:
        tile = WebTile(tile_id=3, profile=None)
        tile._ensure_browser_page()
        tile.stack.setCurrentWidget(tile._browser_container)
        tile._web_view = _FakeVisibleBrowserView(tile._browser_container)
        tile._web_view.show()
        tile.show()

        with patch.object(tile._browser_focus_timer, "start") as start_mock:
            tile.request_browser_focus()
            tile.request_browser_focus()

        self.assertEqual(start_mock.call_count, 2)
        tile._browser_focus_timer.timeout.emit()
        self.assertTrue(tile._web_view.focused)
        self.assertTrue(tile._web_view.activated)

    def test_load_finished_does_not_steal_focus(self) -> None:
        tile = WebTile(tile_id=6, profile=None)
        tile._ensure_browser_page()
        tile.stack.setCurrentWidget(tile._browser_container)
        tile.show()
        keeper = QLineEdit()
        keeper.show()
        keeper.setFocus()
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), keeper)

        with patch.object(tile, "request_browser_focus") as focus_mock:
            tile._on_load_finished(True)

        focus_mock.assert_not_called()
        self.assertIs(QApplication.focusWidget(), keeper)


if __name__ == "__main__":
    unittest.main()

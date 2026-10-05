from __future__ import annotations

import inspect
import unittest

from app.windows.main_window import MainWindow


class FakeTimer:
    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1


class FakeWindow:
    def __init__(self) -> None:
        self._session_save_timer = FakeTimer()


class SessionAutosaveRegressionTest(unittest.TestCase):
    def test_schedule_session_save_restarts_debounce_timer(self) -> None:
        window = FakeWindow()

        MainWindow._schedule_session_save(window)
        MainWindow._schedule_session_save(window)

        self.assertEqual(window._session_save_timer.start_calls, 2)

    def test_top_state_refresh_schedules_persistence(self) -> None:
        source = inspect.getsource(MainWindow._refresh_top_state)
        self.assertIn("self._schedule_session_save()", source)

    def test_resize_and_fullscreen_schedule_persistence(self) -> None:
        self.assertIn("self._schedule_session_save()", inspect.getsource(MainWindow.resizeEvent))
        self.assertIn("self._schedule_session_save()", inspect.getsource(MainWindow.toggle_global_fullscreen))


if __name__ == "__main__":
    unittest.main()

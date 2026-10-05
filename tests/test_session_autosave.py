from __future__ import annotations

import ast
from pathlib import Path
import unittest


SOURCE_PATH = Path(__file__).resolve().parents[1] / "app" / "windows" / "main_window.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def method_source(name: str) -> str:
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"method not found: {name}")


class SessionAutosaveRegressionTest(unittest.TestCase):
    def test_debounce_constant_is_wired_into_main_window(self) -> None:
        self.assertIn("SESSION_SAVE_DEBOUNCE_MS", SOURCE)
        self.assertIn("setInterval(SESSION_SAVE_DEBOUNCE_MS)", SOURCE)

    def test_schedule_method_restarts_timer(self) -> None:
        source = method_source("_schedule_session_save")
        self.assertIn("self._session_save_timer.start()", source)

    def test_top_state_refresh_schedules_persistence(self) -> None:
        self.assertIn("self._schedule_session_save()", method_source("_refresh_top_state"))

    def test_resize_and_fullscreen_schedule_persistence(self) -> None:
        self.assertIn("self._schedule_session_save()", method_source("resizeEvent"))
        self.assertIn("self._schedule_session_save()", method_source("toggle_global_fullscreen"))


if __name__ == "__main__":
    unittest.main()

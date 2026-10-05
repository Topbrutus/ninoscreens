from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "app" / "terminal" / "runtime.py").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "app" / "widgets" / "terminal_workspace.py").read_text(encoding="utf-8")
NATIVE = (ROOT / "app" / "widgets" / "native_terminal_view.py").read_text(encoding="utf-8")


class NativeTerminalFrontendTest(unittest.TestCase):
    def test_runtime_exposes_direct_terminal_io(self) -> None:
        self.assertIn("def session_buffer(self, session_id: str) -> str:", RUNTIME)
        self.assertIn("def send_input(self, session_id: str, data: str) -> bool:", RUNTIME)
        self.assertIn("def send_interrupt(self, session_id: str) -> bool:", RUNTIME)
        self.assertIn("def resize_session(self, session_id: str, rows: int, cols: int) -> bool:", RUNTIME)

    def test_workspace_defaults_to_native_frontend_on_non_windows(self) -> None:
        self.assertIn('frontend != "native" and os.name == "nt"', WORKSPACE)
        self.assertIn("NativeTerminalView", WORKSPACE)
        self.assertIn("self._native_poll_timer", WORKSPACE)

    def test_native_view_keeps_terminal_controls(self) -> None:
        self.assertIn('Qt.Key.Key_Up: "\\x1b[A"', NATIVE)
        self.assertIn('Qt.Key.Key_Backspace: "\\x7f"', NATIVE)
        self.assertIn("self.interrupt_requested.emit()", NATIVE)
        self.assertIn("terminal_plain_text", NATIVE)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "app" / "terminal" / "runtime.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "windows" / "main_window.py").read_text(encoding="utf-8")
MATRIX = (ROOT / "app" / "widgets" / "page_matrix.py").read_text(encoding="utf-8")


class TerminalIntegrationRegressionTest(unittest.TestCase):
    def test_terminal_service_stays_loopback_only(self) -> None:
        self.assertIn('TERMINAL_HOST = "127.0.0.1"', RUNTIME)

    def test_runtime_has_windows_and_unix_pty_paths(self) -> None:
        self.assertIn('if os.name == "nt":', RUNTIME)
        self.assertIn('from winpty import PtyProcess', RUNTIME)
        self.assertIn('pid, fd = pty.fork()', RUNTIME)
        self.assertIn('NINO_TERMINAL_SHELL', RUNTIME)

    def test_main_window_routes_run_slot_to_terminal_workspace(self) -> None:
        self.assertIn('self.terminal_workspace = TerminalWorkspace(self.terminal_runtime)', MAIN)
        self.assertIn('self.terminal_workspace.activate()', MAIN)
        self.assertIn('self.terminal_workspace.shutdown()', MAIN)

    def test_matrix_exposes_terminal_control(self) -> None:
        self.assertIn('QPushButton("TERM")', MATRIX)
        self.assertIn('Ouvrir le terminal LinuxIA', MATRIX)

    def test_terminal_assets_are_present(self) -> None:
        for relative in (
            "app/assets/terminal/terminal.html",
            "app/assets/terminal/xterm.js",
            "app/assets/terminal/xterm.css",
            "app/assets/terminal/addon-fit.js",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()

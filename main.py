from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import APP_NAME
from app.focus_split_runtime import apply_runtime_focus_split
from app.matrix_icon_fixes import apply_runtime_matrix_icon_fixes
from app.styles import build_app_stylesheet
from app.text_fixes import apply_runtime_text_fixes
from app.windows.main_window import MainWindow


def main() -> int:
    """Application entry point."""

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RunAssistant")
    app.setStyleSheet(build_app_stylesheet())

    window = MainWindow()
    apply_runtime_text_fixes(window)
    apply_runtime_matrix_icon_fixes(window)
    apply_runtime_focus_split(window)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

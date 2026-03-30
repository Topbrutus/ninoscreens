from __future__ import annotations

import sys
import os
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-blink-features=AutomationControlled "
    "--no-sandbox "
    "--disable-web-security "
    "--allow-running-insecure-content"
)

from PySide6.QtWidgets import QApplication

from app.config import APP_NAME
from app.styles import build_app_stylesheet
from app.windows.main_window import MainWindow


def main() -> int:
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RunAssistant")
    app.setStyleSheet(build_app_stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

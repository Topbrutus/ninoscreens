from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from app.brutus_rarity_watch import BrutusRarityHealth
from app.config import APP_NAME
from app.focus_split_runtime import apply_runtime_focus_split
from app.matrix_icon_fixes import apply_runtime_matrix_icon_fixes
from app.styles import build_app_stylesheet
from app.terminal import TerminalRuntimeError
from app.text_fixes import apply_runtime_text_fixes
from app.widgets.brutus_rarity_watch import BrutusRarityWatchController
from app.windows.main_window import MainWindow


def main() -> int:
    """Application entry point."""

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RunAssistant")
    app.setStyleSheet(build_app_stylesheet())

    window = MainWindow()
    try:
        window.terminal_runtime.ensure_started()
    except TerminalRuntimeError as exc:
        print(f"Nino TERM backend unavailable at startup: {exc}", file=sys.stderr)

    apply_runtime_text_fixes(window)
    apply_runtime_matrix_icon_fixes(window)
    apply_runtime_focus_split(window)

    brutus_watch = BrutusRarityWatchController(
        os.environ.get("NINO_BRUTUS_STATUS_URL", "http://127.0.0.1:8788/api/status"),
        parent=window,
    )

    def on_brutus_health(health: BrutusRarityHealth) -> None:
        if health.ok:
            pending = " / PENDING" if health.pending_refresh else ""
            short = f"BRUTUS {health.runtime_state} • RARITY LOCK OK{pending}"
            detail = (
                f"NINO • {short} • snapshot G{health.snapshot_generation} • "
                f"sélection N={health.selection_count}"
            )
        elif health.online:
            short = f"BRUTUS {health.runtime_state} • ALERTE RARETÉ"
            detail = f"NINO • {short} • {health.message}"
        else:
            short = "BRUTUS OFFLINE"
            detail = f"NINO • {short} • {health.message}"
        window.setWindowTitle(f"{APP_NAME} — {short}")
        window.statusBar().showMessage(detail)

    brutus_watch.health_ready.connect(on_brutus_health)
    app.aboutToQuit.connect(brutus_watch.stop)
    window._nino_brutus_rarity_watch = brutus_watch
    brutus_watch.start()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

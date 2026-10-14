from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from app.brutus_rarity_watch import BrutusRarityHealth, fetch_brutus_status


class BrutusRarityWatchController(QObject):
    """Non-blocking, read-only Nino observer for the Brotoculateur rarity lock."""

    health_ready = Signal(object)

    def __init__(
        self,
        status_url: str,
        *,
        interval_ms: int = 2500,
        timeout_seconds: float = 0.8,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.status_url = status_url
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self._inflight = False
        self._stopped = False
        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(interval_ms)))
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self._stopped = False
        self._timer.start()
        QTimer.singleShot(250, self.poll)

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()

    def poll(self) -> None:
        if self._stopped or self._inflight:
            return
        self._inflight = True
        threading.Thread(target=self._worker, name="nino-brutus-rarity-watch", daemon=True).start()

    def _worker(self) -> None:
        try:
            health: BrutusRarityHealth = fetch_brutus_status(
                self.status_url,
                timeout_seconds=self.timeout_seconds,
            )
            if not self._stopped:
                self.health_ready.emit(health)
        finally:
            self._inflight = False

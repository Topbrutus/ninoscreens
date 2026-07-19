from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.chatgpt_bridge_browser import ChatGPTBridgeBrowserHost


class ChatGPTBridgeWorkspace(QFrame):
    back_requested = Signal()

    def __init__(self, host: ChatGPTBridgeBrowserHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.setObjectName("ChatGPTBridgeWorkspace")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("ChatGPT Bridge")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.back_button = QPushButton("Retour")
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(title, 1)
        header.addWidget(self.back_button)
        layout.addLayout(header)

        self.status_frame = QFrame()
        self.status_frame.setObjectName("BridgeStatusPanel")
        status_layout = QGridLayout(self.status_frame)
        status_layout.setContentsMargins(10, 10, 10, 10)
        status_layout.setSpacing(6)
        self.values: dict[str, QLabel] = {}
        labels = [
            ("BRIDGE BROWSER", "browser"),
            ("SESSION", "session"),
            ("TARGET", "target"),
            ("CURRENT URL", "current_url"),
            ("COMPOSER", "composer"),
            ("GENERATION", "generation"),
            ("CYCLE", "cycle"),
            ("LAST ERROR", "last_error"),
            ("TRANSPORT", "transport"),
            ("VISIBLE PAGE DEPENDENCY", "visible_page_dependency"),
        ]
        for row, (label, key) in enumerate(labels):
            name = QLabel(label)
            name.setObjectName("MutedText")
            value = QLabel("UNKNOWN")
            value.setTextInteractionFlags(value.textInteractionFlags())
            self.values[key] = value
            status_layout.addWidget(name, row, 0)
            status_layout.addWidget(value, row, 1)
        layout.addWidget(self.status_frame)

        controls = QHBoxLayout()
        self.open_button = QPushButton("Ouvrir la vue")
        self.refresh_button = QPushButton("Rafraîchir le statut")
        self.set_target_button = QPushButton("Définir cette conversation comme cible")
        self.clear_target_button = QPushButton("Effacer la cible")
        self.return_target_button = QPushButton("Revenir à la cible")
        self.diagnostic_button = QPushButton("Diagnostic sans envoi")
        controls.addWidget(self.open_button)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.set_target_button)
        controls.addWidget(self.clear_target_button)
        controls.addWidget(self.return_target_button)
        controls.addWidget(self.diagnostic_button)
        layout.addLayout(controls)

        self.browser_container = QFrame()
        browser_layout = QVBoxLayout(self.browser_container)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.host.widget(), 1)
        layout.addWidget(self.browser_container, 1)

        self.open_button.clicked.connect(self.host.navigate_to_target)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.return_target_button.clicked.connect(self.host.navigate_to_target)
        self.diagnostic_button.clicked.connect(self.run_diagnostic)
        self.set_target_button.clicked.connect(self.set_current_as_target)
        self.clear_target_button.clicked.connect(self.clear_target)
        self.host.status_changed.connect(self.apply_status)
        self.refresh_status()

    def apply_status(self, status: dict) -> None:
        for key, label in self.values.items():
            label.setText(str(status.get(key, "UNKNOWN") or ""))

    def refresh_status(self) -> None:
        self.host.refresh_status(self.apply_status)

    def run_diagnostic(self) -> None:
        self.host.diagnostic_without_send(self.apply_status)

    def set_current_as_target(self) -> None:
        ok, reason = self.host.set_current_conversation_as_target()
        if not ok:
            QMessageBox.warning(self, "Cible non valide", reason)

    def clear_target(self) -> None:
        reply = QMessageBox.question(self, "Effacer la cible", "Effacer la conversation cible Bridge ?")
        if reply == QMessageBox.StandardButton.Yes:
            self.host.clear_target()

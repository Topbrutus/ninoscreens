from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

        self.target_frame = QFrame()
        target_layout = QGridLayout(self.target_frame)
        target_layout.setContentsMargins(10, 10, 10, 10)
        target_layout.setSpacing(6)
        self.target_title = QLabel("CONVERSATION CIBLE DU BRIDGE")
        self.target_url_edit = QLineEdit(self.host.target_url())
        self.target_url_edit.setPlaceholderText("https://chatgpt.com/c/...")
        self.use_current_url_button = QPushButton("Utiliser l'URL actuelle")
        self.apply_target_button = QPushButton("Appliquer au Bridge")
        self.open_target_button = QPushButton("Ouvrir la cible")
        self.test_target_button = QPushButton("Tester sans envoyer")
        self.clear_target_button = QPushButton("Effacer la cible")
        self.unapplied_label = QLabel("")
        self.unapplied_label.setObjectName("WarningText")
        target_layout.addWidget(self.target_title, 0, 0)
        target_layout.addWidget(self.target_url_edit, 0, 1)
        target_layout.addWidget(self.use_current_url_button, 0, 2)
        target_layout.addWidget(self.apply_target_button, 0, 3)
        target_layout.addWidget(self.open_target_button, 1, 1)
        target_layout.addWidget(self.test_target_button, 1, 2)
        target_layout.addWidget(self.clear_target_button, 1, 3)
        target_layout.addWidget(self.unapplied_label, 2, 1, 1, 3)
        layout.addWidget(self.target_frame)

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
            ("CONFIGURED AT", "configured_at"),
            ("LAST VALIDATION", "last_validated_at"),
            ("CONVERSATION ID", "target_conversation_id"),
            ("VALIDATION", "validation_status"),
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
        self.refresh_button = QPushButton("Rafraîchir le statut")
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.browser_container = QFrame()
        browser_layout = QVBoxLayout(self.browser_container)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.host.widget(), 1)
        layout.addWidget(self.browser_container, 1)

        self.refresh_button.clicked.connect(self.refresh_status)
        self.use_current_url_button.clicked.connect(self.use_current_url)
        self.apply_target_button.clicked.connect(self.apply_target)
        self.open_target_button.clicked.connect(self.host.navigate_to_target)
        self.test_target_button.clicked.connect(self.run_diagnostic)
        self.clear_target_button.clicked.connect(self.clear_target)
        self.target_url_edit.textChanged.connect(self.refresh_unapplied_indicator)
        self.host.status_changed.connect(self.apply_status)
        self.refresh_status()

    def apply_status(self, status: dict) -> None:
        for key, label in self.values.items():
            label.setText(str(status.get(key, "UNKNOWN") or ""))
        self.refresh_unapplied_indicator()

    def refresh_status(self) -> None:
        self.refresh_button.setEnabled(False)
        self.values["session"].setText("SESSION_LOADING")
        self.values["composer"].setText("LOADING")
        self.values["last_error"].setText("VALIDATION_IN_PROGRESS")

        def _done(status: dict) -> None:
            self.apply_status(status)
            self.refresh_button.setEnabled(True)

        self.host.refresh_status(_done)

    def run_diagnostic(self) -> None:
        self.host.diagnostic_without_send(self.apply_status)

    def use_current_url(self) -> None:
        self.target_url_edit.setText(self.host.current_url())
        self.refresh_unapplied_indicator()

    def apply_target(self) -> None:
        self.apply_target_button.setEnabled(False)
        self.apply_target_button.setText("Validation en cours...")

        def _done(result: dict) -> None:
            self.apply_target_button.setEnabled(True)
            self.apply_target_button.setText("Appliquer au Bridge")
            if not result.get("ok"):
                reason = str(result.get("reason") or result.get("status") or "INVALID")
                session = str(result.get("session") or self.values["session"].text() or "SESSION_UNKNOWN")
                composer = str(result.get("composer") or self.values["composer"].text() or "UNKNOWN")
                short_url = self.target_url_edit.text().strip().split("?", 1)[0]
                QMessageBox.warning(
                    self,
                    "Cible non valide",
                    f"{reason}\nSESSION: {session}\nCOMPOSER: {composer}\nURL: {short_url}",
                )
            else:
                self.target_url_edit.setText(self.host.target_url())
            self.refresh_status()

        self.host.apply_target_url(self.target_url_edit.text(), _done)

    def refresh_unapplied_indicator(self) -> None:
        configured = self.host.target_url()
        current = self.target_url_edit.text().strip()
        self.unapplied_label.setText("CHANGEMENTS NON APPLIQUES" if current != configured else "")

    def clear_target(self) -> None:
        reply = QMessageBox.question(self, "Effacer la cible", "Effacer la conversation cible Bridge ?")
        if reply == QMessageBox.StandardButton.Yes:
            self.host.clear_target()
            self.target_url_edit.setText("")
            self.refresh_status()

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.api_connectors import ApiConnectionSettings, get_service_definition, list_service_definitions


@dataclass(frozen=True)
class ApiPanelState:
    connected: bool = False
    service_id: str = "openai-compatible"
    base_url: str = ""
    test_path: str = ""
    secured_storage_used: bool = False
    masked_key_hint: str = ""
    status_text: str = ""


class ApiConnectionPanel(QFrame):
    connect_requested = Signal(object)
    disconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")
        self._definitions = list_service_definitions()
        self._building = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Connexion API")
        title.setStyleSheet("font-weight: 700;")

        description = QLabel("Cné masquée aprȨs validation. Stockage sécirisé utilisé seulement si disponible.")
        description.setWordWrap(True)
        description.setObjectName("MutedText")

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.service_combo = QComboBox()
        for definition in self._definitions:
            self.service_combo.addItem(definition.label, definition.service_id)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com")

        self.test_path_edit = QLineEdit()
        self.test_path_edit.setPlaceholderText("/v1/models")

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Coller la clé API ici")

        self.remember_checkbox = QCheckBox("Conserver la clé dans le stockage sécurisé local")
        self.remember_checkbox.setChecked(True)

        form.addRow("Service", self.service_combo)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("Chemin test", self.test_path_edit)
        form.addRow("Cné API", self.api_key_edit)
        form.addRow("", self.remember_checkbox)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)

        self.test_button = QPushButton("Tester et connecter")
        self.test_button.setProperty("role", "accent")
        self.disconnect_button = QPushButton("Déconnecter")
        self.disconnect_button.setProperty("role", "danger")
        self.disconnect_button.setEnabled(False)

        buttons.addWidget(self.test_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("MutedText")

        root.addWidget(title)
        root.addWidget(description)
        root.addLayout(form)
        root.addLayout(buttons)
        root.addWidget(self.status_label)

        self.service_combo.currentIndexChanged.connect(self._sync_definition_defaults)
        self.test_button.clicked.connect(self._emit_connect_requested)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)

        self._sync_definition_defaults()

    def _sync_definition_defaults(self) -> None:
        if self._building:
            return
        definition = get_service_definition(self.current_service_id)
        if not self.base_url_edit.text().strip():
            self.base_url_edit.setText(definition.default_base_url)
        if not self.test_path_edit.text().strip():
            self.test_path_edit.setText(definition.default_test_path)
        self.status_label.setText(definition.description)

    @property
    def current_service_id(self) -> str:
        return str(self.service_combo.currentData())

    def _emit_connect_requested(self) -> None:
        settings = ApiConnectionSettings(
            service_id=self.current_service_id,
            base_url=self.base_url_edit.text().strip(),
            api_key=self.api_key_edit.text(),
            test_path=self.test_path_edit.text().strip(),
        )
        self.connect_requested.emit(settings)

    def set_secure_storage_available(self, available: bool) -> None:
        self.remember_checkbox.setEnabled(available)
        if not available:
            self.remember_checkbox.setChecked(False)
            self.remember_checkbox.setToolTip("Aucun stockage sécurisé détecté : la clé restera seulement en mémoire.")
        else:
            self.remember_checkbox.setToolTip("")

    def apply_state(self, state: ApiPanelState) -> None:
        self._building = True
        try:
            index = self.service_combo.findData(state.service_id)
            if index >= 0:
                self.service_combo.setCurrentIndex(index)
            if state.base_url:
                self.base_url_edit.setText(state.base_url)
            if state.test_path:
                self.test_path_edit.setText(state.test_path)
            self.disconnect_button.setEnabled(state.connected)
            self.test_button.setText("Reconnecter" if state.connected else "Tester et connecter")

            if state.connected:
                self.api_key_edit.clear()
                self.api_key_edit.setPlaceholderText("Cné masquée et non réaffichée")
            else:
                self.api_key_edit.setPlaceholderText("Coller la clé API ici")

            suffix = " (stockage sécurisé)" if state.secured_storage_used else " (session courante)"
            hint = f" — {state.masked_key_hint}" if state.masked_key_hint else ""
            if state.connected:
                self.status_label.setText(f"{state.status_text}{hint}{suffix}")
            else:
                self.status_label.setText(state.status_text)
        finally:
            self._building = False

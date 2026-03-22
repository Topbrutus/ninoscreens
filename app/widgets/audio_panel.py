from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QVBoxLayout, QWidget


class AudioSettingsPanel(QFrame):
    settings_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("Feedback audio")
        title.setStyleSheet("font-weight: 700;")

        self.sounds_checkbox = QCheckBox("Activer les sons")
        self.sounds_checkbox.setChecked(True)

        self.voice_checkbox = QCheckBox("Activer la voix")
        self.voice_checkbox.setChecked(False)

        self.blocked_checkbox = QCheckBox("Parler quand un blocage important survient")
        self.blocked_checkbox.setChecked(True)

        self.complete_checkbox = QCheckBox("Parler quand une tâche est terminée")
        self.complete_checkbox.setChecked(True)

        self.api_checkbox = QCheckBox("Parler quand la connexion API est validée")
        self.api_checkbox.setChecked(False)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("MutedText")

        for widget in (
            title,
            self.sounds_checkbox,
            self.voice_checkbox,
            self.blocked_checkbox,
            self.complete_checkbox,
            self.api_checkbox,
            self.status_label,
        ):
            root.addWidget(widget)

        for checkbox in (
            self.sounds_checkbox,
            self.voice_checkbox,
            self.blocked_checkbox,
            self.complete_checkbox,
            self.api_checkbox,
        ):
            checkbox.toggled.connect(self._emit_settings)

    def set_voice_available(self, available: bool) -> None:
        self.voice_checkbox.setEnabled(available)
        if available:
            self.status_label.setText("Voix disponible. Les messages restent courts et limités.")
        else:
            self.voice_checkbox.setChecked(False)
            self.status_label.setText("Voix indisponible. Les sons restent utilisables.")

    def _emit_settings(self) -> None:
        self.settings_changed.emit(
            {
                "sound_enabled": self.sounds_checkbox.isChecked(),
                "voice_enabled": self.voice_checkbox.isChecked(),
                "speak_blocked": self.blocked_checkbox.isChecked(),
                "speak_task_complete": self.complete_checkbox.isChecked(),
                "speak_api_connected": self.api_checkbox.isChecked(),
            }
        )

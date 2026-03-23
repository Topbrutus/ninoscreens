from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    )


class RunWorkspace(QFrame):
    prompt_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("RUN / Corvo")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        subtitle = QLabel(
            "Espace dédié à Run : journal, terminal, zone de parole et future console d’outils."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("MutedText")

        tools_frame = QFrame()
        tools_layout = QGridLayout(tools_frame)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setHorizontalSpacing(8)
        tools_layout.setVerticalSpacing(8)

        self.tool_buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate(
            (
                ("monitor", "Monitor"),
                ("voice", "Voix"),
                ("audio", "Audio"),
                ("api", "API"),
                ("micro", "Micro"),
                ("tools", "Outils+"),
            )
        ):
            button = QPushButton(label)
            button.setProperty("compact", True)
            button.setToolTip("Emplacement réservé pour une fonction Run future.")
            button.setEnabled(False)
            row, column = divmod(index, 3)
            tools_layout.addWidget(button, row, column)
            self.tool_buttons[key] = button

        self.monitor = QTextEdit()
        self.monitor.setReadOnly(True)
        self.monitor.setPlaceholderText("Le moniteur RUN apparaîtra ici.")
        self.monitor.setMinimumHeight(280)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("GÉcrire à Run ici puis appuyer Entrée…")
        self.input_edit.returnPressed.connect(self._submit_prompt)

        self.send_button = QPushButton("Envoyer")
        self.send_button.setProperty("role", "accent")
        self.send_button.clicked.connect(self._submit_prompt)

        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(self.send_button)

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(tools_frame)
        root.addWidget(self.monitor, 1)
        root.addLayout(input_row)

        self.append_system_message("Workspace RUN initialisé. Les outils avancés arriveront ensuite.")

    def append_system_message(self, text: str, *, tone: str = "info") -> None:
        clean = text.strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "RUN",
            "success": "OK",
            "blocked": "BLOCK",
            "error": "ERR",
        }.get(tone, "RUN")
        self.monitor.append(f"[{stamp}] {prefix} > {clean}")

    def append_user_message(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.monitor.append(f"[{stamp}] YOU > {clean}")

    def _submit_prompt(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.append_user_message(text)
        self.prompt_submitted.emit(text)
        self.input_edit.clear()

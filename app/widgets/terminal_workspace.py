from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)


class TerminalWorkspace(QFrame):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Terminal")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        self.back_button = QPushButton("Retour à la grille")
        self.back_button.setProperty("compact", True)
        self.back_button.setToolTip("Revenir à la grille principale")
        self.back_button.clicked.connect(self.back_requested.emit)

        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.back_button)

        subtitle = QLabel(
            "Interface Terminal en préparation. Cette phase remplace uniquement l’ancienne page RUN dans la navigation."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("MutedText")

        tabs_frame = QFrame()
        tabs_layout = QHBoxLayout(tabs_frame)
        tabs_layout.setContentsMargins(12, 10, 12, 10)
        tabs_layout.setSpacing(8)

        tabs_label = QLabel("Onglets")
        tabs_label.setObjectName("SecondaryText")

        self.tab_bar = QTabBar()
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setMovable(False)
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_bar.setMinimumHeight(32)
        self.tab_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.add_tab_button = QPushButton("+")
        self.add_tab_button.setProperty("compact", True)
        self.add_tab_button.setEnabled(False)
        self.add_tab_button.setToolTip("L’ajout d’onglets sera activé en phase suivante")

        tabs_layout.addWidget(tabs_label)
        tabs_layout.addWidget(self.tab_bar, 1)
        tabs_layout.addWidget(self.add_tab_button)

        self.placeholder_frame = QFrame()
        self.placeholder_frame.setObjectName("TerminalPlaceholder")
        placeholder_layout = QVBoxLayout(self.placeholder_frame)
        placeholder_layout.setContentsMargins(20, 20, 20, 20)
        placeholder_layout.setSpacing(10)

        placeholder_title = QLabel("Zone réservée au futur terminal")
        placeholder_title.setStyleSheet("font-size: 16px; font-weight: 600;")

        placeholder_body = QLabel(
            "Aucun terminal réel n’est lancé à cette étape.\n"
            "Cette zone est uniquement un emplacement réservé pour la phase suivante."
        )
        placeholder_body.setWordWrap(True)
        placeholder_body.setObjectName("MutedText")
        placeholder_body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        placeholder_layout.addWidget(placeholder_title)
        placeholder_layout.addWidget(placeholder_body)
        placeholder_layout.addStretch(1)

        root.addLayout(header)
        root.addWidget(subtitle)
        root.addWidget(tabs_frame)
        root.addWidget(self.placeholder_frame, 1)

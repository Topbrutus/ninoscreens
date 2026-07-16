from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QUrlQuery
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from app.terminal import TerminalRuntime, TerminalRuntimeError


class TerminalWorkspace(QFrame):
    back_requested = Signal()

    def __init__(self, runtime: TerminalRuntime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._terminal_loaded = False
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Terminal")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        self.mode_label = QLabel("MODE MANUEL")
        self.mode_label.setObjectName("SecondaryText")
        self.mode_label.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #3b6e9e; border-radius: 999px; background: #21415f; font-weight: 700;"
        )

        self.back_button = QPushButton("Retour à la grille")
        self.back_button.setProperty("compact", True)
        self.back_button.setToolTip("Revenir à la grille principale")
        self.back_button.clicked.connect(self.back_requested.emit)

        header.addWidget(title)
        header.addWidget(self.mode_label)
        header.addStretch(1)
        header.addWidget(self.back_button)

        self.status_label = QLabel("Service terminal local arrêté.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("MutedText")

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

        self.copy_button = QPushButton("Copier")
        self.copy_button.setProperty("compact", True)
        self.copy_button.setToolTip("Copier la sélection du terminal")
        self.copy_button.clicked.connect(self.copy_selection)

        self.paste_button = QPushButton("Coller")
        self.paste_button.setProperty("compact", True)
        self.paste_button.setToolTip("Coller le presse-papiers dans le terminal")
        self.paste_button.clicked.connect(self.paste_clipboard)

        tabs_layout.addWidget(tabs_label)
        tabs_layout.addWidget(self.tab_bar, 1)
        tabs_layout.addWidget(self.copy_button)
        tabs_layout.addWidget(self.paste_button)
        tabs_layout.addWidget(self.add_tab_button)

        self.view_stack = QStackedLayout()

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

        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)

        self.view_stack.addWidget(self.placeholder_frame)
        self.view_stack.addWidget(self.web_view)

        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.copy_shortcut.activated.connect(self.copy_selection)
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+Shift+V"), self)
        self.paste_shortcut.activated.connect(self.paste_clipboard)

        root.addLayout(header)
        root.addWidget(self.status_label)
        root.addWidget(tabs_frame)
        root.addLayout(self.view_stack, 1)

    def activate(self) -> bool:
        try:
            info = self.runtime.ensure_started()
        except TerminalRuntimeError as exc:
            self.status_label.setText(f"MODE MANUEL • Échec du terminal local: {exc}")
            self.view_stack.setCurrentWidget(self.placeholder_frame)
            return False

        self.status_label.setText(
            f"MODE MANUEL • {info['host']}:{info['port']} • PID {info['pid']} • {info['cwd']}"
        )
        if not self._terminal_loaded:
            self._load_terminal_page(info["ws_url"])
            self._terminal_loaded = True
        self.view_stack.setCurrentWidget(self.web_view)
        self.web_view.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def refresh_runtime_status(self) -> None:
        info = self.runtime.snapshot()
        if info.get("alive"):
            self.status_label.setText(
                f"MODE MANUEL • {info['host']}:{info['port']} • PID {info['pid']} • {info['cwd']}"
            )
        else:
            self.status_label.setText("Service terminal local arrêté.")

    def shutdown(self) -> None:
        self.runtime.shutdown()
        self._terminal_loaded = False
        self.view_stack.setCurrentWidget(self.placeholder_frame)
        self.status_label.setText("Service terminal local arrêté.")

    def copy_selection(self) -> None:
        self.web_view.page().runJavaScript("window.ninoTerminalApi?.getSelection?.() ?? ''", self._store_selection)

    def paste_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text()
        if not text:
            return
        self.web_view.page().runJavaScript(
            f"window.ninoTerminalApi?.pasteText?.({json.dumps(text)});"
        )

    def send_line(self, text: str) -> None:
        self.web_view.page().runJavaScript(
            f"window.ninoTerminalApi?.sendLine?.({json.dumps(text)});"
        )

    def send_interrupt(self) -> None:
        self.web_view.page().runJavaScript("window.ninoTerminalApi?.sendInterrupt?.();")

    def terminal_dump(self, callback) -> None:
        self.web_view.page().runJavaScript("window.ninoTerminalApi?.dumpText?.() ?? ''", callback)

    def fit_terminal(self) -> None:
        self.web_view.page().runJavaScript("window.ninoTerminalApi?.fitNow?.();")

    def _store_selection(self, value: object) -> None:
        text = str(value or "")
        if not text:
            return
        QGuiApplication.clipboard().setText(text)

    def _load_terminal_page(self, ws_url: str) -> None:
        html_path = Path(__file__).resolve().parents[1] / "assets" / "terminal" / "terminal.html"
        url = QUrl.fromLocalFile(str(html_path))
        query = QUrlQuery()
        query.addQueryItem("ws", ws_url)
        url.setQuery(query)
        self.web_view.setUrl(url)

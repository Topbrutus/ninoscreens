from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
_WEBENGINE_FRONTEND_REQUESTED = (
    os.name == "nt"
    or os.environ.get("NINO_TERMINAL_FRONTEND", "").strip().lower() == "web"
)
if _WEBENGINE_FRONTEND_REQUESTED:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
else:
    QWebEngineSettings = None
    QWebEngineView = None
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from app.terminal import TerminalRuntime, TerminalRuntimeError
from app.widgets.native_terminal_view import NativeTerminalView


class TerminalWorkspace(QFrame):
    back_requested = Signal()

    def __init__(self, runtime: TerminalRuntime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        frontend = os.environ.get("NINO_TERMINAL_FRONTEND", "").strip().lower()
        self._use_web_terminal = frontend == "web" or (frontend != "native" and os.name == "nt")
        self._terminal_loaded = False
        self._web_ready = False
        self._pending_session_id: str | None = None
        self._selected_session_id: str | None = None
        self._auto_create_initial_session = True
        self._syncing_tabs = False
        self._native_poll_timer = QTimer(self)
        self._native_poll_timer.setInterval(120)
        self._native_poll_timer.timeout.connect(self._refresh_native_terminal)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self._apply_terminal_focus)
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
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_bar.setMinimumHeight(32)
        self.tab_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.tabCloseRequested.connect(self.close_tab_at)

        self.add_tab_button = QPushButton("+")
        self.add_tab_button.setProperty("compact", True)
        self.add_tab_button.setEnabled(False)
        self.add_tab_button.setToolTip("Ouvrir un nouvel onglet terminal")
        self.add_tab_button.clicked.connect(self.open_new_tab)

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

        self.placeholder_title = QLabel("Terminal inactif")
        self.placeholder_title.setStyleSheet("font-size: 16px; font-weight: 600;")

        self.placeholder_body = QLabel("")
        self.placeholder_body.setWordWrap(True)
        self.placeholder_body.setObjectName("MutedText")
        self.placeholder_body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        placeholder_layout.addWidget(self.placeholder_title)
        placeholder_layout.addWidget(self.placeholder_body)
        placeholder_layout.addStretch(1)

        self.web_view = None
        self.native_view = None
        self.view_stack.addWidget(self.placeholder_frame)
        if self._use_web_terminal:
            self.web_view = QWebEngineView()
            self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
            settings = self.web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)
            self.web_view.loadFinished.connect(self._on_terminal_page_loaded)
            self.view_stack.addWidget(self.web_view)
        else:
            self.native_view = NativeTerminalView()
            self.native_view.input_requested.connect(self._send_native_input)
            self.native_view.interrupt_requested.connect(self.send_interrupt)
            self.native_view.paste_requested.connect(self.paste_clipboard)
            self.view_stack.addWidget(self.native_view)
            self._web_ready = True

        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.copy_shortcut.activated.connect(self.copy_selection)
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+Shift+V"), self)
        self.paste_shortcut.activated.connect(self.paste_clipboard)

        root.addLayout(header)
        root.addWidget(self.status_label)
        root.addWidget(tabs_frame)
        root.addLayout(self.view_stack, 1)

        self._show_empty_state(
            "Aucun onglet Terminal ouvert",
            "Cliquez sur + pour créer une nouvelle session terminal locale.",
        )

    def activate(self) -> bool:
        try:
            service_info = self.runtime.ensure_started()
        except TerminalRuntimeError as exc:
            self.status_label.setText(f"MODE MANUEL • Échec du terminal local: {exc}")
            self._show_empty_state(
                "Terminal indisponible",
                "Le service local n’a pas démarré. Aucun onglet n’est accessible.",
            )
            return False

        self.add_tab_button.setEnabled(True)
        if not self._terminal_loaded:
            if self._use_web_terminal:
                self._load_terminal_page(service_info["ws_url"])
            else:
                self._web_ready = True
                self._native_poll_timer.start()
            self._terminal_loaded = True

        sessions = self.runtime.list_sessions()
        if not sessions and self._auto_create_initial_session:
            created = self.runtime.create_session()
            sessions = [created]
            self._auto_create_initial_session = False

        preferred_session_id = self._selected_session_id
        if preferred_session_id is None and sessions:
            preferred_session_id = sessions[0]["session_id"]
        self._sync_tabs_from_sessions(sessions, preferred_session_id)
        self._refresh_status()

        if self._selected_session_id is None:
            self._show_empty_state(
                "Aucun onglet Terminal ouvert",
                "Le service local reste actif. Utilisez + pour créer une nouvelle session terminal.",
            )
            return True

        self.view_stack.setCurrentWidget(self._terminal_widget())
        self._attach_selected_session()
        self.request_terminal_focus()
        return True

    def refresh_runtime_status(self) -> None:
        try:
            sessions = self.runtime.list_sessions()
        except TerminalRuntimeError:
            sessions = []
        self._sync_tabs_from_sessions(sessions, self._selected_session_id)
        self._refresh_status()

    def shutdown(self) -> None:
        self._native_poll_timer.stop()
        self.runtime.shutdown()
        self._terminal_loaded = False
        self._web_ready = False
        self._pending_session_id = None
        self._selected_session_id = None
        self._sync_tabs_from_sessions([], None)
        self._show_empty_state(
            "Terminal arrêté",
            "Le service terminal local est arrêté.",
        )
        self.status_label.setText("Service terminal local arrêté.")

    def open_new_tab(self) -> None:
        try:
            session = self.runtime.create_session()
        except TerminalRuntimeError as exc:
            self.status_label.setText(f"MODE MANUEL • Création d’onglet impossible: {exc}")
            return

        self._auto_create_initial_session = False
        self._sync_tabs_from_sessions(self.runtime.list_sessions(), session["session_id"])
        self.view_stack.setCurrentWidget(self._terminal_widget())
        self._attach_selected_session()
        self._refresh_status()
        self.request_terminal_focus()

    def close_tab_at(self, index: int) -> None:
        session_id = self._tab_session_id(index)
        if not session_id:
            return

        session = self.runtime.session_snapshot(session_id)
        if session and session.get("alive"):
            result = QMessageBox.question(
                self,
                "Fermer l’onglet Terminal",
                f"{session['display_name']} est encore actif (PID {session['pid']}). Fermer cette session ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        try:
            self.runtime.close_session(session_id)
        except TerminalRuntimeError as exc:
            self.status_label.setText(f"MODE MANUEL • Fermeture impossible: {exc}")
            return

        sessions = self.runtime.list_sessions()
        next_session_id = None
        if sessions:
            fallback_index = min(index, len(sessions) - 1)
            next_session_id = sessions[fallback_index]["session_id"]
        self._sync_tabs_from_sessions(sessions, next_session_id)
        self._refresh_status()

        if self._selected_session_id is None:
            self._show_empty_state(
                "Aucun onglet Terminal ouvert",
                "La dernière session a été fermée. Cliquez sur + pour en créer une nouvelle.",
            )
            return

        self.view_stack.setCurrentWidget(self._terminal_widget())
        self._attach_selected_session()
        self.request_terminal_focus()

    def copy_selection(self) -> None:
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.getSelection?.() ?? ''", self._store_selection)
            return
        if self.native_view is not None:
            self.native_view.copy()

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            return
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript(f"window.ninoTerminalApi?.pasteText?.({json.dumps(text)});")
            return
        self._send_native_input(text)

    def send_line(self, text: str) -> None:
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript(f"window.ninoTerminalApi?.sendLine?.({json.dumps(text)});")
            return
        self._send_native_input(f"{text}\r")

    def send_interrupt(self) -> None:
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.sendInterrupt?.();")
            return
        session_id = self._selected_session_id
        if session_id:
            self.runtime.send_interrupt(session_id)

    def terminal_dump(self, callback) -> None:
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.dumpText?.() ?? ''", callback)
            return
        callback(self.native_view.dump_text() if self.native_view is not None else "")

    def fit_terminal(self) -> None:
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.fitNow?.();")
            return
        session_id = self._selected_session_id
        if not session_id or self.native_view is None:
            return
        metrics = self.native_view.fontMetrics()
        char_width = max(1, metrics.horizontalAdvance("M"))
        line_height = max(1, metrics.lineSpacing())
        cols = max(20, self.native_view.viewport().width() // char_width)
        rows = max(10, self.native_view.viewport().height() // line_height)
        self.runtime.resize_session(session_id, rows, cols)

    def request_terminal_focus(self) -> None:
        self._focus_timer.start(0)

    def _send_native_input(self, data: str) -> None:
        session_id = self._selected_session_id
        if not session_id or not data:
            return
        try:
            self.runtime.send_input(session_id, data)
        except TerminalRuntimeError as exc:
            self.status_label.setText(f"MODE MANUEL • Entrée terminal impossible: {exc}")

    def current_session_id(self) -> str | None:
        return self._selected_session_id

    def current_session_snapshot(self) -> dict | None:
        session_id = self._selected_session_id
        if not session_id:
            return None
        return self.runtime.session_snapshot(session_id)

    def list_session_snapshots(self) -> list[dict]:
        return self.runtime.list_sessions()

    def _store_selection(self, value: object) -> None:
        text = str(value or "")
        if not text:
            return
        QGuiApplication.clipboard().setText(text)

    def _terminal_widget(self) -> QWidget:
        if self._use_web_terminal and self.web_view is not None:
            return self.web_view
        if self.native_view is not None:
            return self.native_view
        return self.placeholder_frame

    def _load_terminal_page(self, ws_url: str) -> None:
        if not self._use_web_terminal or self.web_view is None:
            return
        html_path = Path(__file__).resolve().parents[1] / "assets" / "terminal" / "terminal.html"
        url = QUrl.fromLocalFile(str(html_path))
        query = QUrlQuery()
        query.addQueryItem("ws", ws_url)
        url.setQuery(query)
        self.web_view.setUrl(url)

    def _on_terminal_page_loaded(self, ok: bool) -> None:
        self._web_ready = ok
        if ok:
            self._attach_selected_session()
            self.request_terminal_focus()

    def _on_tab_changed(self, index: int) -> None:
        if self._syncing_tabs:
            return

        session_id = self._tab_session_id(index)
        if session_id == self._selected_session_id:
            self._refresh_status()
            return

        self._selected_session_id = session_id
        self._refresh_status()
        if session_id is None:
            self._show_empty_state(
                "Aucun onglet Terminal ouvert",
                "Cliquez sur + pour créer une nouvelle session terminal locale.",
            )
            return

        self.view_stack.setCurrentWidget(self._terminal_widget())
        self._attach_selected_session()
        self.request_terminal_focus()

    def _tab_session_id(self, index: int) -> str | None:
        if index < 0 or index >= self.tab_bar.count():
            return None
        value = self.tab_bar.tabData(index)
        text = str(value or "").strip()
        return text or None

    def _sync_tabs_from_sessions(self, sessions: list[dict], preferred_session_id: str | None) -> None:
        self._syncing_tabs = True
        try:
            while self.tab_bar.count() > 0:
                self.tab_bar.removeTab(0)
            for session in sessions:
                label = str(session.get("display_name") or session["session_id"])
                index = self.tab_bar.addTab(label)
                self.tab_bar.setTabData(index, session["session_id"])
                self.tab_bar.setTabToolTip(
                    index,
                    f"{label} • PID {session.get('pid') or '?'} • {session.get('state', 'unknown')}",
                )
            selected_session_id = preferred_session_id
            if selected_session_id is None and sessions:
                selected_session_id = sessions[0]["session_id"]
            selected_index = self._find_tab_index(selected_session_id)
            if selected_index < 0 and sessions:
                selected_index = 0
                selected_session_id = sessions[0]["session_id"]
            self._selected_session_id = selected_session_id if selected_index >= 0 else None
            if selected_index >= 0:
                self.tab_bar.setCurrentIndex(selected_index)
            else:
                self.tab_bar.setCurrentIndex(-1)
        finally:
            self._syncing_tabs = False

    def _find_tab_index(self, session_id: str | None) -> int:
        if not session_id:
            return -1
        for index in range(self.tab_bar.count()):
            if self._tab_session_id(index) == session_id:
                return index
        return -1

    def _attach_selected_session(self) -> None:
        session_id = self._selected_session_id
        if not session_id:
            return
        self._pending_session_id = session_id
        if self._use_web_terminal:
            if not self._web_ready or self.web_view is None:
                return
            self.web_view.page().runJavaScript(f"window.ninoTerminalApi?.attachSession?.({json.dumps(session_id)});")
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.fitNow?.();")
        else:
            self._refresh_native_terminal()
            self.fit_terminal()
        self._pending_session_id = None

    def _apply_terminal_focus(self) -> None:
        widget = self._terminal_widget()
        if self.view_stack.currentWidget() is not widget:
            self.view_stack.setCurrentWidget(widget)
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        if self._use_web_terminal and self.web_view is not None:
            self.web_view.page().runJavaScript("window.ninoTerminalApi?.focusInput?.();")

    def _refresh_native_terminal(self) -> None:
        if self._use_web_terminal or self.native_view is None:
            return
        session_id = self._selected_session_id
        if not session_id:
            return
        try:
            raw = self.runtime.session_buffer(session_id)
        except TerminalRuntimeError:
            return
        self.native_view.update_from_raw(raw)

    def _refresh_status(self) -> None:
        service_info = self.runtime.snapshot()
        session_id = self._selected_session_id
        if not service_info.get("ready"):
            self.status_label.setText("Service terminal local arrêté.")
            return

        if session_id is None:
            self.status_label.setText(
                f"MODE MANUEL • {service_info['host']}:{service_info['port']} • aucun onglet • {service_info['session_count']} session(s)"
            )
            return

        session = self.runtime.session_snapshot(session_id)
        if not session:
            self.status_label.setText(
                f"MODE MANUEL • {service_info['host']}:{service_info['port']} • session indisponible"
            )
            return

        self.status_label.setText(
            f"MODE MANUEL • {service_info['host']}:{service_info['port']} • {session['display_name']} • PID {session['pid']} • {session['cwd']}"
        )

    def _show_empty_state(self, title: str, body: str) -> None:
        self.placeholder_title.setText(title)
        self.placeholder_body.setText(body)
        self.view_stack.setCurrentWidget(self.placeholder_frame)

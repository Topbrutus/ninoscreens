
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import time

from PySide6.QtCore import QEventLoop, QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon
from PySide6.QtTest import QTest

from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    DEFAULT_ZOOM,
    MAX_ZOOM,
    MIN_ZOOM,
    PALETTE,
    THUMBNAIL_CAPTURE_DELAY_MS,
    THUMBNAIL_CAPTURE_INTERVAL_MS,
    THUMBNAIL_IMAGE_SIZE,
    TOOLBAR_BUTTON_SIZE,
    URL_BAR_HEIGHT,
    ZOOM_STEP,
)
from app.state import TileState, TileVisualStatus
from app.url_utils import normalize_user_url


class PopUpCapturePage(QWebEnginePage):
    popup_url_ready = Signal(QUrl)

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)
        self.urlChanged.connect(self._forward_url)

    def _forward_url(self, url: QUrl) -> None:
        if url.isValid() and not url.isEmpty():
            self.popup_url_ready.emit(url)
            self.deleteLater()


class TileWebPage(QWebEnginePage):
    popup_url_ready = Signal(QUrl)

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)

    def createWindow(self, _type) -> QWebEnginePage:
        popup_page = PopUpCapturePage(self.profile(), self)
        popup_page.popup_url_ready.connect(self.popup_url_ready.emit)
        return popup_page


class WebTile(QFrame):
    state_changed = Signal(object)
    memory_requested = Signal(int)
    focus_requested = Signal(int)
    grid_requested = Signal(int)
    split_requested = Signal(int)
    grid_interchange_requested = Signal(int)
    split_interchange_requested = Signal(int)
    web_page_ready = Signal(object)
    web_page_released = Signal()

    def __init__(self, tile_id: int, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(parent)
        self.tile_id = tile_id
        self.profile = profile
        self._state = TileState(tile_id=tile_id)
        self._browser_container: QWidget | None = None
        self._web_view: QWebEngineView | None = None
        self._page: TileWebPage | None = None
        self._toolbar_focus_mode = False
        self._split_button_active = False
        self._split_panel_visible = False
        self._toolbar_feedback_timer = QTimer(self)
        self._toolbar_feedback_timer.setSingleShot(True)
        self._toolbar_feedback_timer.timeout.connect(self._clear_toolbar_feedback)
        self._browser_focus_timer = QTimer(self)
        self._browser_focus_timer.setSingleShot(True)
        self._browser_focus_timer.timeout.connect(self._apply_browser_focus)
        self._media_probe_installed = False
        self._media_audio_active = False
        self._media_video_active = False
        self._media_last_error = ""
        self._web_text_submission_busy = False
        self._web_text_one_shot_used = False

        self.setObjectName("TileFrame")
        self.setProperty("focused", False)
        self.setMinimumSize(QSize(240, 180))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedLayout()
        root.addLayout(self.stack)

        self.empty_page = self._build_empty_page()
        self.stack.addWidget(self.empty_page)

        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(THUMBNAIL_CAPTURE_INTERVAL_MS)
        self.thumbnail_timer.timeout.connect(self.capture_thumbnail_if_possible)
        self.thumbnail_timer.start()

        self.media_poll_timer = QTimer(self)
        self.media_poll_timer.setInterval(900)
        self.media_poll_timer.timeout.connect(self._poll_media_state)

        self._emit_state()

    @property
    def state(self) -> TileState:
        return self._state

    def set_focus_flag(self, focused: bool) -> None:
        if self._state.is_focused == focused and self.property("focused") == focused:
            return
        self._state.is_focused = focused
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)
        self._emit_state()

    def set_split_button_active(self, active: bool, panel_visible: bool = False) -> None:
        self._split_button_active = active
        self._split_panel_visible = panel_visible
        if self._browser_container is None:
            return
        self._refresh_split_button_state()

    def set_toolbar_focus_mode(self, in_focus_mode: bool) -> None:
        self._toolbar_focus_mode = in_focus_mode
        if self._browser_container is None:
            return

        if in_focus_mode:
            self.focus_button.setText("Grille")
            self.focus_button.setToolTip("Retour à la grille")
            self.focus_button.setProperty("role", "nav")
            self.split_button.show()
        else:
            self.focus_button.setText("Focus")
            self.focus_button.setToolTip("Open this tile in focus mode")
            self.focus_button.setProperty("role", "accent")
            self.split_button.hide()
            self.swap_pages_button.hide()
            self._split_button_active = False
            self._split_panel_visible = False

        self.focus_button.style().unpolish(self.focus_button)
        self.focus_button.style().polish(self.focus_button)
        self._refresh_split_button_state()
        self._apply_navigation_state()

    def _refresh_split_button_state(self) -> None:
        if self._browser_container is None:
            return
        self.split_button.setText("Split")
        if not self._split_button_active:
            tooltip = "Aucun split permanent actif"
            role = "nav"
            self.swap_pages_button.hide()
        elif self._split_panel_visible:
            tooltip = "Masquer temporairement la page secondaire"
            role = "accent"
            self.swap_pages_button.setVisible(self._toolbar_focus_mode)
        else:
            tooltip = "Restaurer la page secondaire liee"
            role = "accent"
            self.swap_pages_button.setVisible(self._toolbar_focus_mode)
        self.split_button.setToolTip(tooltip)
        self.split_button.setProperty("role", role)
        self.split_button.style().unpolish(self.split_button)
        self.split_button.style().polish(self.split_button)

    def load_google_page(self) -> None:
        if self._navigate_from_text("https://www.google.com/"):
            self.request_browser_focus()

    def copy_displayed_url(self) -> None:
        if self._browser_container is None:
            return
        text = self.browser_url_edit.text().strip()
        if not text:
            self._show_toolbar_feedback("URL vide")
            return
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
        except Exception:
            self._show_toolbar_feedback("Presse-papiers indisponible")
            return
        self._show_toolbar_feedback("URL copiée")

    def request_browser_focus(self) -> None:
        if self._browser_container is None or self._web_view is None:
            return
        self._browser_focus_timer.start(0)

    def _apply_browser_focus(self) -> None:
        if self._browser_container is None or self._web_view is None:
            return
        if not self.isVisible() or not self._browser_container.isVisible() or not self._web_view.isVisible():
            return
        self.stack.setCurrentWidget(self._browser_container)
        self._web_view.setFocus(Qt.FocusReason.OtherFocusReason)
        self._web_view.activateWindow()

    def _show_toolbar_feedback(self, text: str) -> None:
        self.toolbar_feedback_label.setText(text)
        self.toolbar_feedback_label.show()
        self._toolbar_feedback_timer.stop()
        self._toolbar_feedback_timer.start(1200)

    def _clear_toolbar_feedback(self) -> None:
        self.toolbar_feedback_label.clear()
        self.toolbar_feedback_label.hide()

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addStretch(1)

        title = QLabel(f"Tile {self.tile_id + 1}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")

        prompt = QLabel("Enter a web address to load this tile.")
        prompt.setObjectName("TilePrompt")
        prompt.setWordWrap(True)
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_url_edit = QLineEdit()
        self.empty_url_edit.setPlaceholderText("https://example.com")
        self.empty_url_edit.setFixedHeight(URL_BAR_HEIGHT + 4)
        self.empty_url_edit.returnPressed.connect(self.load_from_empty_input)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        self.empty_load_button = QPushButton("Load")
        self.empty_load_button.setProperty("role", "accent")
        self.empty_load_button.clicked.connect(self.load_from_empty_input)

        self.empty_google_button = QPushButton("Google")
        self.empty_google_button.setProperty("role", "nav")
        self.empty_google_button.clicked.connect(self.load_google_page)

        buttons_row.addStretch(1)
        buttons_row.addWidget(self.empty_load_button)
        buttons_row.addWidget(self.empty_google_button)
        buttons_row.addStretch(1)

        self.empty_error_label = QLabel("")
        self.empty_error_label.setObjectName("ErrorBanner")
        self.empty_error_label.setWordWrap(True)
        self.empty_error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_error_label.hide()

        layout.addWidget(title)
        layout.addWidget(prompt)
        layout.addWidget(self.empty_url_edit)
        layout.addLayout(buttons_row)
        layout.addWidget(self.empty_error_label)
        layout.addStretch(1)
        return page

    def _configure_toolbar_button(
        self,
        button: QPushButton,
        tooltip: str,
        role: str,
        *,
        fixed_size: QSize | None = TOOLBAR_BUTTON_SIZE,
    ) -> None:
        button.setToolTip(tooltip)
        button.setProperty("compact", True)
        button.setProperty("role", role)
        if fixed_size is not None:
            button.setFixedSize(fixed_size)

    def _ensure_browser_page(self) -> None:
        if self._browser_container is not None:
            return

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("TileHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(4)

        compact_icon_size = QSize(28, 24)
        compact_text_height = 24

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(4)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)

        self.back_button = QPushButton("←")
        self.forward_button = QPushButton("→")
        self.reload_button = QPushButton("↻")
        self.zoom_out_button = QPushButton("-")
        self.zoom_in_button = QPushButton("+")
        self.memory_button = QPushButton("Sauver")
        self.focus_button = QPushButton("Focus")
        self.split_button = QPushButton("Split")
        self.swap_pages_button = QPushButton("⇄ Pages")
        self.grid_interchange_button = QPushButton("↔ Grille")
        self.close_button = QPushButton("Fermer")
        self.google_button = QPushButton("Google")
        self.copy_url_button = QPushButton("Copier URL")
        self.toolbar_feedback_label = QLabel("")
        self.toolbar_feedback_label.setObjectName("SecondaryText")
        self.toolbar_feedback_label.setStyleSheet(
            "padding: 2px 6px; border: 1px solid #34506f; border-radius: 8px; background: #182433; font-weight: 700;"
        )
        self.toolbar_feedback_label.hide()

        for button, tooltip, role in (
            (self.back_button, "Go back", "nav"),
            (self.forward_button, "Go forward", "nav"),
            (self.reload_button, "Reload", "nav"),
            (self.zoom_out_button, "Zoom out", "zoom"),
            (self.zoom_in_button, "Zoom in", "zoom"),
        ):
            self._configure_toolbar_button(button, tooltip, role, fixed_size=compact_icon_size)

        for button, tooltip, role, min_width in (
            (self.memory_button, "Save this tile", "memory", 72),
            (self.focus_button, "Open this tile in focus mode", "accent", 58),
            (self.split_button, "Split this focused page", "accent", 58),
            (self.swap_pages_button, "Interchanger les deux pages du split", "accent", 92),
            (self.grid_interchange_button, "Interchange de la grille", "nav", 92),
            (self.close_button, "Close this tile", "danger", 62),
            (self.google_button, "Ouvrir Google", "nav", 62),
            (self.copy_url_button, "Copier l'URL affichée", "nav", 86),
        ):
            self._configure_toolbar_button(button, tooltip, role, fixed_size=None)
            button.setMinimumHeight(compact_text_height)
            button.setMinimumWidth(min_width)

        self.browser_url_edit = QLineEdit()
        self.browser_url_edit.setObjectName("BrowserUrlEdit")
        self.browser_url_edit.setPlaceholderText("Page address")
        self.browser_url_edit.setFixedHeight(24)
        self.browser_url_edit.setMinimumWidth(90)
        self.browser_url_edit.returnPressed.connect(self.load_from_browser_input)

        row1.addWidget(self.back_button)
        row1.addWidget(self.forward_button)
        row1.addWidget(self.reload_button)
        row1.addWidget(self.browser_url_edit, 1)
        row1.addWidget(self.google_button)
        row1.addWidget(self.copy_url_button)
        row1.addWidget(self.toolbar_feedback_label)

        row2.addWidget(self.zoom_out_button)
        row2.addWidget(self.zoom_in_button)
        row2.addWidget(self.memory_button)
        row2.addWidget(self.focus_button)
        row2.addWidget(self.split_button)
        row2.addWidget(self.swap_pages_button)
        row2.addWidget(self.grid_interchange_button)
        row2.addWidget(self.close_button)

        header_layout.addLayout(row1)
        header_layout.addLayout(row2)

        self.error_banner = QLabel("")
        self.error_banner.setObjectName("ErrorBanner")
        self.error_banner.setContentsMargins(8, 4, 8, 4)
        self.error_banner.hide()

        self.media_banner = QLabel("")
        self.media_banner.setObjectName("SecondaryText")
        self.media_banner.setContentsMargins(8, 0, 8, 6)
        self.media_banner.setWordWrap(True)
        self.media_banner.hide()

        self._web_view = QWebEngineView()
        self._page = TileWebPage(self.profile, self._web_view)
        self._page.popup_url_ready.connect(self._load_qurl)
        self._page.fullScreenRequested.connect(self._handle_page_fullscreen_request)
        self._page.iconChanged.connect(self._on_icon_changed)
        self._web_view.setPage(self._page)

        self.back_button.clicked.connect(self._web_view.back)
        self.forward_button.clicked.connect(self._web_view.forward)
        self.reload_button.clicked.connect(self._web_view.reload)
        self.zoom_out_button.clicked.connect(lambda: self.adjust_zoom(-ZOOM_STEP))
        self.zoom_in_button.clicked.connect(lambda: self.adjust_zoom(ZOOM_STEP))
        self.memory_button.clicked.connect(lambda: self.memory_requested.emit(self.tile_id))
        self.focus_button.clicked.connect(self._on_focus_button_clicked)
        self.split_button.clicked.connect(self._on_split_button_clicked)
        self.swap_pages_button.clicked.connect(lambda: self.split_interchange_requested.emit(self.tile_id))
        self.grid_interchange_button.clicked.connect(lambda: self.grid_interchange_requested.emit(self.tile_id))
        self.google_button.clicked.connect(self.load_google_page)
        self.copy_url_button.clicked.connect(self.copy_displayed_url)
        self.close_button.clicked.connect(self.reset_to_empty)

        self._page.loadStarted.connect(self._on_load_started)
        self._page.loadFinished.connect(self._on_load_finished)
        self._page.loadProgress.connect(self._on_load_progress)
        self._page.urlChanged.connect(self._on_url_changed)
        self._page.titleChanged.connect(self._on_title_changed)

        container_layout.addWidget(header)
        container_layout.addWidget(self.error_banner)
        container_layout.addWidget(self.media_banner)
        container_layout.addWidget(self._web_view, 1)

        self._browser_container = container
        self.stack.addWidget(container)
        self.set_toolbar_focus_mode(self._toolbar_focus_mode)
        self._apply_navigation_state()
        self.web_page_ready.emit(self._page)

    def _on_focus_button_clicked(self) -> None:
        if self._toolbar_focus_mode:
            self.grid_requested.emit(self.tile_id)
        else:
            self.focus_requested.emit(self.tile_id)

    def _on_split_button_clicked(self) -> None:
        if self._toolbar_focus_mode and self._state.has_content:
            self.split_requested.emit(self.tile_id)

    def load_from_empty_input(self) -> None:
        if self._navigate_from_text(self.empty_url_edit.text()):
            self.request_browser_focus()

    def load_from_browser_input(self) -> None:
        if self._navigate_from_text(self.browser_url_edit.text()):
            self.request_browser_focus()

    def open_url_text(self, raw_text: str) -> None:
        self._navigate_from_text(raw_text)

    def current_page_url(self) -> str:
        return self._state.current_url.strip()

    def _qt_sleep(self, timeout_ms: int) -> None:
        if timeout_ms <= 0:
            return
        loop = QEventLoop()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    def _run_javascript_sync(self, script: str, timeout_ms: int = 4000) -> object:
        if self._page is None:
            raise RuntimeError("QWebEnginePage indisponible.")

        loop = QEventLoop()
        result: dict[str, object] = {"ready": False, "value": None}

        def on_result(value: object) -> None:
            result["ready"] = True
            result["value"] = value
            if loop.isRunning():
                loop.quit()

        try:
            self._page.runJavaScript(script, on_result)
        except RuntimeError as exc:
            raise RuntimeError("QWebEnginePage détruit ou indisponible.") from exc

        if not result["ready"]:
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()

        if not result["ready"]:
            raise TimeoutError("La requête JavaScript a expiré.")

        return result["value"]

    def _parse_json_result(self, raw_value: object) -> dict[str, object]:
        if isinstance(raw_value, dict):
            return raw_value
        text = str(raw_value or "").strip()
        if not text:
            raise ValueError("Résultat JavaScript vide.")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Résultat JavaScript inattendu.")
        return payload

    def read_chatgpt_assistant_state(self) -> dict[str, object]:
        if self._page is None or self._web_view is None or not self._state.has_content:
            return {
                "ok": False,
                "stage": "page",
                "error": "active web page unavailable",
            }

        current_url = self._state.current_url.strip()
        if not current_url.startswith("https://chatgpt.com/") and current_url != "https://chatgpt.com":
            return {
                "ok": False,
                "stage": "url",
                "error": "target URL must start with https://chatgpt.com/",
            }

        script = """
        (() => {
          try {
            const messages = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
            const last = messages.length > 0 ? messages[messages.length - 1] : null;
            const text = last ? String(last.innerText || last.textContent || "").trim() : "";
            return JSON.stringify({
              ok: true,
              assistant_count: messages.length,
              last_assistant_text: text.slice(0, 2000),
            });
          } catch (error) {
            return JSON.stringify({
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            });
          }
        })()
        """
        try:
            return self._parse_json_result(self._run_javascript_sync(script, timeout_ms=2000))
        except Exception as exc:
            return {
                "ok": False,
                "stage": "exception",
                "error": str(exc),
            }

    def wait_for_chatgpt_summary_confirmation(
        self,
        previous_assistant_count: int,
        *,
        timeout_ms: int = 90000,
    ) -> dict[str, object]:
        deadline = time.monotonic() + max(1.0, timeout_ms / 1000)
        last_text = ""
        while time.monotonic() < deadline:
            self._qt_sleep(1000)
            state = self.read_chatgpt_assistant_state()
            if not state.get("ok"):
                return state

            assistant_count = int(state.get("assistant_count", 0) or 0)
            last_text = str(state.get("last_assistant_text", "") or "")
            normalized = (
                last_text.lower()
                .replace("é", "e")
                .replace("è", "e")
                .replace("ê", "e")
                .replace("ç", "c")
            )
            received = "resume" in normalized and any(
                marker in normalized
                for marker in ("recu", "bien recu", "received", "reception")
            )
            if assistant_count > previous_assistant_count and received:
                return {
                    "ok": True,
                    "assistant_count": assistant_count,
                    "confirmation_text": last_text,
                }

        return {
            "ok": False,
            "stage": "confirmation",
            "error": "summary receipt confirmation not received",
            "last_assistant_text": last_text,
        }

    def _build_chatgpt_bridge_inspect_script(self, text: str, transmission_key: str) -> str:
        text_json = json.dumps(str(text))
        key_json = json.dumps(str(transmission_key))
        return f"""
        (() => {{
          try {{
            {self._web_text_js_helpers(text_json)}
            const ninoTransmissionKey = {key_json};
            const normalize = (value) => String(value || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\r\\n/g, "\\n")
              .trim();
            const sessionMatch = ninoTransmissionKey.match(/session_id=([^;]+)/);
            const turnMatch = ninoTransmissionKey.match(/turn_id=([^;]+)/);
            const sessionId = sessionMatch ? sessionMatch[1] : "";
            const turnId = turnMatch ? turnMatch[1] : "";
            const hasTransmissionIdentity = (value) => {{
              const text = normalize(value);
              if (text.includes(ninoTransmissionKey)) {{
                return true;
              }}
              return !!sessionId && !!turnId && text.includes(sessionId) && text.includes(turnId);
            }};
            const editor = document.querySelector('#prompt-textarea[contenteditable="true"]');
            const textarea = document.querySelector('textarea[name="prompt-textarea"]');
            const field = editor || textarea || null;
            const editorText = field
              ? normalize(field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement
                  ? field.value
                  : (field.innerText || field.textContent || ""))
              : "";
            const sendButton = document.querySelector('button[data-testid="send-button"]');
            const stopButton = document.querySelector('button[data-testid="stop-button"]');
            const sendAvailable = !!sendButton
              && ninoVisible(sendButton)
              && !sendButton.disabled
              && sendButton.getAttribute("aria-disabled") !== "true";
            const busy = !!stopButton && ninoVisible(stopButton);
            const userMessages = Array.from(document.querySelectorAll('[data-message-author-role="user"]'));
            const matches = userMessages
              .map((element, index) => {{
                const text = normalize(element.innerText || element.textContent || "");
                return {{ index, text }};
              }})
              .filter((item) => hasTransmissionIdentity(item.text));
            const latest = matches.length > 0 ? matches[matches.length - 1] : null;
            return JSON.stringify({{
              ok: true,
              field_found: !!field,
              editor_text_present: editorText.length > 0,
              editor_contains_key: hasTransmissionIdentity(editorText),
              editor_contains_payload: editorText === normalize(ninoText),
              send_available: sendAvailable,
              chatgpt_busy: busy || (!!sendButton && !sendAvailable),
              user_message_found: !!latest,
              user_message_index: latest ? latest.index : null,
              user_message_length: latest ? latest.text.length : 0,
              user_message_count: userMessages.length,
              key: ninoTransmissionKey,
            }});
          }} catch (error) {{
            return JSON.stringify({{
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            }});
          }}
        }})()
        """

    def inspect_chatgpt_bridge_message(self, text: str, transmission_key: str) -> dict[str, object]:
        if self._page is None or self._web_view is None or not self._state.has_content:
            return {
                "ok": False,
                "stage": "page",
                "error": "active web page unavailable",
            }

        current_url = self._state.current_url.strip()
        if not current_url.startswith("https://chatgpt.com/") and current_url != "https://chatgpt.com":
            return {
                "ok": False,
                "stage": "url",
                "error": "target URL must start with https://chatgpt.com/",
            }

        try:
            return self._parse_json_result(
                self._run_javascript_sync(
                    self._build_chatgpt_bridge_inspect_script(text, transmission_key),
                    timeout_ms=2000,
                )
            )
        except Exception as exc:
            return {
                "ok": False,
                "stage": "exception",
                "error": str(exc),
            }

    def _build_chatgpt_bridge_submit_existing_script(self, text: str, transmission_key: str) -> str:
        text_json = json.dumps(str(text))
        key_json = json.dumps(str(transmission_key))
        return f"""
        (() => {{
          try {{
            {self._web_text_js_helpers(text_json)}
            const ninoTransmissionKey = {key_json};
            const normalize = (value) => String(value || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\r\\n/g, "\\n")
              .trim();
            const sessionMatch = ninoTransmissionKey.match(/session_id=([^;]+)/);
            const turnMatch = ninoTransmissionKey.match(/turn_id=([^;]+)/);
            const sessionId = sessionMatch ? sessionMatch[1] : "";
            const turnId = turnMatch ? turnMatch[1] : "";
            const hasTransmissionIdentity = (value) => {{
              const text = normalize(value);
              if (text.includes(ninoTransmissionKey)) {{
                return true;
              }}
              return !!sessionId && !!turnId && text.includes(sessionId) && text.includes(turnId);
            }};
            const editor = document.querySelector('#prompt-textarea[contenteditable="true"]');
            const textarea = document.querySelector('textarea[name="prompt-textarea"]');
            const field = editor || textarea || null;
            if (!field) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: "no visible editable field",
                field_found: false,
              }});
            }}
            const editorText = field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement
              ? String(field.value || "")
              : String(field.innerText || field.textContent || "");
            if (!hasTransmissionIdentity(editorText)) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: "existing draft does not match transmission identity",
                field_found: true,
              }});
            }}
            const resolved = ninoResolveSendButton();
            if (!resolved.button) {{
              return JSON.stringify({{
                ok: false,
                stage: resolved.stage || "send",
                error: resolved.error || "send button not found",
                field_found: true,
              }});
            }}
            if (resolved.button.disabled || resolved.button.getAttribute("aria-disabled") === "true") {{
              return JSON.stringify({{
                ok: false,
                stage: "send",
                error: "send button disabled",
                field_found: true,
              }});
            }}
            resolved.button.click();
            return JSON.stringify({{
              ok: true,
              field_found: true,
              submitted: true,
            }});
          }} catch (error) {{
            return JSON.stringify({{
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            }});
          }}
        }})()
        """

    def send_chatgpt_bridge_message(
        self,
        text: str,
        transmission_key: str,
        *,
        max_attempts: int = 5,
        retry_delay_ms: int = 30000,
    ) -> dict[str, object]:
        attempts: list[dict[str, object]] = []
        max_attempts = max(1, int(max_attempts))
        retry_delay_ms = max(0, int(retry_delay_ms))
        inserted_during_run = False
        send_attempted_during_run = False

        for attempt_number in range(1, max_attempts + 1):
            state = self.inspect_chatgpt_bridge_message(text, transmission_key)
            attempt: dict[str, object] = {
                "attempt": attempt_number,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "field_found": bool(state.get("field_found", False)),
                "text_present_in_field": bool(state.get("editor_contains_key", False)),
                "send_available": bool(state.get("send_available", False)),
                "chatgpt_busy": bool(state.get("chatgpt_busy", False)),
                "send_action_executed": False,
                "message_found": bool(state.get("user_message_found", False)),
                "state": "INSPECTED",
            }

            if not state.get("ok"):
                attempt["state"] = "INSPECTION_FAILED"
                attempt["error"] = str(state.get("error", "inspection failed"))
                attempts.append(attempt)
                if attempt_number < max_attempts:
                    attempt["next_retry_ms"] = retry_delay_ms
                    self._qt_sleep(retry_delay_ms)
                    continue
                return {
                    "ok": False,
                    "status": "FAILED_AFTER_5_ATTEMPTS",
                    "attempts": attempts,
                    "error": attempt["error"],
                }

            if state.get("user_message_found") and not state.get("editor_contains_key"):
                final_status = "SENT_CONFIRMED" if send_attempted_during_run else "DUPLICATE_SKIPPED"
                attempt["state"] = final_status
                attempts.append(attempt)
                return {
                    "ok": True,
                    "status": final_status,
                    "attempts": attempts,
                    "message_found": True,
                    "submitted": send_attempted_during_run,
                }

            editor_has_other_text = bool(state.get("editor_text_present")) and not bool(state.get("editor_contains_key"))
            if editor_has_other_text:
                attempt["state"] = "FIELD_CONTAINS_OTHER_TEXT"
                attempt["error"] = "composer contains unrelated text"
                attempts.append(attempt)
                return {
                    "ok": False,
                    "status": "FAILED_AFTER_5_ATTEMPTS",
                    "attempts": attempts,
                    "error": "composer contains unrelated text",
                }

            if not state.get("editor_contains_key"):
                prepare_result = self._parse_json_result(
                    self._run_javascript_sync(
                        self._build_web_text_prepare_script(text, one_shot=False),
                        timeout_ms=2000,
                    )
                )
                if not prepare_result.get("ok"):
                    attempt["state"] = "DRAFT_INSERT_FAILED"
                    attempt["error"] = str(prepare_result.get("error", "draft insertion failed"))
                    attempts.append(attempt)
                    if attempt_number < max_attempts:
                        attempt["next_retry_ms"] = retry_delay_ms
                        self._qt_sleep(retry_delay_ms)
                        continue
                    return {
                        "ok": False,
                        "status": "FAILED_AFTER_5_ATTEMPTS",
                        "attempts": attempts,
                        "error": attempt["error"],
                    }
                inserted_during_run = True
                attempt["state"] = "DRAFT_INSERTED"

            state = self.inspect_chatgpt_bridge_message(text, transmission_key)
            attempt["field_found"] = bool(state.get("field_found", False))
            attempt["text_present_in_field"] = bool(state.get("editor_contains_key", False))
            attempt["send_available"] = bool(state.get("send_available", False))
            attempt["chatgpt_busy"] = bool(state.get("chatgpt_busy", False))
            attempt["message_found"] = bool(state.get("user_message_found", False))

            if state.get("user_message_found") and not state.get("editor_contains_key"):
                attempt["state"] = "SENT_CONFIRMED"
                attempts.append(attempt)
                return {
                    "ok": True,
                    "status": "SENT_CONFIRMED",
                    "attempts": attempts,
                    "message_found": True,
                    "submitted": send_attempted_during_run,
                }

            if state.get("send_available"):
                submit_script = (
                    self._build_web_text_submit_script(text, one_shot=False)
                    if state.get("editor_contains_payload")
                    else self._build_chatgpt_bridge_submit_existing_script(text, transmission_key)
                )
                submit_result = self._parse_json_result(
                    self._run_javascript_sync(
                        submit_script,
                        timeout_ms=2000,
                    )
                )
                send_attempted_during_run = bool(submit_result.get("ok"))
                attempt["send_action_executed"] = send_attempted_during_run
                attempt["state"] = "SEND_ATTEMPTED" if send_attempted_during_run else "WAITING_CHATGPT_BUSY"
                if not submit_result.get("ok"):
                    attempt["error"] = str(submit_result.get("error", "send action failed"))
            else:
                attempt["state"] = "WAITING_CHATGPT_BUSY" if state.get("chatgpt_busy") else "DRAFT_INSERTED"

            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                self._qt_sleep(250)
                confirm_state = self.inspect_chatgpt_bridge_message(text, transmission_key)
                attempt["message_found"] = bool(confirm_state.get("user_message_found", False))
                attempt["text_present_in_field"] = bool(confirm_state.get("editor_contains_key", False))
                attempt["send_available"] = bool(confirm_state.get("send_available", False))
                attempt["chatgpt_busy"] = bool(confirm_state.get("chatgpt_busy", False))
                if confirm_state.get("user_message_found") and not confirm_state.get("editor_contains_key"):
                    attempt["state"] = "SENT_CONFIRMED"
                    attempts.append(attempt)
                    return {
                        "ok": True,
                        "status": "SENT_CONFIRMED",
                        "attempts": attempts,
                        "message_found": True,
                        "submitted": send_attempted_during_run,
                    }

            if attempt_number < max_attempts:
                attempt["next_retry_ms"] = retry_delay_ms
                attempt["state"] = "RETRY_SCHEDULED"
                attempts.append(attempt)
                self._qt_sleep(retry_delay_ms)
                continue

            attempt["state"] = "FAILED_AFTER_5_ATTEMPTS"
            attempts.append(attempt)
            return {
                "ok": False,
                "status": "FAILED_AFTER_5_ATTEMPTS",
                "attempts": attempts,
                "message_found": False,
                "submitted": send_attempted_during_run,
                "draft_inserted": inserted_during_run,
            }

        return {
            "ok": False,
            "status": "FAILED_AFTER_5_ATTEMPTS",
            "attempts": attempts,
            "message_found": False,
            "submitted": send_attempted_during_run,
            "draft_inserted": inserted_during_run,
        }

    def _web_text_js_helpers(self, text_json: str) -> str:
        return f"""
          const ninoText = {text_json};
          const ninoVisible = (element) => {{
            if (!(element instanceof HTMLElement)) {{
              return false;
            }}
            const style = window.getComputedStyle(element);
            if (!style || style.display === "none" || style.visibility === "hidden") {{
              return false;
            }}
            const rect = element.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {{
              return false;
            }}
            if (element.hasAttribute("hidden") || element.getAttribute("aria-hidden") === "true") {{
              return false;
            }}
            return true;
          }};
          const ninoUnique = (items) => {{
            const seen = new Set();
            const unique = [];
            for (const item of items) {{
              if (!item || seen.has(item)) {{
                continue;
              }}
              seen.add(item);
              unique.push(item);
            }}
            return unique;
          }};
          const ninoCollectEditableFields = () => {{
            const found = [];
            const add = (element, force = false) => {{
              if (element && (force || ninoVisible(element)) && !element.disabled && !element.readOnly) {{
                found.push(element);
              }}
            }};
            const promptEditor = document.querySelector('#prompt-textarea[contenteditable="true"]');
            if (promptEditor) {{
              add(promptEditor);
              return ninoUnique(found);
            }}
            const promptTextarea = document.querySelector('textarea[name="prompt-textarea"]');
            if (promptTextarea) {{
              add(promptTextarea, true);
              return ninoUnique(found);
            }}
            document.querySelectorAll("textarea").forEach(add);
            document.querySelectorAll('[contenteditable="true"]').forEach(add);
            return ninoUnique(found);
          }};
          const ninoSetTextareaText = (target, text) => {{
            const prototype = target instanceof HTMLInputElement
              ? HTMLInputElement.prototype
              : HTMLTextAreaElement.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(prototype, "value")
              || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
              || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
            if (!descriptor || typeof descriptor.set !== "function") {{
              return {{ ok: false, stage: "field", error: "missing value setter" }};
            }}
            target.focus({{ preventScroll: true }});
            if (typeof target.select === "function") {{
              try {{
                target.select();
              }} catch (_error) {{
              }}
            }}
            descriptor.set.call(target, "");
            target.dispatchEvent(new InputEvent("beforeinput", {{
              bubbles: true,
              composed: true,
              cancelable: true,
              inputType: "deleteContentBackward",
              data: "",
            }}));
            target.dispatchEvent(new InputEvent("input", {{
              bubbles: true,
              composed: true,
              inputType: "deleteContentBackward",
              data: "",
            }}));
            descriptor.set.call(target, text);
            target.dispatchEvent(new InputEvent("beforeinput", {{
              bubbles: true,
              composed: true,
              cancelable: true,
              inputType: "insertText",
              data: text,
            }}));
            target.dispatchEvent(new InputEvent("input", {{
              bubbles: true,
              composed: true,
              inputType: "insertText",
              data: text,
            }}));
            target.dispatchEvent(new Event("change", {{ bubbles: true }}));
            if (String(target.value) !== text) {{
              return {{ ok: false, stage: "field", error: "textarea value mismatch" }};
            }}
            return {{ ok: true }};
          }};
          const ninoSetEditableText = (target, text) => {{
            target.focus({{ preventScroll: true }});
            const selection = window.getSelection();
            if (!selection) {{
              return {{ ok: false, stage: "field", error: "selection unavailable" }};
            }}
            const range = document.createRange();
            range.selectNodeContents(target);
            selection.removeAllRanges();
            selection.addRange(range);
            try {{
              document.execCommand("delete");
            }} catch (_error) {{
            }}
            const promptTextarea = document.querySelector('textarea[name="prompt-textarea"]');
            if (promptTextarea && ninoText.length > 0) {{
              const textareaDescriptor = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
                || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
              if (!textareaDescriptor || typeof textareaDescriptor.set !== "function") {{
                return {{ ok: false, stage: "field", error: "missing textarea setter" }};
              }}
              const primeText = ninoText.slice(0, 1);
              textareaDescriptor.set.call(promptTextarea, primeText);
              promptTextarea.dispatchEvent(new InputEvent("beforeinput", {{
                bubbles: true,
                composed: true,
                cancelable: true,
                inputType: "insertText",
                data: primeText,
              }}));
              promptTextarea.dispatchEvent(new InputEvent("input", {{
                bubbles: true,
                composed: true,
                inputType: "insertText",
                data: primeText,
              }}));
            }}
            const inserted = document.execCommand("insertText", false, text);
            target.focus({{ preventScroll: true }});
            const value = (target.innerText || target.textContent || "").replace(/\\u00a0/g, " ").trim();
            if (!inserted || value !== ninoText) {{
              return {{ ok: false, stage: "field", error: "contenteditable text mismatch", field_found: true, text_inserted: value }};
            }}
            return {{ ok: true }};
          }};
          const ninoResolveSendButton = () => {{
            const candidates = Array.from(document.querySelectorAll("button, [role='button']"))
              .filter((element) => ninoVisible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true");
            const byTestId = candidates.filter((element) =>
              String(element.getAttribute("data-testid") || "").trim().toLowerCase() === "send-button"
            );
            if (byTestId.length === 1) {{
              return {{ button: byTestId[0] }};
            }}
            if (byTestId.length > 1) {{
              return {{ error: `ambiguous send buttons (${{byTestId.length}})`, stage: "send" }};
            }}
            const byLabel = candidates.filter((element) => {{
              const label = [
                element.getAttribute("aria-label") || "",
                element.getAttribute("title") || "",
                element.textContent || "",
              ].join(" ").toLowerCase();
              return /\\b(send|envoyer|submit|soumettre)\\b/i.test(label);
            }});
            if (byLabel.length === 1) {{
              return {{ button: byLabel[0] }};
            }}
            if (byLabel.length > 1) {{
              return {{ error: `ambiguous send buttons (${{byLabel.length}})`, stage: "send" }};
            }}
            return {{ error: "send button not found", stage: "send" }};
          }};
        """

    def _build_web_text_prepare_script(self, text: str, one_shot: bool) -> str:
        text_json = json.dumps(str(text))
        one_shot_json = "true" if one_shot else "false"
        return f"""
        (() => {{
          try {{
            {self._web_text_js_helpers(text_json)}
            if ({one_shot_json} && window.__ninoTypeWebTextOneShotUsed) {{
                return JSON.stringify({{
                ok: false,
                stage: "guard",
                error: "type_web_text one-shot already used",
              }});
            }}
            const promptMessages = document.querySelectorAll('[data-message-author-role]');
            if (promptMessages.length === 0) {{
              return JSON.stringify({{
                ok: false,
                stage: "thread",
                error: "conversation not ready",
                field_found: false,
              }});
            }}
            const editableFields = ninoCollectEditableFields();
            if (editableFields.length === 0) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: "no visible editable field",
                field_found: false,
              }});
            }}
            if (editableFields.length > 1) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: `ambiguous editable fields (${{editableFields.length}})`,
                field_found: false,
              }});
            }}
            const target = editableFields[0];
            const result = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement
              ? ninoSetTextareaText(target, ninoText)
              : ninoSetEditableText(target, ninoText);
            if (!result.ok) {{
              return JSON.stringify({{
                ...result,
                field_found: true,
              }});
            }}
            return JSON.stringify({{
              ok: true,
              field_found: true,
              text_inserted: ninoText,
              submitted: false,
            }});
          }} catch (error) {{
            return JSON.stringify({{
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            }});
          }}
        }})()
        """

    def _build_web_text_verify_script(self, text: str) -> str:
        text_json = json.dumps(str(text))
        return f"""
        (() => {{
          try {{
            {self._web_text_js_helpers(text_json)}
            const editableFields = ninoCollectEditableFields();
            if (editableFields.length === 0) {{
              return JSON.stringify({{
                ok: false,
                stage: "verify",
                error: "no visible editable field",
                field_found: false,
              }});
            }}
            if (editableFields.length > 1) {{
              return JSON.stringify({{
                ok: false,
                stage: "verify",
                error: `ambiguous editable fields (${{editableFields.length}})`,
                field_found: false,
              }});
            }}
            const target = editableFields[0];
            const value = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement
              ? String(target.value || "")
              : (target.innerText || target.textContent || "").replace(/\\u00a0/g, " ").trim();
            if (value !== ninoText) {{
              return JSON.stringify({{
                ok: false,
                stage: "verify",
                error: "contenteditable text mismatch",
                field_found: true,
                text_inserted: value,
              }});
            }}
            return JSON.stringify({{
              ok: true,
              field_found: true,
              text_inserted: ninoText,
            }});
          }} catch (error) {{
            return JSON.stringify({{
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            }});
          }}
        }})()
        """

    def _build_web_text_submit_script(self, text: str, one_shot: bool) -> str:
        text_json = json.dumps(str(text))
        one_shot_json = "true" if one_shot else "false"
        return f"""
        (() => {{
          try {{
            {self._web_text_js_helpers(text_json)}
            const editableFields = ninoCollectEditableFields();
            if (editableFields.length === 0) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: "no visible editable field",
                field_found: false,
              }});
            }}
            if (editableFields.length > 1) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: `ambiguous editable fields (${{editableFields.length}})`,
                field_found: false,
              }});
            }}
            const target = editableFields[0];
            const value = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement
              ? String(target.value || "")
              : (target.innerText || target.textContent || "").replace(/\\u00a0/g, " ").trim();
            if (value !== ninoText) {{
              return JSON.stringify({{
                ok: false,
                stage: "field",
                error: "inserted text mismatch",
                field_found: true,
                text_inserted: value,
              }});
            }}
            const resolved = ninoResolveSendButton();
            if (!resolved.button) {{
              return JSON.stringify({{
                ok: false,
                stage: resolved.stage || "send",
                error: resolved.error || "send button not found",
                field_found: true,
                text_inserted: ninoText,
              }});
            }}
            if (resolved.button.disabled || resolved.button.getAttribute("aria-disabled") === "true") {{
              return JSON.stringify({{
                ok: false,
                stage: "send",
                error: "send button disabled",
                field_found: true,
                text_inserted: ninoText,
              }});
            }}
            try {{
              resolved.button.click();
            }} catch (error) {{
              return JSON.stringify({{
                ok: false,
                stage: "send",
                error: String(error && error.message ? error.message : error),
                field_found: true,
                text_inserted: ninoText,
              }});
            }}
            if ({one_shot_json}) {{
              window.__ninoTypeWebTextOneShotUsed = true;
            }}
            return JSON.stringify({{
              ok: true,
              field_found: true,
              text_inserted: ninoText,
              submitted: true,
            }});
          }} catch (error) {{
            return JSON.stringify({{
              ok: false,
              stage: "exception",
              error: String(error && error.message ? error.message : error),
            }});
          }}
        }})()
        """

    def send_text_to_active_web_page(
        self,
        text: str,
        *,
        submit: bool,
        one_shot: bool = True,
    ) -> dict[str, object]:
        if self._page is None or self._web_view is None or not self._state.has_content:
            return {
                "ok": False,
                "stage": "page",
                "error": "active web page unavailable",
            }

        current_url = self._state.current_url.strip()
        if not current_url.startswith("https://chatgpt.com/") and current_url != "https://chatgpt.com":
            return {
                "ok": False,
                "stage": "url",
                "error": "target URL must start with https://chatgpt.com/",
            }

        if one_shot and self._web_text_one_shot_used:
            return {
                "ok": False,
                "stage": "guard",
                "error": "type_web_text one-shot already used",
            }

        if self._web_text_submission_busy:
            return {
                "ok": False,
                "stage": "busy",
                "error": "another web text submission is already running",
            }

        self._web_text_submission_busy = True
        try:
            if self._browser_container is not None:
                self.stack.setCurrentWidget(self._browser_container)
            self._web_view.show()
            self._web_view.raise_()
            self._web_view.setFocus(Qt.FocusReason.OtherFocusReason)
            self._web_view.activateWindow()
            self._qt_sleep(50)

            prepare_script = self._build_web_text_prepare_script(text, one_shot=one_shot)
            prepare_result: dict[str, object] | None = None
            deadline = time.monotonic() + 8.0
            while True:
                raw_result = self._run_javascript_sync(prepare_script, timeout_ms=1500)
                prepare_result = self._parse_json_result(raw_result)
                if prepare_result.get("ok"):
                    break
                stage = str(prepare_result.get("stage", "") or "")
                if stage not in {"field", "thread"}:
                    return prepare_result
                if time.monotonic() >= deadline:
                    return prepare_result
                self._qt_sleep(150)

            verify_script = self._build_web_text_verify_script(text)
            verify_result: dict[str, object] | None = None
            deadline = time.monotonic() + 6.0
            while True:
                raw_result = self._run_javascript_sync(verify_script, timeout_ms=1500)
                verify_result = self._parse_json_result(raw_result)
                if verify_result.get("ok"):
                    break
                stage = str(verify_result.get("stage", "") or "")
                if stage not in {"verify"}:
                    return verify_result
                if time.monotonic() >= deadline:
                    return verify_result
                self._qt_sleep(150)

            if not submit:
                return {
                    "ok": True,
                    "field_found": True,
                    "text_inserted": str(text),
                    "submitted": False,
                }

            self._web_view.setFocus(Qt.FocusReason.OtherFocusReason)
            self._qt_sleep(50)
            focus_widget = QApplication.focusWidget()
            if focus_widget is None:
                return {
                    "ok": False,
                    "stage": "send",
                    "error": "focus widget unavailable",
                    "field_found": True,
                    "text_inserted": str(text),
                }

            try:
                QTest.keyClick(focus_widget, Qt.Key.Key_Return)
            except Exception as exc:
                return {
                    "ok": False,
                    "stage": "send",
                    "error": str(exc),
                    "field_found": True,
                    "text_inserted": str(text),
                }

            text_json = json.dumps(str(text))
            check_script = f"""
            (() => {{
              try {{
                {self._web_text_js_helpers(text_json)}
                const promptMessages = document.querySelectorAll('[data-message-author-role]');
                const editor = document.querySelector('#prompt-textarea[contenteditable="true"]');
                const sendButton = document.querySelector('button[data-testid="send-button"]');
                const editorText = editor ? (editor.innerText || editor.textContent || '').replace(/\\u00a0/g, ' ').trim() : '';
                return JSON.stringify({{
                  ok: true,
                  field_found: true,
                  text_inserted: ninoText,
                  editor_text: editorText,
                  send_disabled: sendButton ? !!sendButton.disabled : null,
                  message_count: promptMessages.length,
                }});
              }} catch (error) {{
                return JSON.stringify({{
                  ok: false,
                  stage: "exception",
                  error: String(error && error.message ? error.message : error),
                }});
              }}
            }})()
            """
            initial_message_count = int(prepare_result.get("message_count", 0)) if isinstance(prepare_result, dict) else 0
            deadline = time.monotonic() + 6.0
            while True:
                self._qt_sleep(150)
                raw_result = self._run_javascript_sync(check_script, timeout_ms=1500)
                submit_result = self._parse_json_result(raw_result)
                editor_text = str(submit_result.get("editor_text", "") or "")
                send_disabled = submit_result.get("send_disabled")
                message_count = int(submit_result.get("message_count", 0) or 0)
                if editor_text == "" and send_disabled is True:
                    if one_shot:
                        self._web_text_one_shot_used = True
                    return {
                        "ok": True,
                        "field_found": True,
                        "text_inserted": str(text),
                        "submitted": True,
                        "message_count": message_count,
                    }
                if message_count > initial_message_count:
                    if one_shot:
                        self._web_text_one_shot_used = True
                    return {
                        "ok": True,
                        "field_found": True,
                        "text_inserted": str(text),
                        "submitted": True,
                        "message_count": message_count,
                    }
                if time.monotonic() >= deadline:
                    return {
                        "ok": False,
                        "stage": "send",
                        "error": "submission not confirmed",
                        "field_found": True,
                        "text_inserted": str(text),
                        "editor_text": editor_text,
                        "send_disabled": send_disabled,
                        "message_count": message_count,
                    }
        finally:
            self._web_text_submission_busy = False

    def reload_current(self) -> None:
        if self._web_view is not None and self._state.has_content:
            self._web_view.reload()

    def restore_from_session(self, current_url: str, zoom_factor: float) -> None:
        clean_url = current_url.strip()
        if not clean_url:
            self.reset_to_empty()
            return
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, round(float(zoom_factor), 2)))
        self._state.zoom_factor = zoom
        self._ensure_browser_page()
        self.browser_url_edit.setText(clean_url)
        self.empty_url_edit.setText(clean_url)
        self._load_qurl(QUrl(clean_url))
        if self._web_view is not None:
            self._web_view.setZoomFactor(zoom)
        self._apply_navigation_state()

    def _navigate_from_text(self, raw_text: str) -> bool:
        result = normalize_user_url(raw_text)
        if not result.ok:
            self.show_input_error(result.error)
            return False
        self.clear_errors()
        self._ensure_browser_page()
        self.stack.setCurrentWidget(self._browser_container)
        self.browser_url_edit.setText(result.normalized_text)
        self.empty_url_edit.setText(result.normalized_text)
        self._state.has_content = True
        self._state.error_message = ""
        self._state.status = TileVisualStatus.LOADING
        self._load_qurl(result.url)
        return True

    def _load_qurl(self, qurl: QUrl) -> None:
        if self._web_view is None:
            self._ensure_browser_page()
        self.stack.setCurrentWidget(self._browser_container)
        self._state.has_content = True
        self._state.status = TileVisualStatus.LOADING
        self._web_view.setZoomFactor(self._state.zoom_factor)
        self._web_view.load(qurl)
        self._apply_navigation_state()
        self._emit_state()

    def show_input_error(self, message: str) -> None:
        if self.stack.currentWidget() == self.empty_page:
            self.empty_error_label.setText(message)
            self.empty_error_label.show()
        else:
            self.error_banner.setText(message)
            self.error_banner.show()
        self._state.error_message = message
        self._state.status = TileVisualStatus.ERROR
        self._emit_state()

    def clear_errors(self) -> None:
        self.empty_error_label.hide()
        if self._browser_container is not None:
            self.error_banner.hide()
        self._state.error_message = ""

    def adjust_zoom(self, delta: float) -> None:
        if self._web_view is None:
            return
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, round(self._state.zoom_factor + delta, 2)))
        self._state.zoom_factor = new_zoom
        self._web_view.setZoomFactor(new_zoom)
        self.queue_thumbnail_capture()
        self._emit_state()

    def reset_to_empty(self) -> None:
        if self._browser_container is not None:
            self._stop_media_capture()
            self.web_page_released.emit()
            self.stack.removeWidget(self._browser_container)
            self._browser_container.deleteLater()
            self._browser_container = None
            self._web_view = None
            self._page = None
        self._stop_media_probe()
        self._set_media_status(False, False)
        self.clear_media_message()
        self.empty_url_edit.clear()
        self.empty_error_label.hide()
        self._web_text_submission_busy = False
        self._web_text_one_shot_used = False
        self._state.current_url = ""
        self._state.title = ""
        self._state.domain = ""
        self._state.has_content = False
        self._state.is_loading = False
        self._state.error_message = ""
        self._state.zoom_factor = DEFAULT_ZOOM
        self._state.status = TileVisualStatus.EMPTY
        self._state.site_icon = None
        self.stack.setCurrentWidget(self.empty_page)
        self.queue_thumbnail_capture()
        self._emit_state()

    def _on_load_started(self) -> None:
        self._stop_media_capture()
        self.clear_errors()
        self._media_probe_installed = False
        self.clear_media_message()
        self._set_media_status(False, False)
        self._state.has_content = True
        self._state.is_loading = True
        self._state.status = TileVisualStatus.LOADING
        self._apply_navigation_state()
        self._emit_state()

    def _on_load_progress(self, _progress: int) -> None:
        self._state.is_loading = True
        self._state.status = TileVisualStatus.LOADING
        self._emit_state()

    def _on_load_finished(self, ok: bool) -> None:
        self._state.is_loading = False
        if ok:
            self._state.status = TileVisualStatus.READY
            self._state.error_message = ""
            self.clear_errors()
            self._install_media_probe()
        else:
            self._state.status = TileVisualStatus.ERROR
            self._state.error_message = "The page failed to load."
            self.error_banner.setText(self._state.error_message)
            self.error_banner.show()
            self._stop_media_capture()
            self._stop_media_probe()
        self._apply_navigation_state()
        self.queue_thumbnail_capture()
        self._emit_state()

    def _on_url_changed(self, qurl: QUrl) -> None:
        value = qurl.toString()
        self._state.current_url = value
        self._state.domain = qurl.host()
        self.empty_url_edit.setText(value)
        if self._browser_container is not None:
            self.browser_url_edit.setText(value)
        self._apply_navigation_state()
        self._emit_state()

    def _on_title_changed(self, title: str) -> None:
        self._state.title = title.strip()
        self.queue_thumbnail_capture()
        self._emit_state()

    def _on_icon_changed(self, icon: QIcon) -> None:
        if icon.isNull():
            self._state.site_icon = None
        else:
            self._state.site_icon = icon.pixmap(QSize(16, 16))
        self.queue_thumbnail_capture()
        self._emit_state()

    def _apply_navigation_state(self) -> None:
        if self._browser_container is None or self._web_view is None:
            return
        history = self._web_view.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())
        self.reload_button.setEnabled(self._state.has_content)
        self.zoom_out_button.setEnabled(self._state.has_content)
        self.zoom_in_button.setEnabled(self._state.has_content)
        self.memory_button.setEnabled(self._state.has_content)
        self.focus_button.setEnabled(self._state.has_content)
        self.split_button.setEnabled(
            self._state.has_content and self._toolbar_focus_mode and self._split_button_active
        )
        self.close_button.setEnabled(self._state.has_content)

    def _handle_page_fullscreen_request(self, request) -> None:
        request.reject()

    def _stop_media_capture(self, timeout_ms: int = 750) -> None:
        if self._page is None:
            return

        loop = QEventLoop()
        finished = False

        def finish(_result: object | None = None) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            loop.quit()

        try:
            self._page.runJavaScript(
                """
                (() => {
                  const state = window.__ninoMediaState;
                  if (state && typeof state.stopAll === "function") {
                    state.stopAll();
                  }
                })();
                """,
                finish,
            )
        except RuntimeError:
            return

        QTimer.singleShot(timeout_ms, finish)
        if not finished:
            loop.exec()

    def show_media_message(self, message: str) -> None:
        text = message.strip()
        if not text:
            self.clear_media_message()
            return
        self.media_banner.setText(text)
        self.media_banner.show()

    def clear_media_message(self) -> None:
        if self._browser_container is None:
            return
        self.media_banner.clear()
        self.media_banner.hide()

    def _install_media_probe(self) -> None:
        if self._page is None:
            return
        script = """
        (() => {
          if (window.__ninoMediaBridgeInstalled) {
            return;
          }
          window.__ninoMediaBridgeInstalled = true;
          const state = {
            audioActive: false,
            videoActive: false,
            activeTrackCount: 0,
            lastErrorName: "",
            lastErrorMessage: "",
          };
          const activeTracks = new Map();

          function syncState() {
            const tracks = Array.from(activeTracks.values()).filter((track) => track && track.readyState !== "ended");
            state.activeTrackCount = tracks.length;
            state.audioActive = tracks.some((track) => track.kind === "audio");
            state.videoActive = tracks.some((track) => track.kind === "video");
            window.__ninoMediaState = state;
          }

          function rememberTrack(track) {
            if (!track) {
              return;
            }
            const key = `${track.kind}:${track.id}:${Math.random().toString(36).slice(2)}`;
            activeTracks.set(key, track);
            if (!track.__ninoWrappedStop) {
              const originalStop = track.stop.bind(track);
              track.stop = function() {
                try {
                  return originalStop();
                } finally {
                  activeTracks.delete(key);
                  syncState();
                }
              };
              track.__ninoWrappedStop = true;
            }
            track.addEventListener("ended", () => {
              activeTracks.delete(key);
              syncState();
            });
            syncState();
          }

          function rememberStream(stream) {
            for (const track of stream.getTracks()) {
              rememberTrack(track);
            }
            syncState();
            return stream;
          }

          if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = async function(constraints) {
              try {
                const stream = await originalGetUserMedia(constraints);
                state.lastErrorName = "";
                state.lastErrorMessage = "";
                return rememberStream(stream);
              } catch (error) {
                state.lastErrorName = error && error.name ? String(error.name) : "Error";
                state.lastErrorMessage = error && error.message ? String(error.message) : "media error";
                syncState();
                throw error;
              }
            };
          }

          state.stopAll = () => {
            for (const track of Array.from(activeTracks.values())) {
              try {
                track.stop();
              } catch (_error) {
              }
            }
            activeTracks.clear();
            syncState();
          };

          window.__ninoMediaState = state;
          syncState();
        })();
        """
        self._page.runJavaScript(script)
        self._media_probe_installed = True
        if not self.media_poll_timer.isActive():
            self.media_poll_timer.start()

    def _stop_media_probe(self) -> None:
        self.media_poll_timer.stop()
        self._media_probe_installed = False

    def _poll_media_state(self) -> None:
        if self._page is None or not self._state.has_content:
            return
        self._page.runJavaScript(
            "window.__ninoMediaState ? JSON.stringify(window.__ninoMediaState) : ''",
            self._apply_polled_media_state,
        )

    def _apply_polled_media_state(self, raw_value: object) -> None:
        if not raw_value:
            return
        try:
            payload = json.loads(str(raw_value))
        except json.JSONDecodeError:
            return

        audio_active = bool(payload.get("audioActive"))
        video_active = bool(payload.get("videoActive"))
        self._set_media_status(audio_active, video_active)

        error_name = str(payload.get("lastErrorName", "") or "").strip()
        error_message = str(payload.get("lastErrorMessage", "") or "").strip()
        if error_name or error_message:
            normalized_error = self._classify_media_error(error_name, error_message)
            if normalized_error != self._media_last_error:
                self._media_last_error = normalized_error
                self.show_media_message(normalized_error)
        elif self._media_last_error and not audio_active and not video_active:
            self._media_last_error = ""
            self.clear_media_message()

    def _set_media_status(self, audio_active: bool, video_active: bool) -> None:
        self._media_audio_active = audio_active
        self._media_video_active = video_active
        if audio_active and video_active:
            text = "🎤 📷"
            tooltip = "Microphone et caméra actifs"
        elif audio_active:
            text = "🎤"
            tooltip = "Microphone actif"
        elif video_active:
            text = "📷"
            tooltip = "Caméra active"
        else:
            text = ""
            tooltip = ""

        if self._browser_container is None:
            return
        self.media_banner.setText(text)
        self.media_banner.setToolTip(tooltip)
        self.media_banner.setVisible(bool(text))

    def _classify_media_error(self, error_name: str, error_message: str) -> str:
        if error_name == "NotAllowedError":
            return (
                "Accès média accordé par Nino mais bloqué par Windows, par le navigateur ou refusé par la page."
            )
        if error_name == "NotFoundError":
            return "Aucun microphone ou aucune caméra compatible n’a été détecté."
        if error_name in {"NotReadableError", "TrackStartError"}:
            return "Le périphérique média est déjà utilisé, indisponible ou débranché."
        if error_name == "AbortError":
            return "La demande média a été annulée avant l’ouverture du périphérique."
        if error_name == "SecurityError":
            return "L’accès média a été bloqué pour des raisons de sécurité."
        if error_name:
            return f"Erreur média {error_name}: {error_message or 'échec de l’accès au périphérique.'}"
        if error_message:
            return f"Erreur média: {error_message}"
        return "Erreur média inconnue."

    def queue_thumbnail_capture(self) -> None:
        QTimer.singleShot(THUMBNAIL_CAPTURE_DELAY_MS, self.capture_thumbnail_if_possible)

    def capture_thumbnail_if_possible(self) -> None:
        if not self.isVisible():
            return
        pixmap = self._build_thumbnail_pixmap()
        self._state.thumbnail = pixmap
        self._state.thumbnail_revision += 1
        self._emit_state()

    def _build_thumbnail_pixmap(self) -> QPixmap:
        if self._state.has_content and self._web_view is not None:
            source = self.grab()
            if not source.isNull():
                return source.scaled(
                    THUMBNAIL_IMAGE_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        return self._build_placeholder_thumbnail()

    def _build_placeholder_thumbnail(self) -> QPixmap:
        pixmap = QPixmap(THUMBNAIL_IMAGE_SIZE)
        pixmap.fill(QColor(PALETTE.panel_bg))
        painter = QPainter(pixmap)
        painter.setPen(QColor(PALETTE.text_secondary))
        painter.drawText(
            pixmap.rect().adjusted(12, 12, -12, -12),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self._state.display_title if self._state.has_content else f"Tile {self.tile_id + 1}\nEmpty",
        )
        painter.end()
        return pixmap

    def _emit_state(self) -> None:
        self.state_changed.emit(replace(self._state))

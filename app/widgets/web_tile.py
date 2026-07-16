
from __future__ import annotations

from dataclasses import replace
import json

from PySide6.QtCore import QEventLoop, QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon

from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
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
        self._media_probe_installed = False
        self._media_audio_active = False
        self._media_video_active = False
        self._media_last_error = ""

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
            self.focus_button.setText("▦")
            self.focus_button.setToolTip("Retour à la grille")
            self.focus_button.setProperty("role", "nav")
            self.split_button.show()
        else:
            self.focus_button.setText("⛶")
            self.focus_button.setToolTip("Open this tile in focus mode")
            self.focus_button.setProperty("role", "accent")
            self.split_button.hide()
            self._split_button_active = False
            self._split_panel_visible = False

        self.focus_button.style().unpolish(self.focus_button)
        self.focus_button.style().polish(self.focus_button)
        self._refresh_split_button_state()
        self._apply_navigation_state()

    def _refresh_split_button_state(self) -> None:
        if self._browser_container is None:
            return
        self.split_button.setText("⇆")
        if not self._split_button_active:
            tooltip = "Aucun split permanent actif"
            role = "nav"
        elif self._split_panel_visible:
            tooltip = "Masquer temporairement la page secondaire"
            role = "accent"
        else:
            tooltip = "Restaurer la page secondaire liee"
            role = "accent"
        self.split_button.setToolTip(tooltip)
        self.split_button.setProperty("role", role)
        self.split_button.style().unpolish(self.split_button)
        self.split_button.style().polish(self.split_button)

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

        buttons_row.addStretch(1)
        buttons_row.addWidget(self.empty_load_button)
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
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(4)

        self.back_button = QPushButton("←")
        self.forward_button = QPushButton("→")
        self.reload_button = QPushButton("↻")
        self.zoom_out_button = QPushButton("-")
        self.zoom_in_button = QPushButton("+")
        self.memory_button = QPushButton("💾")
        self.focus_button = QPushButton("⛶")
        self.split_button = QPushButton("⇆")
        self.close_button = QPushButton("✕")
        self.media_status_label = QLabel("")
        self.media_status_label.setObjectName("SecondaryText")
        self.media_status_label.setStyleSheet(
            "padding: 2px 6px; border: 1px solid #34506f; border-radius: 8px; background: #182433; font-weight: 700;"
        )
        self.media_status_label.hide()

        for button, tooltip, role in (
            (self.back_button, "Go back", "nav"),
            (self.forward_button, "Go forward", "nav"),
            (self.reload_button, "Reload", "nav"),
            (self.zoom_out_button, "Zoom out", "zoom"),
            (self.zoom_in_button, "Zoom in", "zoom"),
            (self.memory_button, "Save this tile", "memory"),
            (self.focus_button, "Open this tile in focus mode", "accent"),
            (self.split_button, "Split this focused page", "accent"),
            (self.close_button, "Close this tile", "danger"),
        ):
            self._configure_toolbar_button(button, tooltip, role)

        self.browser_url_edit = QLineEdit()
        self.browser_url_edit.setObjectName("BrowserUrlEdit")
        self.browser_url_edit.setPlaceholderText("Page address")
        self.browser_url_edit.setFixedHeight(URL_BAR_HEIGHT)
        self.browser_url_edit.setMinimumWidth(90)
        self.browser_url_edit.returnPressed.connect(self.load_from_browser_input)

        header_layout.addWidget(self.back_button)
        header_layout.addWidget(self.forward_button)
        header_layout.addWidget(self.reload_button)
        header_layout.addWidget(self.zoom_out_button)
        header_layout.addWidget(self.zoom_in_button)
        header_layout.addWidget(self.browser_url_edit, 1)
        header_layout.addWidget(self.media_status_label)
        header_layout.addWidget(self.memory_button)
        header_layout.addWidget(self.focus_button)
        header_layout.addWidget(self.split_button)
        header_layout.addWidget(self.close_button)

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
        self._navigate_from_text(self.empty_url_edit.text())

    def load_from_browser_input(self) -> None:
        self._navigate_from_text(self.browser_url_edit.text())

    def open_url_text(self, raw_text: str) -> None:
        self._navigate_from_text(raw_text)

    def current_page_url(self) -> str:
        return self._state.current_url.strip()

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

    def _navigate_from_text(self, raw_text: str) -> None:
        result = normalize_user_url(raw_text)
        if not result.ok:
            self.show_input_error(result.error)
            return
        self.clear_errors()
        self._ensure_browser_page()
        self.stack.setCurrentWidget(self._browser_container)
        self.browser_url_edit.setText(result.normalized_text)
        self.empty_url_edit.setText(result.normalized_text)
        self._state.has_content = True
        self._state.error_message = ""
        self._state.status = TileVisualStatus.LOADING
        self._load_qurl(result.url)

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
        self.media_status_label.setText(text)
        self.media_status_label.setToolTip(tooltip)
        self.media_status_label.setVisible(bool(text))

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

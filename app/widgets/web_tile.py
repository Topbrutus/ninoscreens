from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer, Qt, QUrl, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
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


class PopupCapturePage(QWebEnginePage):
    """
    Temporary page used to capture popup / new-window requests.

    Strategy:
    - redirect the first resulting URL back into the current tile
    - do not allow uncontrolled native windows to appear
    """

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
        popup_page = PopupCapturePage(self.profile(), self)
        popup_page.popup_url_ready.connect(self.popup_url_ready.emit)
        return popup_page


class WebTile(QFrame):
    state_changed = Signal(object)
    memory_requested = Signal(int)
    focus_requested = Signal(int)
    grid_requested = Signal(int)

    def __init__(self, tile_id: int, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(parent)
        self.tile_id = tile_id
        self.profile = profile
        self._state = TileState(tile_id=tile_id)
        self._browser_container: QWidget | None = None
        self._web_view: QWebEngineView | None = None
        self._page: TileWebPage | None = None
        self._toolbar_focus_mode = False

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

        self._emit_state()

    @property
    def state(self) -> TileState:
        return self._state

    def set_focus_flag(self, focused: bool) -> None:
        self._state.is_focused = focused
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)
        self._emit_state()

    def set_toolbar_focus_mode(self, in_focus_mode: bool) -> None:
        self._toolbar_focus_mode = in_focus_mode
        if self._browser_container is None:
            return

        if in_focus_mode:
            self.focus_button.setText("🧩")
            self.focus_button.setToolTip("Revenir à la grille")
            self.focus_button.setProperty("role", "nav")
        else:
            self.focus_button.setText("🎯")
            self.focus_button.setToolTip("Ouvrir ce carreau en mode focus")
            self.focus_button.setProperty("role", "accent")

        self.focus_button.style().unpolish(self.focus_button)
        self.focus_button.style().polish(self.focus_button)

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addStretch(1)

        title = QLabel(f"Carreau {self.tile_id + 1}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")

        prompt = QLabel("Quelle page internet voulez-vous avoir ?")
        prompt.setObjectName("TilePrompt")
        prompt.setWordWrap(True)
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_url_edit = QLineEdit()
        self.empty_url_edit.setPlaceholderText("https://exemple.com")
        self.empty_url_edit.setFixedHeight(URL_BAR_HEIGHT + 4)
        self.empty_url_edit.returnPressed.connect(self.load_from_empty_input)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        self.empty_load_button = QPushButton("🚠 Charger")
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

        self.back_button = QPushButton("⬅️")
        self.forward_button = QPushButton("➡️")
        self.reload_button = QPushButton("🔄")
        self.zoom_out_button = QPushButton("➖")
        self.zoom_in_button = QPushButton("➕")
        self.memory_button = QPushButton("💾")
        self.focus_button = QPushButton("🎯")
        self.close_button = QPushButton("❌")

        for button, tooltip, role in (
            (self.back_button, "Retour", "nav"),
            (self.forward_button, "Avancer", "nav"),
            (self.reload_button, "Recharger", "nav"),
            (self.zoom_out_button, "Zoom -", "zoom"),
            (self.zoom_in_button, "Zoom +", "zoom"),
            (self.memory_button, "Mémoriser maintenant ce carreau", "memory"),
            (self.focus_button, "Ouvrir ce carreau en mode focus", "accent"),
            (self.close_button, "Fermer ce carreau", "danger"),
        ):
            self._configure_toolbar_button(button, tooltip, role)

        self.browser_url_edit = QLineEdit()
        self.browser_url_edit.setObjectName("BrowserUrlEdit")
        self.browser_url_edit.setPlaceholderText("Adresse de la page")
        self.browser_url_edit.setFixedHeight(URL_BAR_HEIGHT)
        self.browser_url_edit.setMinimumWidth(90)
        self.browser_url_edit.returnPressed.connect(self.load_from_browser_input)

        header_layout.addWidget(self.back_button)
        header_layout.addWidget(self.forward_button)
        header_layout.addWidget(self.reload_button)
        header_layout.addWidget(self.zoom_out_button)
        header_layout.addWidget(self.zoom_in_button)
        header_layout.addWidget(self.browser_url_edit, 1)
        header_layout.addWidget(self.memory_button)
        header_layout.addWidget(self.focus_button)
        header_layout.addWidget(self.close_button)

        self.error_banner = QLabel("")
        self.error_banner.setObjectName("ErrorBanner")
        self.error_banner.setContentsMargins(8, 4, 8, 4)
        self.error_banner.hide()

        self._web_view = QWebEngineView()
        self._page = TileWebPage(self.profile, self._web_view)
        self._page.popup_url_ready.connect(self._load_qurl)
        self._page.fullScreenRequested.connect(self._handle_page_fullscreen_request)
        self._web_view.setPage(self._page)

        self.back_button.clicked.connect(self._web_view.back)
        self.forward_button.clicked.connect(self._web_view.forward)
        self.reload_button.clicked.connect(self._web_view.reload)
        self.zoom_out_button.clicked.connect(lambda: self.adjust_zoom(-ZOOM_STEP))
        self.zoom_in_button.clicked.connect(lambda: self.adjust_zoom(ZOOM_STEP))
        self.memory_button.clicked.connect(lambda: self.memory_requested.emit(self.tile_id))
        self.focus_button.clicked.connect(self._on_focus_button_clicked)
        self.close_button.clicked.connect(self.reset_to_empty)

        self._page.loadStarted.connect(self._on_load_started)
        self._page.loadFinished.connect(self._on_load_finished)
        self._page.loadProgress.connect(self._on_load_progress)
        self._page.urlChanged.connect(self._on_url_changed)
        self._page.titleChanged.connect(self._on_title_changed)
        self._page.iconChanged.connect(lambda _icon: self.queue_thumbnail_capture())

        container_layout.addWidget(header)
        container_layout.addWidget(self.error_banner)
        container_layout.addWidget(self._web_view, 1)

        self._browser_container = container
        self.stack.addWidget(container)
        self._apply_navigation_state()
        self.set_toolbar_focus_mode(self._toolbar_focus_mode)

    def _on_focus_button_clicked(self) -> None:
        if self._toolbar_focus_mode:
            self.grid_requested.emit(self.tile_id)
        else:
            self.focus_requested.emit(self.tile_id)

    def load_from_empty_input(self) -> None:
        self._navigate_from_text(self.empty_url_edit.text())

    def load_from_browser_input(self) -> None:
        self._navigate_from_text(self.browser_url_edit.text())

    def open_url_text(self, raw_text: str) -> None:
        self._navigate_from_text(raw_text)

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
        """
        Return the tile to its initial state.

        We recreate the browser layer on the next load so that navigation history,
        page instance, and local transient state are reset cleanly.
        """
        if self._browser_container is not None:
            self.stack.removeWidget(self._browser_container)
            self._browser_container.deleteLater()
            self._browser_container = None
            self._web_view = None
            self._page = None

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

        self.stack.setCurrentWidget(self.empty_page)
        self.queue_thumbnail_capture()
        self._emit_state()

    def _on_load_started(self) -> None:
        self.clear_errors()
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
        else:
            self._state.status = TileVisualStatus.ERROR
            self._state.error_message = "Le chargement a échoué ou la page est inaccessible."
            self.error_banner.setText(self._state.error_message)
            self.error_banner.show()

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
        self.close_button.setEnabled(self._state.has_content)

    def _handle_page_fullscreen_request(self, request) -> None:
        """
        Reject site-driven fullscreen in V1.

        This keeps the application in control and avoids conflicts with:
        - the application's own focus mode
        - the application's own global fullscreen mode
        """
        request.reject()

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
            self._state.display_title if self._state.has_content else f"Carreau {self.tile_id + 1}\nVide",
        )
        painter.end()
        return pixmap

    def _emit_state(self) -> None:
        self.state_changed.emit(replace(self._state))

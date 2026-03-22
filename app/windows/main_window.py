from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    APP_MARGIN,
    APP_NAME,
    DEFAULT_WINDOW_SIZE,
    MEMORY_SLOT_BUTTON_SIZE,
    MINIMUM_WINDOW_SIZE,
    SESSION_SAVE_DEBOUNCE_MS,
    TILE_COUNT,
)
from app.session_store import load_session_payload, save_session_payload, serialize_app_state
from app.state import AppState, TileState
from app.web_profile import build_shared_profile
from app.widgets.dashboard_grid import DashboardGrid
from app.widgets.focus_view import FocusView
from app.widgets.web_tile import WebTile


class MainWindow(QMainWindow):
    """Main application window coordinating grid mode, focus mode, persistence, and global state."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)

        self.app_state = AppState(window_size=DEFAULT_WINDOW_SIZE)
        self.profile = build_shared_profile(self)
        self.tiles: dict[int, WebTile] = {}
        self.memory_slot_buttons: dict[int, QPushButton] = {}
        self._focused_tile_id: int | None = None
        self._restoring_session = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SESSION_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_session_now)

        self._build_ui()
        self._build_tiles()
        self._restore_session()
        self._sync_focus_flags()
        self._refresh_global_labels()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(12)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(12)

        self.window_title_label = QLabel(APP_NAME)
        self.window_title_label.setStyleSheet("font-size: 16px; font-weight: 700;")

        self.mode_label = QLabel("Mode grille 3x3")
        self.mode_label.setObjectName("SecondaryText")

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("MutedText")

        self.memory_bar = QWidget()
        memory_layout = QHBoxLayout(self.memory_bar)
        memory_layout.setContentsMargins(0, 0, 0, 0)
        memory_layout.setSpacing(6)

        for tile_id in range(TILE_COUNT):
            button = QPushButton(str(tile_id + 1))
            button.setFixedSize(MEMORY_SLOT_BUTTON_SIZE)
            button.setProperty("compact", True)
            button.setProperty("role", "memory-slot")
            button.setProperty("filled", False)
            button.setProperty("active", False)
            button.setToolTip(f"Carreau {tile_id + 1}")
            button.clicked.connect(lambda _checked=False, tid=tile_id: self.activate_memory_slot(tid))
            self.memory_slot_buttons[tile_id] = button
            memory_layout.addWidget(button)

        self.reload_all_button = QPushButton("🔄 Tout")
        self.reload_all_button.setProperty("compact", True)
        self.reload_all_button.setProperty("role", "memory-slot")
        self.reload_all_button.clicked.connect(self.reload_all_tiles)
        memory_layout.addWidget(self.reload_all_button)

        top_layout.addWidget(self.window_title_label)
        top_layout.addSpacing(8)
        top_layout.addWidget(self.mode_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.memory_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        top_layout.addStretch(1)
        top_layout.addWidget(self.summary_label)

        self.fullscreen_button = QPushButton("⛶ Plein écran")
        self.fullscreen_button.setProperty("role", "accent")
        self.fullscreen_button.clicked.connect(self.toggle_global_fullscreen)
        top_layout.addWidget(self.fullscreen_button)

        root.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        self.grid_view = DashboardGrid()
        self.focus_view = FocusView()
        self.focus_view.tile_switch_requested.connect(self.switch_focus_tile)

        self.stack.addWidget(self.grid_view)
        self.stack.addWidget(self.focus_view)
        root.addWidget(self.stack, 1)

    def _build_tiles(self) -> None:
        for tile_id in range(TILE_COUNT):
            tile = WebTile(tile_id=tile_id, profile=self.profile)
            tile.state_changed.connect(self.on_tile_state_changed)
            tile.memory_requested.connect(self.save_session_now)
            tile.focus_requested.connect(self.enter_focus_mode)
            tile.grid_requested.connect(self.exit_focus_mode)
            self.tiles[tile_id] = tile
            self.grid_view.place_tile(tile, tile_id)

    def _restore_session(self) -> None:
        payload = load_session_payload()
        if not payload:
            self._update_memory_buttons()
            return

        self._restoring_session = True

        window_payload = payload.get("window", {})
        width = int(window_payload.get("width", DEFAULT_WINDOW_SIZE.width()))
        height = int(window_payload.get("height", DEFAULT_WINDOW_SIZE.height()))
        self.resize(max(width, MINIMUM_WINDOW_SIZE.width()), max(height, MINIMUM_WINDOW_SIZE.height()))
        self.app_state.window_size = self.size()

        for tile_payload in payload.get("tiles", []):
            tile_id = tile_payload.get("tile_id")
            if not isinstance(tile_id, int) or tile_id not in self.tiles:
                continue
            if tile_payload.get("has_content"):
                current_url = str(tile_payload.get("current_url", "")).strip()
                zoom_factor = float(tile_payload.get("zoom_factor", 1.0))
                self.tiles[tile_id].restore_from_session(current_url=current_url, zoom_factor=zoom_factor)

        focused_tile_id = payload.get("focused_tile_id")
        self._restoring_session = False

        if isinstance(focused_tile_id, int) and focused_tile_id in self.tiles:
            QTimer.singleShot(0, lambda tid=focused_tile_id: self.enter_focus_mode(tid))

        self._update_memory_buttons()

    def on_tile_state_changed(self, state_object: object) -> None:
        state = state_object if isinstance(state_object, TileState) else None
        if state is None:
            return

        self.app_state.tiles[state.tile_id] = state
        if self._focused_tile_id is not None:
            self.focus_view.rail.refresh(self.app_state.tiles, self._focused_tile_id)

        self._refresh_global_labels()
        self._update_memory_buttons()

        if not self._restoring_session:
            self.schedule_session_save()

    def activate_memory_slot(self, tile_id: int) -> None:
        self.enter_focus_mode(tile_id)

    def reload_all_tiles(self) -> None:
        for tile in self.tiles.values():
            tile.reload_current()

    def enter_focus_mode(self, tile_id: int) -> None:
        if self._focused_tile_id == tile_id and self.stack.currentWidget() is self.focus_view:
            return

        if self._focused_tile_id is None:
            self._detach_tile_from_grid(tile_id)
        else:
            self._return_tile_to_grid(self._focused_tile_id)
            self._detach_tile_from_grid(tile_id)

        self._focused_tile_id = tile_id
        self.app_state.focused_tile_id = tile_id

        tile = self.tiles[tile_id]
        self.focus_view.set_tile_widget(tile)
        self.stack.setCurrentWidget(self.focus_view)
        self._sync_focus_flags()
        self.focus_view.rail.refresh(self.app_state.tiles, tile_id)

        self.mode_label.setText("Mode focus")
        self._refresh_global_labels()
        self.schedule_session_save()

    def switch_focus_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None:
            self.enter_focus_mode(tile_id)
            return
        if tile_id == self._focused_tile_id:
            return

        self._return_tile_to_grid(self._focused_tile_id)
        self._detach_tile_from_grid(tile_id)

        self._focused_tile_id = tile_id
        self.app_state.focused_tile_id = tile_id

        tile = self.tiles[tile_id]
        self.focus_view.set_tile_widget(tile)
        self.stack.setCurrentWidget(self.focus_view)
        self._sync_focus_flags()
        self.focus_view.rail.refresh(self.app_state.tiles, tile_id)

        self._refresh_global_labels()
        self.schedule_session_save()

    def exit_focus_mode(self, *_args) -> None:
        if self._focused_tile_id is None:
            return

        self._return_tile_to_grid(self._focused_tile_id)
        self.focus_view.clear_tile_widget()

        self._focused_tile_id = None
        self.app_state.focused_tile_id = None
        self.stack.setCurrentWidget(self.grid_view)
        self._sync_focus_flags()

        self.mode_label.setText("Mode grille 3x3")
        self._refresh_global_labels()
        self.schedule_session_save()

    def _detach_tile_from_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        self.grid_view.remove_tile(tile)

    def _return_tile_to_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        self.focus_view.clear_tile_widget()
        self.grid_view.place_tile(tile, tile_id)

    def _sync_focus_flags(self) -> None:
        in_focus_view = self.stack.currentWidget() is self.focus_view
        for tile_id, tile in self.tiles.items():
            is_active_focus_tile = tile_id == self._focused_tile_id
            tile.set_focus_flag(is_active_focus_tile)
            tile.set_toolbar_focus_mode(in_focus_view and is_active_focus_tile)

        self.app_state.tiles = [replace(tile.state) for _, tile in sorted(self.tiles.items())]
        self.focus_view.rail.refresh(self.app_state.tiles, self._focused_tile_id)
        self._update_memory_buttons()

    def _update_memory_buttons(self) -> None:
        for tile_id, button in self.memory_slot_buttons.items():
            tile_state = self.app_state.tiles[tile_id]
            button.setProperty("filled", tile_state.has_content)
            button.setProperty("active", tile_id == self._focused_tile_id)

            if tile_state.has_content:
                tooltip = f"{tile_id + 1} — {tile_state.display_title}\n{tile_state.current_url}"
            else:
                tooltip = f"{tile_id + 1} — Carreau vide"

            button.setToolTip(tooltip)
            button.style().unpolish(button)
            button.style().polish(button)

        any_loaded = any(tile.has_content for tile in self.app_state.tiles)
        self.reload_all_button.setEnabled(any_loaded)

    def toggle_global_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.app_state.is_fullscreen = False
            self.fullscreen_button.setText("⛶ Plein écran")
        else:
            self.showFullScreen()
            self.app_state.is_fullscreen = True
            self.fullscreen_button.setText("🗗 Quitter le plein écran")
        self._refresh_global_labels()
        self.schedule_session_save()

    def resizeEvent(self, event) -> None:
        self.app_state.window_size = self.size()
        self.schedule_session_save()
        super().resizeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.app_state.window_size = self.size()
        self.save_session_now()
        super().closeEvent(event)

    def schedule_session_save(self) -> None:
        if self._restoring_session:
            return
        self._save_timer.start()

    def save_session_now(self, *_args) -> None:
        self.app_state.tiles = [replace(tile.state) for _, tile in sorted(self.tiles.items())]
        self.app_state.focused_tile_id = self._focused_tile_id
        self.app_state.window_size = self.size()
        save_session_payload(serialize_app_state(self.app_state))
        self._refresh_global_labels()
        self._update_memory_buttons()

    def _refresh_global_labels(self) -> None:
        loaded = sum(1 for tile in self.app_state.tiles if tile.has_content)
        loading = sum(1 for tile in self.app_state.tiles if tile.is_loading)
        self.summary_label.setText(f"{loaded}/9 chargés — {loading} en chargement")

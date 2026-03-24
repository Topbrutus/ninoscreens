from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer
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
    MINIMUM_WINDOW_SIZE,
    PAGE_COUNT,
    RUN_PAGE_INDEX,
    SESSION_SAVE_DEBOUNCE_MS,
    TILE_COUNT,
    TILES_PER_PAGE,
)
from app.memory_usage import get_process_memory_mb
from app.session_store import load_session_payload, save_session_payload, serialize_app_state
from app.state import AppState, TileState
from app.web_profile import build_shared_profile
from app.widgets.api_panel import ApiConnectionPanel
from app.widgets.audio_panel import AudioSettingsPanel
from app.widgets.dashboard_grid import DashboardGrid
from app.widgets.focus_view import FocusView
from app.widgets.page_matrix import PageMatrix
from app.widgets.run_workspace import RunWorkspace
from app.widgets.web_tile import WebTile


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)

        self.app_state = AppState(window_size=DEFAULT_WINDOW_SIZE)
        self.profile = build_shared_profile(self)
        self.tiles: dict[int, WebTile] = {}
        self.page_grids: list[DashboardGrid] = []
        self._focused_tile_id: int | None = None
        self._restoring_session = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SESSION_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_session_now)

        self._memory_timer = QTimer(self)
        self._memory_timer.setInterval(2000)
        self._memory_timer.timeout.connect(self._refresh_memory_usage)

        self._build_ui()
        self._build_tiles()
        self._restore_session()
        self._sync_focus_flags()
        self._refresh_memory_usage()
        self._refresh_top_state()
        self._memory_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(10)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(10)

        title_column = QWidget()
        title_layout = QVBoxLayout(title_column)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.window_title_label = QLabel(APP_NAME)
        self.window_title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.mode_label = QLabel("Page 1 / 3")
        self.mode_label.setObjectName("SecondaryText")
        self.summary_label = QLabel""
        self.summary_label.setObjectName("MutedText")

        title_layout.addWidget(self.window_title_label)
        title_layout.addWidget(self.mode_label)
        title_layout.addWidget(self.summary_label)

        self.page_matrix = PageMatrix()
        self.page_matrix.slot_activated.connect(self.activate_memory_slot)
        self.page_matrix.run_activated.connect(self.show_run_page)

        controls_host = QWidget()
        controls_layout = QVBoxLayout(controls_host)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)

        controls_row1 = QHBoxLayout()
        controls_row1.setContentsMargins(0, 0, 0, 0)
        controls_row1.setSpacing(4)
        controls_row2 = QHBoxLayout()
        controls_row2.setContentsMargins(0, 0, 0, 0)
        controls_row2.setSpacing(4)

        self.audio_button = QPushButton("Audio")
        self.audio_button.setProperty("compact", True)
        self.audio_button.clicked.connect(self._toggle_audio_panel)

        self.api_button = QPushButton("API")
        self.api_button.setProperty("compact", True)
        self.api_button.clicked.connect(self._toggle_api_panel)

        self.tiles_button = QPushButton("Pages")
        self.tiles_button.setProperty("compact", True)
        self.tiles_button.clicked.connect(lambda: self.show_tile_page(self.app_state.current_page_index))

        self.focus_exit_button = QPushButton("Sortir focus")
        self.focus_exit_button.setProperty("compact", True)
        self.focus_exit_button.clicked.connect(self.exit_focus_mode)

        self.fullscreen_button = QPushButton("Plein écran")
        self.fullscreen_button.setProperty("compact", True)
        self.fullscreen_button.setProperty("role", "accent")
        self.fullscreen_button.clicked.connect(self.toggle_global_fullscreen)

        controls_row1.addWidget(self.audio_button)
        controls_row1.addWidget(self.api_button)
        controls_row2.addWidget(self.tiles_button)
        controls_row2.addWidget(self.focus_exit_button)
        controls_layout.addLayout(controls_row1)
        controls_layout.addLayout(controls_row2)
        controls_layout.addWidget(self.fullscreen_button)

        top_layout.addWidget(title_column, 0)
        top_layout.addWidget(self.page_matrix, 1)
        top_layout.addWidget(controls_host, 0)

        root.addWidget(self.top_bar)

        self.control_panels = QWidget()
        self.control_panels_layout = QHBoxLayout(self.control_panels)
        self.control_panels_layout.setContentsMargins(0, 0, 0, 0)
        self.control_panels_layout.setSpacing(10)

        self.api_panel = ApiConnectionPanel()
        self.api_panel.hide()
        self.audio_panel = AudioSettingsPanel()
        self.audio_panel.hide()

        self.control_panels_layout.addWidget(self.api_panel, 1)
        self.control_panels_layout.addWidget(self.audio_panel, 1)
        self.control_panels.hide()
        root.addWidget(self.control_panels)

        self.main_stack = QStackedWidget()
        self.page_stack = QStackedWidget()

        for _page_index in range(PAGE_COUNT):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
            grid = DashboardGrid()
            page_layout.addWidget(grid, 1)
            self.page_grids.append(grid)
            self.page_stack.addWidget(page)

        self.run_workspace = RunWorkspace()
        self.run_workspace.prompt_submitted.connect(self._on_run_prompt_submitted)
        self.page_stack.addWidget(self.run_workspace)

        self.focus_view = FocusView()
        self.focus_view.tile_switch_requested.connect(self.switch_focus_tile)

        self.main_stack.addWidget(self.page_stack)
        self.main_stack.addWidget(self.focus_view)
        root.addWidget(self.main_stack, 1)

    def _build_tiles(self) -> None:
        for tile_id in range(TILE_COUNT):
            tile = WebTile(tile_id=tile_id, profile=self.profile)
            tile.state_changed.connect(self.on_tile_state_changed)
            tile.memory_requested.connect(self.activate_memory_slot)
            tile.focus_requested.connect(self.enter_focus_mode)
            tile.grid_requested.connect(self.exit_focus_mode)
            self.tiles[tile_id] = tile
            page_index = self._tile_page_index(tile_id)
            slot_index = tile_id % TILES_PER_PAGE
            self.page_grids[page_index].place_tile(tile, slot_index)

    def _tile_page_index(self, tile_id: int) -> int:
        return max(0, min(PAGE_COUNT - 1, tile_id // TILES_PER_PAGE))

    def _show_page_for_tile(self, tile_id: int) -> None:
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"
        self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        if self._focused_tile_id is None:
            self._show_active_workspace()

    def _tile_memory_mb(self, tile: WebTile) -> int:
        page = getattr(tile, "_page", None)
        if page is None:
            return 0
        pid_getter = getattr(page, "renderProcessPid", None)
        if not callable(pid_getter):
            return 0
        try:
            pid = int(pid_getter())
        except (TypeError, ValueError):
            return 0
        memory_mb = get_process_memory_mb(pid)
        return 0 if memory_mb is None else memory_mb

    def _should_measure_tile_memory(self, tile_id: int) -> bool:
        if self._focused_tile_id == tile_id:
            return True
        if self.app_state.active_view != "tiles":
            return False
        return self._tile_page_index(tile_id) == self.app_state.current_page_index

    def _refresh_memory_usage(self) -> None:
        changed = False
        for tile_id, tile in self.tiles.items():
            if not self._should_measure_tile_memory(tile_id):
                continue
            memory_mb = self._tile_memory_mb(tile)
            if tile.state.memory_mb != memory_mb:
                tile.state.memory_mb = memory_mb
                self.app_state.tiles[tile_id].memory_mb = memory_mb
                changed = True
        if changed:
            self._refresh_top_state()
            if self._focused_tile_id is not None:
                self.focus_view.rail.refresh(self.app_state.tiles, self._focused_tile_id)

    def activate_memory_slot(self, tile_id: int) -> None:
        tile_id = max(0, min(TILE_COUNT - 1, tile_id))
        self._show_page_for_tile(tile_id)
        self._refresh_top_state()
        QTimer.singleShot(0, lambda tid=tile_id: self.enter_focus_mode(tid))

    def show_tile_page(self, page_index: int) -> None:
        self.app_state.current_page_index = max(0, min(PAGE_COUNT - 1, page_index))
        self.app_state.active_view = "tiles"
        if self._focused_tile_id is None:
            self._show_active_workspace()
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        self._refresh_memory_usage()
        self._refresh_top_state()
        self.schedule_session_save()

    def show_run_page(self) -> None:
        self.app_state.active_view = "run"
        if self._focused_tile_id is None:
            self._show_active_workspace()
        self._refresh_top_state()
        self.schedule_session_save()

    def enter_focus_mode(self, tile_id: int) -> None:
        if tile_id not in self.tiles:
            return
        if self._focused_tile_id == tile_id and self.main_stack.currentWidget() is self.focus_view:
            return

        self._show_page_for_tile(tile_id)
        self.page_stack.setCurrentIndex(self._tile_page_index(tile_id))

        if self._focused_tile_id is None:
            self._detach_tile_from_grid(tile_id)
        else:
            self._return_tile_to_grid(self._focused_tile_id)
            self._detach_tile_from_grid(tile_id)

        self._focused_tile_id = tile_id
        self.app_state.focused_tile_id = tile_id
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"

        tile = self.tiles[tile_id]
        self.focus_view.set_tile_widget(tile)
        self.main_stack.setCurrentWidget(self.focus_view)
        self._sync_focus_flags()
        self._refresh_memory_usage()
        self._refresh_top_state()
        self.schedule_session_save()

    def switch_focus_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None:
            self.enter_focus_mode(tile_id)
            return
        if tile_id == self._focused_tile_id:
            return
        self._show_page_for_tile(tile_id)
        QTimer.singleShot(0, lambda tid=tile_id: self.enter_focus_mode(tid))

    def exit_focus_mode(self, *_args) -> None:
        if self._focused_tile_id is None:
            return
        self._return_tile_to_grid(self._focused_tile_id)
        self.focus_view.clear_tile_widget()
        self._focused_tile_id = None
        self.app_state.focused_tile_id = None
        self._show_active_workspace()
        self._refresh_memory_usage()
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def _detach_tile_from_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        if tile.parent() is self.focus_view.main_panel:
            return
        self.page_grids[self._tile_page_index(tile_id)].remove_tile(tile)

    def _return_tile_to_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        self.focus_view.clear_tile_widget()
        self.page_stack.setCurrentIndex(self._tile_page_index(tile_id))
        self.page_grids[self._tile_page_index(tile_id)].place_tile(tile, tile_id % TILES_PER_PAGE)

    def _show_active_workspace(self) -> None:
        self.main_stack.setCurrentWidget(self.page_stack)
        if self.app_state.active_view == "run":
            self.page_stack.setCurrentIndex(RUN_PAGE_INDEX)
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)

    def _sync_focus_flags(self) -> None:
        in_focus_view = self.main_stack.currentWidget() is self.focus_view
        for tile_id, tile in self.tiles.items():
            is_active = tile_id == self._focused_tile_id
            tile.set_focus_flag(is_active)
            tile.set_toolbar_focus_mode(in_focus_view and is_active)
        self.app_state.tiles = [replace(tile.state) for _, tile in sorted(self.tiles.items())]
        self.focus_view.rail.refresh(self.app_state.tiles, self._focused_tile_id)
        self.page_matrix.refresh_all_slots(self.app_state.tiles)

    def _current_matrix_slot(self) -> int | None:
        if self._focused_tile_id is not None:
            return self._focused_tile_id
        if self.app_state.active_view == "run":
            return None
        return self.app_state.current_page_index * TILES_PER_PAGE

    def _refresh_top_state(self) -> None:
        self.page_matrix.refresh_all_slots(self.app_state.tiles)
        loaded = sum(1 for tile in self.app_state.tiles if tile.has_content)
        loading = sum(1 for tile in self.app_state.tiles if tile.is_loading)
        hot = sum(1 for tile in self.app_state.tiles if tile.memory_mb >= 700)

        if self._focused_tile_id is not None:
            self.mode_label.setText(f"Focus • carreau {self._focused_tile_id + 1}")
        elif self.app_state.active_view == "run":
            self.mode_label.setText("Page RUN / Corvo")
        else:
            self.mode_label.setText(f"Page {self.app_state.current_page_index + 1} / {PAGE_COUNT}")

        self.summary_label.setText(f"{loaded}/{TILE_COUNT} chargés • {loading} en chargement • }hot} rouges mémoire")
        self.page_matrix.set_active_slot(self._current_matrix_slot(), run_active=self.app_state.active_view == "run")
        self.focus_exit_button.setEnabled(self._focused_tile_id is not None)

    def _toggle_api_panel(self) -> None:
        visible = not self.api_panel.isVisible()
        self.api_panel.setVisible(visible)
        if visible:
            self.audio_panel.hide()
        self.control_panels.setVisible(self.api_panel.isVisible() or self.audio_panel.isVisible())

    def _toggle_audio_panel(self) -> None:
        visible = not self.audio_panel.isVisible()
        self.audio_panel.setVisible(visible)
        if visible:
            self.api_panel.hide()
        self.control_panels.setVisible(self.api_panel.isVisible() or self.audio_panel.isVisible())

    def toggle_global_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.app_state.is_fullscreen = False
            self.fullscreen_button.setText("Plein écran")
        else:
            self.showFullScreen()
            self.app_state.is_fullscreen = True
            self.fullscreen_button.setText("Quitter plein écran")
        self.schedule_session_save()

    def _restore_session(self) -> None:
        payload = load_session_payload()
        if not payload:
            self._show_active_workspace()
            return

        self._restoring_session = True
        window_payload = payload.get("window", {})
        width = int(window_payload.get("width", DEFAULT_WINDOW_SIZE.width()))
        height = int(window_payload.get("height", DEFAULT_WINDOW_SIZE.height()))
        self.resize(max(width, MINIMUM_WINDOW_SIZE.width()), max(height, MINIMUM_WINDOW_SIZE.height()))
        self.app_state.window_size = self.size()

        requested_page_index = payload.get("current_page_index", 0)
        if isinstance(requested_page_index, int) and 0 <= requested_page_index < PAGE_COUNT:
            self.app_state.current_page_index = requested_page_index

        active_view = str(payload.get("active_view", "tiles")).strip().lower()
        self.app_state.active_view = "run" if active_view == "run" else "tiles"

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
        self._show_active_workspace()
        self._refresh_memory_usage()
        self._refresh_top_state()

        if isinstance(focused_tile_id, int) and focused_tile_id in self.tiles:
            QTimer.singleShot(0, lambda tid=focused_tile_id: self.enter_focus_mode(tid))

    def on_tile_state_changed(self, state_object: object) -> None:
        state = state_object if isinstance(state_object, TileState) else None
        if state is None:
            return
        self.app_state.tiles[state.tile_id] = state
        if self._focused_tile_id is not None:
            self.focus_view.rail.refresh(self.app_state.tiles, self._focused_tile_id)
        self._refresh_memory_usage()
        self._refresh_top_state()
        if not self._restoring_session:
            self.schedule_session_save()

    def _on_run_prompt_submitted(self, text: str) -> None:
        self.run_workspace.append_system_message(f"Message local reçu : {text}", tone="info")

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
        self._refresh_top_state()

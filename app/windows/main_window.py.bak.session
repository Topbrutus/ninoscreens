
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
    TILE_COUNT,
    TILES_PER_PAGE,
)
from app.state import AppState, TileState
from app.web_profile import build_shared_profile
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
        if len(self.app_state.tiles) < TILE_COUNT:
            self.app_state.tiles = [TileState(tile_id=i) for i in range(TILE_COUNT)]

        self.profile = build_shared_profile(self)
        self.tiles: dict[int, WebTile] = {}
        self.page_grids: list[DashboardGrid] = []
        self._focused_tile_id: int | None = None
        self._last_selected_tile_id: int = 0

        self._build_ui()
        self._build_tiles()
        self._sync_focus_flags()
        self._refresh_top_state()

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
        self.mode_label = QLabel(f"Page 1 / {PAGE_COUNT}")
        self.mode_label.setObjectName("SecondaryText")
        self.summary_label = QLabel("")
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

        self.pages_button = QPushButton("Pages")
        self.pages_button.setProperty("compact", True)
        self.pages_button.clicked.connect(
            lambda: self.show_tile_page(self.app_state.current_page_index)
        )

        self.focus_exit_button = QPushButton("Quit focus")
        self.focus_exit_button.setProperty("compact", True)
        self.focus_exit_button.clicked.connect(self.exit_focus_mode)

        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.setProperty("compact", True)
        self.fullscreen_button.clicked.connect(self.toggle_global_fullscreen)

        controls_row1.addWidget(self.pages_button)
        controls_row2.addWidget(self.focus_exit_button)
        controls_layout.addLayout(controls_row1)
        controls_layout.addLayout(controls_row2)
        controls_layout.addWidget(self.fullscreen_button)

        top_layout.addWidget(title_column, 0)
        top_layout.addWidget(self.page_matrix, 1)
        top_layout.addWidget(controls_host, 0)

        root.addWidget(self.top_bar)

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
        self.page_stack.addWidget(self.run_workspace)

        self.focus_view = FocusView()
        self.focus_view.tile_switch_requested.connect(self.switch_focus_tile)
        self.focus_view.split_visibility_changed.connect(self._on_split_visibility_changed)

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
            tile.split_requested.connect(self.toggle_split_panel_for_focused_tile)
            self.tiles[tile_id] = tile

            page_index = self._tile_page_index(tile_id)
            slot_index = tile_id % TILES_PER_PAGE
            self.page_grids[page_index].place_tile(tile, slot_index)

    def on_tile_state_changed(self, state_object: object) -> None:
        if not isinstance(state_object, TileState):
            return

        if 0 <= state_object.tile_id < len(self.app_state.tiles):
            self.app_state.tiles[state_object.tile_id] = state_object

        self.focus_view.refresh_slots(self.app_state.tiles, self._focused_tile_id)
        self.page_matrix.refresh_all_slots(self.app_state.tiles)
        self._refresh_top_state()

    def _tile_page_index(self, tile_id: int) -> int:
        return max(0, min(PAGE_COUNT - 1, tile_id // TILES_PER_PAGE))

    def _show_page_for_tile(self, tile_id: int) -> None:
        self._last_selected_tile_id = tile_id
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"
        self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        if self._focused_tile_id is None:
            self._show_active_workspace()

    def show_tile_page(self, page_index: int) -> None:
        self.app_state.current_page_index = max(0, min(PAGE_COUNT - 1, page_index))
        self.app_state.active_view = "tiles"
        if self._focused_tile_id is None:
            self._show_active_workspace()
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        self._refresh_top_state()

    def show_run_page(self) -> None:
        self.app_state.active_view = "run"
        if self._focused_tile_id is None:
            self._show_active_workspace()
        self._refresh_top_state()

    def activate_memory_slot(self, tile_id: int) -> None:
        tile_id = max(0, min(TILE_COUNT - 1, tile_id))
        keep_split = self.focus_view.is_split_panel_visible()
        self._show_page_for_tile(tile_id)
        self._refresh_top_state()
        QTimer.singleShot(
            0,
            lambda tid=tile_id, keep=keep_split: self.enter_focus_mode(
                tid, show_split_panel=keep
            ),
        )

    def toggle_split_panel_for_focused_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None:
            return
        if tile_id != self._focused_tile_id:
            return
        self.focus_view.toggle_split_panel()
        self._refresh_top_state()

    def enter_focus_mode(self, tile_id: int, show_split_panel: bool = False) -> None:
        if tile_id not in self.tiles:
            return

        if (
            self._focused_tile_id == tile_id
            and self.main_stack.currentWidget() is self.focus_view
        ):
            if show_split_panel:
                self.focus_view.show_split_panel()
            else:
                self.focus_view.hide_split_panel()
            self._refresh_top_state()
            return

        self._show_page_for_tile(tile_id)
        self.page_stack.setCurrentIndex(self._tile_page_index(tile_id))

        if self._focused_tile_id is None:
            self._detach_tile_from_grid(tile_id)
        else:
            previous_tile_id = self._focused_tile_id
            self._return_tile_to_grid(previous_tile_id)
            if previous_tile_id != tile_id:
                self._detach_tile_from_grid(tile_id)

        self._focused_tile_id = tile_id
        self._last_selected_tile_id = tile_id
        self.app_state.focused_tile_id = tile_id
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"

        tile = self.tiles[tile_id]
        self.focus_view.set_tile_widget(tile)
        if show_split_panel:
            self.focus_view.show_split_panel()
        else:
            self.focus_view.hide_split_panel()
        self.main_stack.setCurrentWidget(self.focus_view)
        self._sync_focus_flags()
        self._refresh_top_state()

    def switch_focus_tile(self, tile_id: int) -> None:
        keep_split = self.focus_view.is_split_panel_visible()
        self.enter_focus_mode(tile_id, show_split_panel=keep_split)

    def exit_focus_mode(self, *_args) -> None:
        if self._focused_tile_id is None:
            return
        self._return_tile_to_grid(self._focused_tile_id)
        self.focus_view.clear_tile_widget()
        self.focus_view.hide_split_panel()
        self._focused_tile_id = None
        self.app_state.focused_tile_id = None
        self._show_active_workspace()
        self._sync_focus_flags()
        self._refresh_top_state()

    def _detach_tile_from_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        if tile.parent() is self.focus_view.main_panel:
            return
        self.page_grids[self._tile_page_index(tile_id)].remove_tile(tile)

    def _return_tile_to_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        self.focus_view.clear_tile_widget()
        self.page_stack.setCurrentIndex(self._tile_page_index(tile_id))
        self.page_grids[self._tile_page_index(tile_id)].place_tile(
            tile, tile_id % TILES_PER_PAGE
        )

    def _show_active_workspace(self) -> None:
        self.main_stack.setCurrentWidget(self.page_stack)
        if self.app_state.active_view == "run":
            self.page_stack.setCurrentIndex(RUN_PAGE_INDEX)
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)

    def _sync_focus_flags(self) -> None:
        in_focus_view = self.main_stack.currentWidget() is self.focus_view
        split_visible = self.focus_view.is_split_panel_visible()

        for tile_id, tile in self.tiles.items():
            is_active = tile_id == self._focused_tile_id
            if tile.state.is_focused != is_active:
                tile.set_focus_flag(is_active)
            tile.set_toolbar_focus_mode(in_focus_view and is_active)
            tile.set_split_button_active(in_focus_view and is_active and split_visible)

        self.app_state.tiles = [
            replace(tile.state) for _, tile in sorted(self.tiles.items())
        ]
        self.focus_view.refresh_slots(self.app_state.tiles, self._focused_tile_id)
        self.page_matrix.refresh_all_slots(self.app_state.tiles)

    def _current_matrix_slot(self) -> int | None:
        if self._focused_tile_id is not None:
            return self._focused_tile_id
        if self.app_state.active_view == "run":
            return None
        return self._last_selected_tile_id

    def _refresh_top_state(self) -> None:
        self.page_matrix.refresh_all_slots(self.app_state.tiles)

        loaded = sum(1 for tile in self.app_state.tiles if tile.has_content)
        loading = sum(1 for tile in self.app_state.tiles if tile.is_loading)
        hot = sum(1 for tile in self.app_state.tiles if tile.memory_mb >= 700)

        if self._focused_tile_id is not None:
            prefix = "Split" if self.focus_view.is_split_panel_visible() else "Focus"
            self.mode_label.setText(f"{prefix} - tile {self._focused_tile_id + 1}")
        elif self.app_state.active_view == "run":
            self.mode_label.setText("RUN / Corvo")
        else:
            self.mode_label.setText(
                f"Page {self.app_state.current_page_index + 1} / {PAGE_COUNT}"
            )

        self.summary_label.setText(
            f"{loaded}/{TILE_COUNT} loaded - {loading} loading - {hot} hot memory"
        )
        self.page_matrix.set_active_slot(
            self._current_matrix_slot(),
            run_active=self.app_state.active_view == "run",
        )
        self.focus_exit_button.setEnabled(self._focused_tile_id is not None)

    def _on_split_visibility_changed(self, visible: bool) -> None:
        _ = visible
        self._sync_focus_flags()
        self._refresh_top_state()

    def toggle_global_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText("Fullscreen")
        else:
            self.showFullScreen()
            self.fullscreen_button.setText("Exit fullscreen")

    def resizeEvent(self, event) -> None:
        self.app_state.window_size = self.size()
        super().resizeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.app_state.window_size = self.size()
        super().closeEvent(event)

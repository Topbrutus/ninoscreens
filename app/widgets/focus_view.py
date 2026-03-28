
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from app.config import APP_MARGIN
from app.state import TileState
from app.widgets.split_selector import SplitSelectorGrid


class FocusView(QWidget):
    tile_switch_requested = Signal(int)
    split_visibility_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.main_panel = QWidget()
        self.main_panel_layout = QVBoxLayout(self.main_panel)
        self.main_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.main_panel_layout.setSpacing(0)

        self.placeholder = QWidget()
        self.main_panel_layout.addWidget(self.placeholder, 1)

        self.selector_grid = SplitSelectorGrid()
        self.selector_grid.tile_selected.connect(self.tile_switch_requested.emit)
        self.selector_grid.hide()

        self.splitter.addWidget(self.main_panel)
        self.splitter.addWidget(self.selector_grid)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self._apply_default_split_sizes()

    def _apply_default_split_sizes(self) -> None:
        self.splitter.setSizes([980, 420])

    def is_split_panel_visible(self) -> bool:
        return self.selector_grid.isVisible()

    def show_split_panel(self) -> None:
        self.selector_grid.show()
        self._apply_default_split_sizes()
        self.split_visibility_changed.emit(True)

    def hide_split_panel(self) -> None:
        self.selector_grid.hide()
        self.splitter.setSizes([1, 0])
        self.split_visibility_changed.emit(False)

    def toggle_split_panel(self) -> None:
        if self.selector_grid.isVisible():
            self.hide_split_panel()
        else:
            self.show_split_panel()

    def refresh_slots(self, tiles: list[TileState], active_tile_id: int | None) -> None:
        self.selector_grid.refresh(tiles, active_tile_id)

    def set_tile_widget(self, tile_widget: QWidget) -> None:
        self.clear_tile_widget()
        self.main_panel_layout.addWidget(tile_widget, 1)
        self.placeholder.hide()

    def clear_tile_widget(self) -> None:
        while self.main_panel_layout.count():
            item = self.main_panel_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.main_panel_layout.addWidget(self.placeholder, 1)
        self.placeholder.show()

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QWidget, QSizePolicy

from app.config import APP_MARGIN, GRID_COLUMNS, GRID_ROWS, GRID_SPACING


class DashboardGrid(QWidget):
    """Responsive 3x3 grid that hosts all tile widgets."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.layout_ = QGridLayout(self)
        self.layout_.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        self.layout_.setSpacing(GRID_SPACING)

        for row in range(GRID_ROWS):
            self.layout_.setRowStretch(row, 1)
        for col in range(GRID_COLUMNS):
            self.layout_.setColumnStretch(col, 1)

    def place_tile(self, tile: QWidget, tile_id: int) -> None:
        row = tile_id // GRID_COLUMNS
        col = tile_id % GRID_COLUMNS
        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout_.addWidget(tile, row, col)

    def remove_tile(self, tile: QWidget) -> None:
        self.layout_.removeWidget(tile)

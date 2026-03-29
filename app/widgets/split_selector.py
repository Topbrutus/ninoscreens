from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.config import APP_MARGIN, TILE_COUNT
from app.state import TileState
from app.widgets.thumbnail_rail import ThumbnailCard


_SPLIT_SELECTOR_COLUMNS = 2


class SplitSelectorGrid(QFrame):
    tile_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SplitSelectorGrid")
        self.setMinimumWidth(360)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        outer.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)

        self.cards: dict[int, ThumbnailCard] = {}
        for tile_id in range(TILE_COUNT):
            card = ThumbnailCard(tile_id)
            card.clicked.connect(self.tile_selected.emit)
            self.cards[tile_id] = card
            row = tile_id // _SPLIT_SELECTOR_COLUMNS
            column = tile_id % _SPLIT_SELECTOR_COLUMNS
            self.grid.addWidget(card, row, column)

        self.grid.setRowStretch((TILE_COUNT + _SPLIT_SELECTOR_COLUMNS - 1) // _SPLIT_SELECTOR_COLUMNS, 1)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

    def refresh(self, states: list[TileState], active_tile_id: int | None) -> None:
        for state in states:
            card = self.cards.get(state.tile_id)
            if card is not None:
                card.update_from_state(state, active_tile_id == state.tile_id)

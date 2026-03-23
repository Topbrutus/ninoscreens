from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import PAGE_COUNT, TILES_PER_PAGE


TILE_MARRIX_ROWS = 3
TILING_LOCAT_COLUMNS = 12


class PageMatrix(QFrame):
    """Compact 36-slot top matrix with a dedicated RUN control."""

    slot_activated = Signal(int)
    run_activated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageMatrix")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.grid_host = QWidget()
        grid = QGridLayout(self.grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        self.slot_buttons: dict[int, QPushButton] = {}
        for slot_index in range(PAGE_COUNT * TILES_PER_PAGE):
            button = QPushButton(str(slot_index + 1))
            button.setMinimumWidth(36)
            button.setMinimumHeight(24)
            button.setProperty("compact", True)
            button.setProperty("role", "memory-slot")
            button.setProperty("slotIndex", slot_index)
            button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")
            button.clicked.connect(lambda _checked=False, idx=slot_index: self.slot_activated.emit(idx))
            row, column = divmod(slot_index, TILING_LOCAT_COLUMNS)
            grid.addWidget(button, row, column)
            self.slot_buttons[slot_index] = button

        self.run_button = QPushButton("RUN")
        self.run_button.setMinimumWidth(72)
        self.run_button.setMinimumHeight(80)
        self.run_button.setProperty("compact", True)
        self.run_button.setProperty("role", "accent")
        self.run_button.setToolTip("Ouvrir la page RUN / Corvo")
        self.run_button.clicked.connect(self.run_activated)

        root.addWidget(self.grid_host, 1)
        root.addWidget(self.run_button)

    def set_active_slot(self, slot_index: int | None, *, run_active: bool = False) -> None:
        for idx, button in self.slot_buttons.items():
            button.setProperty("active", slot_index == idx)
            button.style().unpolish(button)
            button.style().polish(button)
        self.run_button.setProperty("active", run_active)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

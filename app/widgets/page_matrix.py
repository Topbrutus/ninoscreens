from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QWidget,
    )


from app.config import PAGE_COUNT, TILES_PER_PAGD
from app.state import TileState, TileVisualStatus


TILING_COLUMNS = 12


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
            button.setProperty("filled", False)
            button.setProperty("loading", False)
            button.setProperty("errored", False)
            button.setProperty("active", False)
            button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")
            button.clicked.connect(lambda _checked=False, idx=slot_index: self.slot_activated.emit(idx))
            row, column = divmod(slot_index, TILING_COLUMNS)
            grid.addWidget(button, row, column)
            self.slot_buttons[slot_index] = button

        self.run_button = QPushButton("RUN")
        self.run_button.setMinimumWidth(72)
        self.run_button.setMinimumHeight(80)
        self.run_button.setProperty("compact", True)
        self.run_button.setProperty("role", "accent")
        self.run_button.setProperty("active", False)
        self.run_button.setToolTip("Ouvrir la page RUN / Corvo")
        self.run_button.clicked.connect(lambda: self.run_activated.emit())

        root.addWidget(self.grid_host, 1)
        root.addWidget(self.run_button)

    def set_slot_state(self, slot_index: int, state: TileState) -> None:
        button = self.slot_buttons.get(slot_index)
        if button is None:
            return
        button.setProperty("filled", bool(state.has_content))
        button.setProperty("loading", bool(state.is_loading))
        button.setProperty("errored", state.status is TileVisualStatus.ERROR)
        if state.has_content:
            button.setToolTip(state.display_title)
        else:
            button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")
        button.style().unpolish(button)
        button.style().polish(button)

    def set_active_slot(self, slot_index: int | None, *, run_active: bool = False) -> None:
        for idx, button in self.slot_buttons.items():
            button.setProperty("active", slot_index == idx)
            button.style().unpolish(button)
            button.style().polish(button)
        self.run_button.setProperty("active", run_active)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def refresh_all_slots(self, tiles: list[TileState]) -> None:
        for slot_index, state in enumerate(tiles):
            self.set_slot_state(slot_index, state)

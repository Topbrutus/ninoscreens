from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_MARGIN
from app.state import TileState, TileVisualStatus

_SPLIT_COLUMNS = 3
_SPLIT_BUTTON_WIDTH = 68
_SPLIT_BUTTON_HEIGHT = 34
_SPLIT_PANEL_WIDTH = 228


class SplitSlotPanel(QWidget):
    tile_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SplitSlotPanel")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(_SPLIT_PANEL_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.grid_host = QWidget()
        self.grid_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        grid = QGridLayout(self.grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        self.slot_buttons: dict[int, QPushButton] = {}
        for slot_index in range(36):
            button = QPushButton(str(slot_index + 1))
            button.setMinimumWidth(_SPLIT_BUTTON_WIDTH)
            button.setMinimumHeight(_SPLIT_BUTTON_HEIGHT)
            button.setProperty("compact", True)
            button.setProperty("role", "memory-slot")
            button.setProperty("fillState", "empty")
            button.setProperty("borderState", "idle")
            button.setProperty("active", False)
            button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")
            button.clicked.connect(
                lambda _checked=False, idx=slot_index: self.tile_selected.emit(idx)
            )
            row = slot_index // _SPLIT_COLUMNS
            column = slot_index % _SPLIT_COLUMNS
            grid.addWidget(button, row, column)
            self.slot_buttons[slot_index] = button

        root.addWidget(self.grid_host, 0)

    def _fill_state_from_memory(self, state: TileState) -> str:
        if not state.has_content:
            return "empty"
        if state.memory_mb <= 200:
            return "cool"
        if state.memory_mb <= 700:
            return "warm"
        return "hot"

    def refresh(self, tiles: list[TileState], active_tile_id: int | None) -> None:
        for slot_index, button in self.slot_buttons.items():
            if slot_index < len(tiles):
                state = tiles[slot_index]
                fill_state = self._fill_state_from_memory(state)
                if state.status is TileVisualStatus.ERROR:
                    border_state = "error"
                elif state.is_loading:
                    border_state = "working"
                elif state.has_content:
                    border_state = "ready"
                else:
                    border_state = "idle"
                if state.has_content:
                    button.setToolTip(f"{state.display_title} • {state.memory_mb} MB")
                else:
                    button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")
            else:
                fill_state = "empty"
                border_state = "idle"
                button.setToolTip(f"Ouvrir le carreau {slot_index + 1}")

            button.setProperty("fillState", fill_state)
            button.setProperty("borderState", border_state)
            button.setProperty("active", active_tile_id == slot_index)
            button.style().unpolish(button)
            button.style().polish(button)


class FocusView(QWidget):
    """
    Split final layout:
    - active page on the left
    - 36 slot buttons on the right

    The tile keeps its own toolbar, so we do not add another focus header here.
    """

    tile_switch_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        root = QHBoxLayout(self)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(10)

        self.main_panel = QWidget()
        self.main_panel_layout = QVBoxLayout(self.main_panel)
        self.main_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.main_panel_layout.setSpacing(0)

        self.placeholder = QWidget()
        self.main_panel_layout.addWidget(self.placeholder, 1)

        self.rail = SplitSlotPanel()
        self.rail.tile_selected.connect(self.tile_switch_requested.emit)

        root.addWidget(self.main_panel, 1)
        root.addWidget(self.rail, 0)

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

    def set_focus_title(self, text: str) -> None:
        # Kept only for API compatibility with the existing main window.
        _ = text

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.config import APP_MARGIN
from app.widgets.thumbnail_rail import ThumbnailRail


class FocusView(QWidget):
    """
    Minimal focus-mode container.

    The tile itself owns the actionable toolbar. We intentionally keep this view
    visually light so the focused page has as much vertical space as possible.
    """

    tile_switch_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._focus_title = "Mode focus"

        root = QVBoxLayout(self)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.main_panel = QWidget()
        self.main_panel_layout = QVBoxLayout(self.main_panel)
        self.main_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.main_panel_layout.setSpacing(0)

        self.placeholder = QWidget()
        self.main_panel_layout.addWidget(self.placeholder, 1)

        self.rail = ThumbnailRail()
        self.rail.tile_selected.connect(self.tile_switch_requested.emit)

        body.addWidget(self.main_panel, 1)
        body.addWidget(self.rail, 0)

        root.addLayout(body, 1)

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
        self._focus_title = text

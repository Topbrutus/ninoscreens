
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import PAGE_COUNT, TILES_PER_PAGE, TOOLBAR_BUTTON_SIZE


def _alive(widget: Any) -> bool:
    if widget is None:
        return False
    try:
        widget.objectName()
    except RuntimeError:
        return False
    return True


def _polish(widget: QWidget | None) -> None:
    if widget is None:
        return
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _icon_for(tile: Any) -> QIcon | None:
    if tile is None or not getattr(tile, "state", None) or not tile.state.has_content:
        return None
    page = getattr(tile, "_page", None)
    icon_getter = getattr(page, "icon", None)
    if not callable(icon_getter):
        return None
    try:
        icon = icon_getter()
    except TypeError:
        return None
    if icon is None or icon.isNull():
        return None
    return icon


class SplitSelector(QFrame):
    picked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        root.addWidget(host, 1)

        self.buttons: dict[int, QPushButton] = {}
        for tile_id in range(PAGE_COUNT * TILES_PER_PAGE):
            button = QPushButton(str(tile_id + 1))
            button.setProperty("compact", True)
            button.setProperty("role", "memory-slot")
            button.setProperty("fillState", "empty")
            button.setProperty("borderState", "idle")
            button.setProperty("active", False)
            button.setMinimumSize(42, 34)
            button.clicked.connect(lambda _checked=False, tid=tile_id: self.picked.emit(tid))
            row, col = divmod(tile_id, TILES_PER_PAGE)
            grid.addWidget(button, row, col)
            self.buttons[tile_id] = button

    def refresh(self, tiles: dict[int, Any], primary_tile_id: int) -> None:
        for tile_id, button in self.buttons.items():
            tile = tiles.get(tile_id)
            loaded = bool(tile and getattr(tile, "state", None) and tile.state.has_content)
            button.setEnabled(loaded and tile_id != primary_tile_id)
            button.setProperty("fillState", "cool" if loaded else "empty")
            button.setProperty("borderState", "ready" if loaded else "idle")
            button.setText(str(tile_id + 1))
            icon = _icon_for(tile)
            button.setIcon(icon if icon else QIcon())
            if icon:
                button.setIconSize(QSize(16, 16))
            button.setToolTip(
                "Page principale actuelle"
                if tile_id == primary_tile_id
                else (tile.state.display_title if loaded else f"Carreau {tile_id + 1} vide")
            )
            _polish(button)


class FocusSplit:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.focus_view = window.focus_view
        self.states: dict[int, int | None] = {}
        self.primary_tile_id: int | None = None
        self.secondary_tile_id: int | None = None

        self.panel: QFrame | None = None
        self.stack: QStackedWidget | None = None
        self.selector: SplitSelector | None = None
        self.host: QWidget | None = None
        self.host_layout: QVBoxLayout | None = None

    def install(self) -> None:
        self._install_panel()
        self.timer = QTimer(self.window)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

        for tile in self.window.tiles.values():
            tile.focus_requested.connect(lambda _tile_id: self.sync())
            tile.grid_requested.connect(lambda _tile_id: self.sync())
            tile.state_changed.connect(lambda _state: self.sync())

        self.focus_view.tile_switch_requested.connect(lambda _tile_id: self.sync())
        self.window.main_stack.currentChanged.connect(lambda _index: self.sync())
        self.window.page_stack.currentChanged.connect(lambda _index: self.sync())
        self.window.focus_exit_button.clicked.connect(self.sync)
        self.sync()

    def _install_panel(self) -> None:
        root_layout = self.focus_view.layout()
        body_layout = root_layout.itemAt(0).layout() if root_layout and root_layout.count() else None
        if body_layout is None:
            return

        self.panel = QFrame()
        self.panel.setObjectName("SplitRightPanel")

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        self.stack = QStackedWidget()

        self.selector = SplitSelector()
        self.selector.picked.connect(self.pick_secondary)

        self.host = QWidget()
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(0)

        self.stack.addWidget(self.selector)
        self.stack.addWidget(self.host)
        panel_layout.addWidget(self.stack, 1)

        body_layout.insertWidget(1, self.panel, 1)
        self.panel.hide()

    def tick(self) -> None:
        self.ensure_split_buttons()
        self.ensure_secondary_close_buttons()
        self.sync()
        self.refresh_split_buttons()

    def ensure_split_buttons(self) -> None:
        for tile in self.window.tiles.values():
            if getattr(tile, "_browser_container", None) is None:
                continue
            button = getattr(tile, "_split_btn", None)
            if _alive(button):
                continue

            container = tile._browser_container
            container_layout = container.layout() if container else None
            if container_layout is None or container_layout.count() == 0:
                continue

            header = container_layout.itemAt(0).widget()
            header_layout = header.layout() if header else None
            if header_layout is None:
                continue

            button = QPushButton("Split")
            button.setProperty("compact", True)
            button.setProperty("role", "accent")
            button.setFixedHeight(TOOLBAR_BUTTON_SIZE.height())
            button.setMinimumWidth(58)
            button.clicked.connect(lambda _checked=False, tid=tile.tile_id: self.toggle_split(tid))

            close_button = getattr(tile, "close_button", None)
            insert_index = header_layout.indexOf(close_button)
            header_layout.insertWidget(insert_index if insert_index >= 0 else header_layout.count(), button)
            tile._split_btn = button

    def ensure_secondary_close_buttons(self) -> None:
        for tile in self.window.tiles.values():
            if getattr(tile, "_browser_container", None) is None:
                continue
            button = getattr(tile, "_secondary_split_close_btn", None)
            if _alive(button):
                continue

            container = tile._browser_container
            container_layout = container.layout() if container else None
            if container_layout is None or container_layout.count() == 0:
                continue

            header = container_layout.itemAt(0).widget()
            header_layout = header.layout() if header else None
            if header_layout is None:
                continue

            button = QPushButton("X")
            button.setProperty("compact", True)
            button.setProperty("role", "danger")
            button.setFixedSize(TOOLBAR_BUTTON_SIZE)
            button.setToolTip("Fermer la page de droite et revenir au sélecteur")
            button.hide()
            button.clicked.connect(self.return_to_selector)

            close_button = getattr(tile, "close_button", None)
            insert_index = header_layout.indexOf(close_button)
            header_layout.insertWidget(insert_index if insert_index >= 0 else header_layout.count(), button)
            tile._secondary_split_close_btn = button

    def refresh_split_buttons(self) -> None:
        for tile in self.window.tiles.values():
            button = getattr(tile, "_split_btn", None)
            if not _alive(button):
                continue

            visible = (
                bool(tile.state.has_content)
                and bool(getattr(tile, "_toolbar_focus_mode", False))
                and not bool(getattr(tile, "_in_secondary_split", False))
                and self.window.main_stack.currentWidget() is self.focus_view
                and self.window._focused_tile_id == tile.tile_id
            )
            button.setVisible(visible)

            active = self.primary_tile_id == tile.tile_id and tile.tile_id in self.states
            button.setProperty("role", "nav" if active else "accent")
            button.setToolTip("Fermer complètement le split" if active else "Ouvrir un split")
            _polish(button)

    def sync(self) -> None:
        current_primary = (
            self.window._focused_tile_id
            if self.window.main_stack.currentWidget() is self.focus_view
            else None
        )

        if current_primary != self.primary_tile_id:
            self.detach_secondary()
            self.primary_tile_id = current_primary

        if current_primary is None:
            self.hide_panel()
            return

        state = self.states.get(current_primary, "__off__")
        if state == "__off__":
            self.hide_panel()
            return
        if state is None:
            self.show_selector(current_primary)
            return
        self.show_secondary(current_primary, state)

    def toggle_split(self, tile_id: int) -> None:
        if tile_id != self.primary_tile_id:
            return

        if tile_id in self.states:
            self.detach_secondary()
            self.states.pop(tile_id, None)
            self.hide_panel()
        else:
            self.states[tile_id] = None
            self.show_selector(tile_id)

        self.refresh_split_buttons()

    def pick_secondary(self, secondary_tile_id: int) -> None:
        if self.primary_tile_id is None:
            return
        self.states[self.primary_tile_id] = secondary_tile_id
        self.show_secondary(self.primary_tile_id, secondary_tile_id)
        self.refresh_split_buttons()

    def return_to_selector(self) -> None:
        if self.primary_tile_id is None:
            return
        self.states[self.primary_tile_id = None
        self.show_selector(self.primary_tile_id)
        self.refresh_split_buttons()

    def show_selector(self, primary_tile_id: int) -> None:
        if not self.panel or not self.stack or not self.selector:
            return
        self.detach_secondary()
        self.selector.refresh(self.window.tiles, primary_tile_id)
        self.stack.setCurrentWidget(self.selector)
        self.panel.show()

    def show_secondary(self, primary_tile_id: int, secondary_tile_id: int) -> None:
        if not self.panel or not self.stack or not self.host or not self.host_layout:
            return

        if secondary_tile_id == primary_tile_id:
            self.states[primary_tile_id] = None
            self.show_selector(primary_tile_id)
            return

        secondary_tile = self.window.tiles.get(secondary_tile_id)
        if secondary_tile is None or not secondary_tile.state.has_content:
            self.states[primary_tile_id] = None
            self.show_selector(primary_tile_id)
            return

        if self.secondary_tile_id != secondary_tile_id:
            self.detach_secondary()
            self.window._detach_tile_from_grid(secondary_tile_id)
            self.set_secondary_mode(secondary_tile, True)
            self.clear_host()
            self.host_layout.addWidget(secondary_tile, 1)
            self.secondary_tile_id = secondary_tile_id

        self.stack.setCurrentWidget(self.host)
        self.panel.show()

    def clear_host(self) -> None:
        if self.host_layout is None:
            return
        while self.host_layout.count():
            item = self.host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def detach_secondary(self) -> None:
        if self.secondary_tile_id is None:
            self.clear_host()
            return

        secondary_tile_id = self.secondary_tile_id
        secondary_tile = self.window.tiles.get(secondary_tile_id)
        self.clear_host()

        if secondary_tile is not None:
            self.set_secondary_mode(secondary_tile, False)
            self.window.page_grids[self.window._tile_page_index(secondary_tile_id)].place_tile(
                secondary_tile,
                secondary_tile_id % TILES_PER_PAGE,
            )

        self.secondary_tile_id = None

    def set_secondary_mode(self, tile: Any, enabled: bool) -> None:
        tile._in_secondary_split = enabled

        for name in ("memory_button", "focus_button", "close_button"):
            widget = getattr(tile, name, None)
            if _alive(widget):
                widget.setVisible(not enabled)

        split_button = getattr(tile, "_split_btn", None)
        if _alive(split_button):
            split_button.setVisible(False)

        secondary_close = getattr(tile, "_secondary_split_close_btn", None)
        if _alive(secondary_close):
            secondary_close.setVisible(enabled)

    def hide_panel(self) -> None:
        self.detach_secondary()
        if self.panel:
            self.panel.hide()


def apply_runtime_focus_split(window: Any) -> None:
    window._focus_split = FocusSplit(window)
    window._focus_split.install()

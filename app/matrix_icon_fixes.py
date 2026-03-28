from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, QTimer


_ICON_SIZE = QSize(16, 16)


def _apply_matrix_icons(window: Any) -> None:
    page_matrix = getattr(window, "page_matrix", None)
    tiles = getattr(window, "tiles", None)
    if page_matrix is None or not isinstance(tiles, dict):
        return

    slot_buttons = getattr(page_matrix, "slot_buttons", None)
    if not isinstance(slot_buttons, dict):
        return

    for tile_id, tile in tiles.items():
        button = slot_buttons.get(tile_id)
        if button is None:
            continue

        icon = None
        page = getattr(tile, "_page", None)
        icon_getter = getattr(page, "icon", None) if page is not None else None
        if getattr(tile.state, "has_content", False) and callable(icon_getter):
            try:
                candidate = icon_getter()
            except TypeError:
                candidate = None
            if candidate is not None and not candidate.isNull():
                icon = candidate

        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(_ICON_SIZE)
            button.setText("")
        else:
            button.setIcon(type(button.icon())())
            button.setText(str(tile_id + 1))

        button.style().unpolish(button)
        button.style().polish(button)


def apply_runtime_matrix_icon_fixes(window: Any) -> None:
    _apply_matrix_icons(window)

    timer = QTimer(window)
    timer.setInterval(500)
    timer.timeout.connect(lambda: _apply_matrix_icons(window))
    timer.start()

    window._runtime_matrix_icon_fix_timer = timer

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer


_BAD_TO_GOOD = {
    "â¬…ø®": "⬅️",
    "â¬ï¸": "⬅️",
    "âž¡ï¸": "➡️",
    "ðŸ”„": "🔄",
    "âž–": "➖",
    "âž•": "➕",
    "ðŸ’¾": "💾",
    "ðŸŽ¯": "🎯",
    "ðŸ§©": "🧩",
    "âŒ": "❌",
    "ðŸš  Charger": "🚀 Charger",
    "MÃ©moriser": "Mémoriser",
    "mÃ©moire": "mémoire",
    "Ã©": "é",
    "Ã¨": "è",
    "Ã ": "à",
    "Ã ": "à",
    "Ãª": "ê",
    "Ã´": "ô",
    "Ã»": "û",
}


def _repair_text(value: str) -> str:
    text = value or ""
    for bad, good in _BAD_TO_GOOD.items():
        text = text.replace(bad, good)

    if any(token in text for token in ("Ã", "â", "ð")):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            repaired = text
        else:
            text = repaired

    return text


def _repolish(widget: Any) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _fix_button(button: Any, *, text: str | None = None, tooltip: str | None = None, role: str | None = None) -> None:
    if button is None:
        return

    if text is not None and button.text() != text:
        button.setText(text)

    if tooltip is not None and button.toolTip() != tooltip:
        button.setToolTip(tooltip)

    if role is not None and button.property("role") != role:
        button.setProperty("role", role)
        _repolish(button)


def _fix_tile(tile: Any) -> None:
    _fix_button(getattr(tile, "back_button", None), text="⬅️", tooltip="Retour", role="nav")
    _fix_button(getattr(tile, "forward_button", None), text="➡️", tooltip="Avancer", role="nav")
    _fix_button(getattr(tile, "reload_button", None), text="🔄", tooltip="Recharger", role="nav")
    _fix_button(getattr(tile, "zoom_out_button", None), text="➖", tooltip="Zoom -", role="zoom")
    _fix_button(getattr(tile, "zoom_in_button", None), text="➕", tooltip="Zoom +", role="zoom")
    _fix_button(
        getattr(tile, "memory_button", None),
        text="💾",
        tooltip="Mémoriser maintenant ce carreau",
        role="memory",
    )
    _fix_button(getattr(tile, "close_button", None), text="❌", tooltip="Fermer ce carreau", role="danger")
    _fix_button(getattr(tile, "empty_load_button", None), text="🚀 Charger", role="accent")

    focus_button = getattr(tile, "focus_button", None)
    if focus_button is not None:
        in_focus_mode = bool(getattr(tile, "_toolbar_focus_mode", False))
        if in_focus_mode:
            _fix_button(focus_button, text="🧩", tooltip="Revenir à la grille", role="nav")
        else:
            _fix_button(focus_button, text="🎯", tooltip="Ouvrir ce carreau en mode focus", role="accent")

    state = getattr(tile, "_state", None)
    if state is not None and isinstance(getattr(state, "error_message", None), str):
        state.error_message = _repair_text(state.error_message)

    error_banner = getattr(tile, "error_banner", None)
    if error_banner is not None:
        repaired = _repair_text(error_banner.text())
        if error_banner.text() != repaired:
            error_banner.setText(repaired)

    empty_error_label = getattr(tile, "empty_error_label", None)
    if empty_error_label is not None:
        repaired = _repair_text(empty_error_label.text())
        if empty_error_label.text() != repaired:
            empty_error_label.setText(repaired)


def _fix_main_window(window: Any) -> None:
    app_state = getattr(window, "app_state", None)
    tiles = list(getattr(app_state, "tiles", []) or [])

    loaded = sum(1 for tile in tiles if getattr(tile, "has_content", False))
    loading = sum(1 for tile in tiles if getattr(tile, "is_loading", False))
    hot = sum(1 for tile in tiles if getattr(tile, "memory_mb", 0) >= 700)

    summary_label = getattr(window, "summary_label", None)
    if summary_label is not None:
        summary_text = f"{loaded}/{getattr(window, 'TILE_COUNT', None) or 9} chargés • {loading} en chargement • {hot} rouges mémoire"
        summary_label.setText(summary_text)

    fullscreen_button = getattr(window, "fullscreen_button", None)
    if fullscreen_button is not None:
        fullscreen_text = "Quitter plein écran" if window.isFullScreen() else "Plein écran"
        _fix_button(fullscreen_button, text=fullscreen_text, role="accent")

    mode_label = getattr(window, "mode_label", None)
    if mode_label is not None:
        repaired = _repair_text(mode_label.text())
        if mode_label.text() != repaired:
            mode_label.setText(repaired)

    for attr_name in ("window_title_label", "summary_label", "mode_label"):
        widget = getattr(window, attr_name, None)
        if widget is None:
            continue
        repaired = _repair_text(widget.text())
        if widget.text() != repaired:
            widget.setText(repaired)


def _tick(window: Any) -> None:
    _fix_main_window(window)
    for tile in getattr(window, "tiles", {}).values():
        _fix_tile(tile)


def apply_runtime_text_fixes(window: Any) -> None:
    _tick(window)

    timer = QTimer(window)
    timer.setInterval(400)
    timer.timeout.connect(lambda: _tick(window))
    timer.start()

    window._runtime_text_fix_timer = timer

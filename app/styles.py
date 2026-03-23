from __future__ import annotations

from app.config import PALETTE


def build_app_stylesheet() -> str:
    """Central application stylesheet."""
    p = PALETTE
    return f"""
    QWidget {{
        background: {p.app_bg};
        color: {p.text_primary};
        font-size: 13px;
    }}

    QMainWindow {{
        background: {p.app_bg};
    }}

    QLabel {{
        color: {p.text_primary};
    }}

    QLineEdit, QComboBox {{
        background: {p.panel_bg_alt};
        border: 1px solid {p.panel_border};
        border-radius: 7px;
        padding: 5px 8px;
        color: {p.text_primary};
        selection-background-color: {p.accent};
    }}

    QLineEdit:focus, ComboBox:focus {{
        border: 1px solid {p.accent};
    }}

    QLineEdit#BrowserUrlEdit {{
        padding: 3px 8px;
    }}

    QPushButton, QToolButton {{
        background: {p.panel_bg_alt};
        border: 1px solid {p.panel_border};
        border-radius: 7px;
        color: {p.text_primary};
        padding: 5px 8px;
    }}

    QPushButton[compact="true"], QToolButton[compact="true"] {{
        padding: 3px 6px;
    }}

    QPushButton[role="nav"], QToolButton[role="nav"] {{
        background: #223246;
        border-color: #34506f;
    }}

    QPushButton[role="zoom"], QToolButton[role="zoom"] {{
        background: #2a3042;
        border-color: #4a5370;
    }}

    QPushButton[role="accent"], QToolButton[role="accent"] {{
        background: #21415f;
        border-color: #3b6e9e;
    }}

    QPushButton[role="memory"], QToolButton[role="memory"] {{
        background: #1f4a74;
        border-color: #4b86be;
    }}

    QPushButton[role="memory-slot"], QToolButton[role="memory-slot"] {{
        background: #1d3651;
        border-color: #335a84;
        font-weight: 600;
    }}

    QPushButton[fillState="empty"][role="memory-slot"], QToolButton[fillState="empty"][role="memory-slot"] {{
        background: #1d3651;
    }}

    QPushButton[fillState="cool"][role="memory-slot"], QToolButton[fillState="cool"][role="memory-slot"] {{
        background: #1f4a74;
    }}

    QPushButton[fillState="warm"][role="memory-slot"], QToolButton[fillState="warm"][role="memory-slot"] {{
        background: #6a5212;
    }}

    QPushButton[fillState="hot"][role="memory-slot"], QToolButton[fillState="hot"][role="memory-slot"] {{
        background: #6a1f1f;
    }}

    QPushButton[borderState="ready"][role="memory-slot"], QToolButton[borderState="ready"][role="memory-slot"] {{
        border-color: #4caf50;
    }}

    QPushButton[borderState="working"][role="memory-slot"], QToolButton[borderState="working"][role="memory-slot"] {{
        border-color: #f1c40f;
    }}

    QPushButton[borderState="error"][role="memory-slot"], QToolButton[borderState="error"][role="memory-slot"] {{
        border-color: #e74c3c;
    }}

    QPushButton[active="true"][role="memory-slot"], QToolButton[active="true"][role="memory-slot"] {{
        background: #2e6fa9;
        border-color: #8fc2ff;
    }}

    QPushButton[role="danger"], QToolButton[role="danger"] {{
        background: #4a2626;
        border-color: #a34a4a;
    }}

    QPushButton[role="api"][connectionState="idle"] {{
        background: #3a3f46;
        border-color: #596575;
    }}

    QPushButton[role="api"][connectionState="connected"] {{
        background: #5a531f;
        border-color: #d2bb34;
    }}

    QPushButton[role="api"][connectionState="error"] {{
        background: #4a2626;
        border-color: #e74c3c;
    }}

    QPushButton[role="audio"][active="true"] {{
        background: #21415f;
        border-color: #3b6e9e;
    }}

    QPushButton[role="audio"][active="false"] {{
        background: #3a3f46;
        border-color: #596575;
    }}

    QPushButton:hover, QToolButton:hover {{
        background: {p.button_hover};
    }}

    QPushButton[role="nav"]:hover, QToolButton[role="nav"]:hover {{
        background: #2b4260;
    }}

    QPushButton[role="zoom"]:hover, QToolButton[role="zoom"]:hover {{
        background: #38405a;
    }}

    QPushButton[role="accent"]:hover, QToolButton[role="accent"]:hover {{
        background: #2a5377;
    }}

    QPushButton[role="memory"]:hover, QToolButton[role="memory"]:hover {{
        background: #2a5f94;
    }}

    QPushButton[role="memory-slot"]:hover, QToolButton[role="memory-slot"]:hover {{
        background: #274563;
    }}

    QPushButton[fillState="cool"][role="memory-slot"]:hover, QToolButton[fillState="cool"][role="memory-slot"]:hover {{
        background: #285b8b;
    }}

    QPushButton[fillState="warm"][role="memory-slot"]:hover, QToolButton[fillState="warm"][role="memory-slot"]:hover {{
        background: #846515;
    }}

    QPushButton[fillState="hot"][role="memory-slot"]:hover, QToolButton[fillState="hot"][role="memory-slot"]:hover {{
        background: #8a2a2a;
    }}

    QPushButton[borderState="working"][role="memory-slot"]:hover, QToolButton[borderState="working"][role="memory-slot"]:hover {{
        border-color: #f6d365;
    }}

    QPushButton[borderState="error"][role="memory-slot"]:hover, QToolButton[borderState="error"][role="memory-slot"]:hover {{
        border-color: #f0857a;
    }}

    QPushButton[active="true"][role="memory-slot"]:hover, QToolButton[active="true"][role="memory-slot"]:hover {{
        background: #3b84c7;
    }}

    QPushButton[role="danger"]:hover, QToolButton[role="danger"]:hover {{
        background: #633333;
    }}

    QPushButton:pressed, QToolButton:pressed {{
        background: {p.button_pressed};
    }}

    QFrame#TileFrame {{
        background: {p.panel_bg};
        border: 1px solid {p.panel_border};
        border-radius: 12px;
    }}

    QFrame[focused="true"]#TileFrame {{
        border: 1px solid {p.focus_border};
    }}

    QWidget#SileHeader {{
        background: {p.panel_bg_alt};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border-bottom: 1px solid {p.panel_border};
    }}

    QLabel#SecondaryText {{
        color: {p.text_secondary};
    }}

    QLabel#SutedText {{
        color: {p.text_muted};
    }}

    QLabel#ErrorBanner {{
        color: {p.error};
        font-weight: 600;
        padding: 2px 4px;
    }}

    QFrame#FocusPanel,
    QFrame#THumbnailRail,
    QFrame#TopBar,
    QFrame#ControlPanel,
    QFrame#PageMatrix {{
        background: {p.panel_bg};
        border: 1px solid {p.panel_border};
        border-radius: 12px;
    }}

    QFrame#ThumbnailCard {{
        background: {p.panel_bg_alt};
        border: 1px solid {p.panel_border};
        border-radius: 10px;
    }}

    QFrame[active="true"]#ThumbnailCard {{
        border: 1px solid {p.focus_border};
    }}

    QCheckBox {{
        spacing: 8px;
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: {p.panel_bg};
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {p.panel_border};
        border-radius: 5px;
        min-height: 20px;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    """

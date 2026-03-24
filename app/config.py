from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths

APP_NAME = "Multi-Site Dashboard"

PAGE_COUNT = 3
TILES_PER_PAGE = 12
GRID_ROWS = 3
GRID_COLUMNS = 4
TILE_COUNT = PAGE_COUNT * TILES_PER_PAGE
RUN_PAGE_INDEX = PAGE_COUNT

DEFAULT_WINDOW_SIZE = QSize(1600, 980)
MINIMUM_WINDOW_SIZE = QSize(1100, 700)

DEFAULT_ZOOM = 1.0
ZOOM_STEP = 0.10
MIN_ZOOM = 0.50
MAX_ZOOM = 2.50

GRID_SPACING = 10
APP_MARGIN = 10
THUMBNAIL_RAIL_WIDTH = 220
THUMBNAIL_IMAGE_SIZE = QSize(190, 118)
THUMBNAIL_CAPTURE_INTERVAL_MS = 1800
THUMBNAIL_CAPTURE_DELAY_MS = 350
SESSION_SAVE_DEBOUNCE_MS = 350

TOOLBAR_BUTTON_SIZE = QSize(34, 30)
MEMORY_SLOT_BUTTON_SIZE = QSize(32, 30)
URL_BAR_HEIGHT = 30
SESSION_FILENAME = "dashboard_session.json"


@dataclass(frozen=True)
class Palette:
    app_bg: str = "#14171c"
    panel_bg: str = "#1c2128"
    panel_bg_alt: str = "#232a33"
    panel_bg_hover: str = "#28313d"
    panel_border: str = "#313a46"
    focus_border: str = "#4b7bec"
    text_primary: str = "#edf2f7"
    text_secondary: str = "#b8c0cc"
    text_muted: str = "#7f8a99"
    success: str = "#4caf50"
    warning: str = "#f1c40f"
    error: str = "#e74c3c"
    empty: str = "#596575"
    accent: str = "#5dade2"
    button_hover: str = "#364150"
    button_pressed: str = "#455466"


PALETTE = Palette()


def app_data_root() -> Path:
    """Return a writable application data directory."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(location) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_file_path() -> Path:
    return app_data_root() / SESSION_FILENAME


def web_profile_root() -> Path:
    root = app_data_root() / "web_profile"
    root.mkdir(parents=True, exist_ok=True)
    return root

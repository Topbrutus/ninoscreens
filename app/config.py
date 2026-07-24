from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSize

APP_NAME: Final[str] = "Multi-Site Dashboard"

PAGE_COUNT: Final[int] = 3
TILES_PER_PAGE: Final[int] = 12
GRID_ROWS: Final[int] = 3
GRID_COLUMNS: Final[int] = 4
TILE_COUNT: Final[int] = PAGE_COUNT * TILES_PER_PAGE
RUN_PAGE_INDEX: Final[int] = PAGE_COUNT

DEFAULT_WINDOW_SIZE: Final[QSize] = QSize(1600, 980)
MINIMUM_WINDOW_SIZE: Final[QSize] = QSize(1100, 700)

DEFAULT_ZOOM: Final[float] = 1.0
ZOOM_STEP: Final[float] = 0.10
MIN_ZOOM: Final[float] = 0.50
MAX_ZOOM: Final[float] = 2.50

GRID_SPACING: Final[int] = 10
APP_MARGIN: Final[int] = 10
THUMBNAIL_RAIL_WIDTH: Final[int] = 220
THUMBNAIL_IMAGE_SIZE: Final[QSize] = QSize(190, 118)
THUMBNAIL_CAPTURE_INTERVAL_MS: Final[int] = 1800
THUMBNAIL_CAPTURE_DELAY_MS: Final[int] = 350
SESSION_SAVE_DEBOUNCE_MS: Final[int] = 350

TOOLBAR_BUTTON_SIZE: Final[QSize] = QSize(34, 30)
MEMORY_SLOT_BUTTON_SIZE: Final[QSize] = QSize(32, 30)
URL_BAR_HEIGHT: Final[int] = 30
SESSION_FILENAME: Final[str] = "dashboard_session.json"
DATA_ROOT_ENV_VAR: Final[str] = "NINO_DATA_ROOT"
DEFAULT_APPDATA_ROOT: Final[Path] = Path(r"D:\runtime\profiles\nino\appdata")
LOG_FILENAME: Final[str] = "ninoscreens.log"
LOG_MAX_BYTES: Final[int] = 5 * 1024 * 1024
LOG_BACKUP_COUNT: Final[int] = 3
LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DEFAULT_LOGGER_NAME: Final[str] = "app"
_MANAGED_HANDLER_ATTR: Final[str] = "_ninoscreens_managed_handler"


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
    root_override = os.environ.get(DATA_ROOT_ENV_VAR, "").strip()
    if root_override:
        path = Path(root_override) / "appdata"
    else:
        path = DEFAULT_APPDATA_ROOT
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    """Return the application log directory."""

    return app_data_root() / "logs"


def _managed_logging_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        handler
        for handler in logger.handlers
        if getattr(handler, _MANAGED_HANDLER_ATTR, False)
    ]


def _prepare_logging_handler(handler: logging.Handler) -> logging.Handler:
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    return handler


def configure_logging(
    log_directory: Path | None = None,
    *,
    logger_name: str = DEFAULT_LOGGER_NAME,
    level: int = logging.INFO,
) -> Path | None:
    """Configure application logging once without removing external handlers."""

    logger = logging.getLogger(logger_name)
    if logger.level == logging.NOTSET:
        logger.setLevel(level)

    existing_handlers = _managed_logging_handlers(logger)
    if existing_handlers:
        existing_handler = existing_handlers[0]
        if isinstance(existing_handler, RotatingFileHandler):
            return Path(existing_handler.baseFilename)
        return None

    try:
        directory = log_directory if log_directory is not None else log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / LOG_FILENAME
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as exc:
        handler = logging.StreamHandler(sys.stderr)
        logger.addHandler(_prepare_logging_handler(handler))
        logger.warning(
            "File logging unavailable; using stderr fallback: %s",
            exc.__class__.__name__,
        )
        return None

    logger.addHandler(_prepare_logging_handler(handler))
    return log_path


def session_file_path() -> Path:
    return app_data_root() / SESSION_FILENAME


def web_profile_root() -> Path:
    root = app_data_root() / "web_profile"
    root.mkdir(parents=True, exist_ok=True)
    return root

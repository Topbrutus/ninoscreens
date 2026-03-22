from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap

from app.config import DEFAULT_ZOOM, TILE_COUNT


class TileVisualStatus(str, Enum):
    EMPTY = "empty"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class TileState:
    tile_id: int
    current_url: str = ""
    title: str = ""
    domain: str = ""
    has_content: bool = False
    is_loading: bool = False
    is_focused: bool = False
    zoom_factor: float = DEFAULT_ZOOM
    error_message: str = ""
    status: TileVisualStatus = TileVisualStatus.EMPTY
    thumbnail: Optional[QPixmap] = None
    thumbnail_revision: int = 0

    @property
    def display_title(self) -> str:
        if self.title.strip():
            return self.title.strip()
        if self.domain.strip():
            return self.domain.strip()
        if self.current_url.strip():
            return self.current_url.strip()
        return f"Carreau {self.tile_id + 1}"


@dataclass
class AppState:
    tiles: list[TileState] = field(default_factory=lambda: [TileState(tile_id=i) for i in range(TILE_COUNT)])
    focused_tile_id: Optional[int] = None
    is_fullscreen: bool = False
    window_size: QSize | None = None

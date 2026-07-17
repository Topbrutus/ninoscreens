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
    memory_mb: int = 0
    thumbnail: Optional[QPixmap] = None
    thumbnail_revision: int = 0
    site_icon: Optional[QPixmap] = None

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
    slot_to_tile_id: list[int] = field(default_factory=lambda: list(range(TILE_COUNT)))
    tile_id_to_slot: list[int] = field(default_factory=lambda: list(range(TILE_COUNT)))
    focused_tile_id: Optional[int] = None
    is_fullscreen: bool = False
    window_size: QSize | None = None
    current_page_index: int = 0
    active_view: str = "tiles"
    last_selected_tile_id: int = 0
    split_panel_visible: bool = False
    bridge_target_tile_id: Optional[int] = None


def _normalize_identity_order(tile_count: int) -> list[int]:
    return list(range(tile_count))


def derive_tile_id_to_slot(slot_to_tile_id: list[int], tile_count: int = TILE_COUNT) -> list[int]:
    tile_id_to_slot = [-1] * tile_count
    if len(slot_to_tile_id) != tile_count:
        return _normalize_identity_order(tile_count)

    seen_tiles: set[int] = set()
    for slot_index, raw_tile_id in enumerate(slot_to_tile_id):
        try:
            tile_id = int(raw_tile_id)
        except (TypeError, ValueError):
            return _normalize_identity_order(tile_count)
        if tile_id < 0 or tile_id >= tile_count or tile_id in seen_tiles:
            return _normalize_identity_order(tile_count)
        tile_id_to_slot[tile_id] = slot_index
        seen_tiles.add(tile_id)

    if any(slot_index < 0 for slot_index in tile_id_to_slot):
        return _normalize_identity_order(tile_count)
    return tile_id_to_slot


def derive_slot_to_tile_id(tile_id_to_slot: list[int], tile_count: int = TILE_COUNT) -> list[int]:
    slot_to_tile_id = [-1] * tile_count
    if len(tile_id_to_slot) != tile_count:
        return _normalize_identity_order(tile_count)

    seen_slots: set[int] = set()
    for tile_id, raw_slot in enumerate(tile_id_to_slot):
        try:
            slot_index = int(raw_slot)
        except (TypeError, ValueError):
            return _normalize_identity_order(tile_count)
        if slot_index < 0 or slot_index >= tile_count or slot_index in seen_slots:
            return _normalize_identity_order(tile_count)
        slot_to_tile_id[slot_index] = tile_id
        seen_slots.add(slot_index)

    if any(tile_id < 0 for tile_id in slot_to_tile_id):
        return _normalize_identity_order(tile_count)
    return slot_to_tile_id


def normalize_slot_to_tile_id(raw_value: object, tile_count: int = TILE_COUNT) -> list[int]:
    identity = _normalize_identity_order(tile_count)
    if not isinstance(raw_value, list) or len(raw_value) != tile_count:
        return identity

    slot_to_tile_id = [-1] * tile_count
    seen_tiles: set[int] = set()
    for slot_index, raw_tile_id in enumerate(raw_value):
        try:
            tile_id = int(raw_tile_id)
        except (TypeError, ValueError):
            return identity
        if tile_id < 0 or tile_id >= tile_count or tile_id in seen_tiles:
            return identity
        slot_to_tile_id[slot_index] = tile_id
        seen_tiles.add(tile_id)

    return slot_to_tile_id


def swap_slot_order(slot_to_tile_id: list[int], first_tile_id: int, second_tile_id: int, tile_count: int = TILE_COUNT) -> list[int]:
    order = list(slot_to_tile_id)
    if len(order) != tile_count:
        return _normalize_identity_order(tile_count)
    if first_tile_id == second_tile_id:
        return order
    if not (0 <= first_tile_id < tile_count and 0 <= second_tile_id < tile_count):
        return _normalize_identity_order(tile_count)

    try:
        first_slot = order.index(first_tile_id)
        second_slot = order.index(second_tile_id)
    except ValueError:
        return _normalize_identity_order(tile_count)

    if first_slot == second_slot:
        return order

    order[first_slot], order[second_slot] = order[second_slot], order[first_slot]
    return order

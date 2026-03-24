from __future__ import annotations

import json
from typing import Any

from app.config import session_file_path
from app.state import AppState


def load_session_payload() -> dict[str, Any] | None:
    path = session_file_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def save_session_payload(payload: dict[str, Any]) -> None:
    path = session_file_path()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def serialize_app_state(app_state: AppState) -> dict[str, Any]:
    tiles_payload: list[dict[str, Any]] = []
    for tile in app_state.tiles:
        tiles_payload.append(
            {
                "tile_id": tile.tile_id,
                "current_url": tile.current_url,
                "zoom_factor": tile.zoom_factor,
                "has_content": tile.has_content,
            }
        )

    window_payload: dict[str, Any] = {}
    if app_state.window_size is not None:
        window_payload = {
            "width": app_state.window_size.width(),
            "height": app_state.window_size.height(),
        }

    return {
        "schema_version": 2,
        "focused_tile_id": app_state.focused_tile_id,
        "is_fullscreen": app_state.is_fullscreen,
        "current_page_index": app_state.current_page_index,
        "active_view": app_state.active_view,
        "window": window_payload,
        "tiles": tiles_payload,
    }

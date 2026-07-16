from __future__ import annotations

import json
import os
import tempfile
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
    path.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    json.loads(serialized)

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = handle.name

        if temp_path is None:
            raise RuntimeError("Unable to create session temp file")

        with open(temp_path, "r", encoding="utf-8") as handle:
            json.loads(handle.read())

        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


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
        "schema_version": 4,
        "focused_tile_id": app_state.focused_tile_id,
        "is_fullscreen": app_state.is_fullscreen,
        "current_page_index": app_state.current_page_index,
        "active_view": app_state.active_view,
        "last_selected_tile_id": app_state.last_selected_tile_id,
        "split_panel_visible": app_state.split_panel_visible,
        "window": window_payload,
        "tile_positions": list(app_state.tile_positions),
        "tiles": tiles_payload,
    }

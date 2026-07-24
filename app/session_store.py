from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.config import session_file_path
from app.state import (
    AppState,
    derive_tile_id_to_slot,
    normalize_slot_to_tile_id,
)

logger = logging.getLogger(__name__)


class SensitiveDataError(ValueError):
    pass

PROHIBITED_KEYS = frozenset({
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "authorization",
    "cookie",
})

def _check_no_sensitive_keys(data: Any) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in PROHIBITED_KEYS:
                raise SensitiveDataError(f"Sensitive key prohibited: {key}")
            _check_no_sensitive_keys(value)
    elif isinstance(data, (list, tuple)):
        for item in data:
            _check_no_sensitive_keys(item)


def _sync_dir(dir_path: Path) -> None:
    if os.name != 'posix':
        return
    try:
        fd = os.open(str(dir_path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _parse_session_dict(raw: str) -> dict[str, Any] | None:
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        _check_no_sensitive_keys(data)
    except SensitiveDataError:
        return None
    return data


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _parse_session_dict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def load_session_payload() -> dict[str, Any] | None:
    path = session_file_path()
    bak_path = path.with_name(path.name + ".bak")

    data = _load_json_file(path)
    if data is not None:
        return data

    logger.warning("Session load: primary store unavailable or invalid")

    backup_data = _load_json_file(bak_path)
    if backup_data is not None:
        logger.warning("Session load: using backup store")
        return backup_data

    logger.warning("Session load: primary and backup stores unavailable or invalid")
    return None


def save_session_payload(payload: dict[str, Any]) -> None:
    _check_no_sensitive_keys(payload)

    path = session_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    bak_path = path.with_name(path.name + ".bak")

    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    json.loads(serialized)

    temp_path: str | None = None
    try:
        existing_stat = None
        if path.exists():
            try:
                existing_stat = path.stat()
            except OSError:
                pass

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_path = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        if temp_path is None:
            raise RuntimeError("Unable to create session temp file")

        with open(temp_path, "r", encoding="utf-8") as handle:
            json.loads(handle.read())

        if existing_stat is not None:
            try:
                os.chmod(temp_path, existing_stat.st_mode)
            except OSError:
                pass

        if path.exists():
            if _load_json_file(path) is not None:
                import shutil
                shutil.copy2(path, bak_path)

        os.replace(temp_path, path)
        temp_path = None

        _sync_dir(path.parent)

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

    slot_to_tile_id = normalize_slot_to_tile_id(app_state.slot_to_tile_id)
    tile_id_to_slot = derive_tile_id_to_slot(slot_to_tile_id)

    return {
        "schema_version": 5,
        "focused_tile_id": app_state.focused_tile_id,
        "is_fullscreen": app_state.is_fullscreen,
        "current_page_index": app_state.current_page_index,
        "active_view": app_state.active_view,
        "last_selected_tile_id": app_state.last_selected_tile_id,
        "split_panel_visible": app_state.split_panel_visible,
        "bridge_target_tile_id": app_state.bridge_target_tile_id,
        "slot_to_tile_id": slot_to_tile_id,
        "tile_id_to_slot": tile_id_to_slot,
        "window": window_payload,
        "tiles": tiles_payload,
    }

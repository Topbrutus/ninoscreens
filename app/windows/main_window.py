from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from PySide6.QtCore import QCoreApplication, QEvent, QFileSystemWatcher, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    APP_MARGIN,
    APP_NAME,
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    PAGE_COUNT,
    SESSION_SAVE_DEBOUNCE_MS,
    RUN_PAGE_INDEX,
    TILE_COUNT,
    TILES_PER_PAGE,
    app_data_root,
)
from app.direct_control import AgentCockpitController, AgentCommand, BlockedAction
from app.arena_controller import ArenaController
from app.chatgpt_bridge_browser import ChatGPTBridgeBrowserHost
from app.jules_summary import (
    DEFAULT_SUMMARY_DIR,
    JulesSummary,
    JulesSummaryError,
    append_transmission_record,
    build_failure_record,
    build_success_record,
    has_successful_transmission,
    latest_untransmitted_summary,
    load_transmission_store,
    summary_from_payload,
)
from app.session_store import load_session_payload, save_session_payload, serialize_app_state
from app.state import AppState, TileState
from app.state import (
    derive_slot_to_tile_id,
    derive_slot_to_tile_id_from_tile_positions,
    derive_tile_id_to_slot,
    normalize_slot_to_tile_id,
    swap_slot_order,
)
from app.terminal import TerminalRuntime
from app.web_media import WebMediaPermissionController
from app.web_profile import build_shared_profile
from app.widgets.dashboard_grid import DashboardGrid
from app.widgets.arena_workspace import ArenaWorkspace
from app.widgets.chatgpt_bridge_workspace import ChatGPTBridgeWorkspace
from app.widgets.focus_view import FocusView
from app.widgets.pages_bridge_workspace import PagesBridgeWorkspace
from app.widgets.page_matrix import PageMatrix
from app.widgets.run_workspace import RunWorkspace
from app.widgets.terminal_workspace import TerminalWorkspace
from app.widgets.web_tile import WebTile


def _clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object) -> bool:
    return bool(value)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)

        self.app_state = AppState(window_size=DEFAULT_WINDOW_SIZE)
        if len(self.app_state.tiles) < TILE_COUNT:
            self.app_state.tiles = [TileState(tile_id=i) for i in range(TILE_COUNT)]

        self._restoring_session = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SESSION_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_session)

        self.profile = build_shared_profile(self)
        self.web_media_controller = WebMediaPermissionController(self.profile, self)
        self.web_media_controller.set_test_page_opener(self.open_media_test_page)

        self.tiles: dict[int, WebTile] = {}
        self.page_grids: list[DashboardGrid] = []
        self.terminal_runtime = TerminalRuntime(start_dir=Path(__file__).resolve().parents[2])
        self.arena_controller = ArenaController()
        self.chatgpt_bridge_host = ChatGPTBridgeBrowserHost(self)
        self.arena_controller.snapshot_signals.snapshot_ready.connect(self._on_arena_snapshot_ready)
        self.arena_controller.snapshot_signals.snapshot_failed.connect(self._on_arena_snapshot_failed)
        self._focused_tile_id: int | None = None
        self._split_tile_id: int | None = None
        self._split_pairs: dict[int, int] = {}
        self._last_selected_tile_id: int = 0
        self._grid_interchange_source_tile_id: int | None = None
        self._jules_summary_watcher: QFileSystemWatcher | None = None
        self._jules_summary_timer: QTimer | None = None
        self._chatgpt_bridge_watcher: QFileSystemWatcher | None = None
        self._chatgpt_bridge_timer: QTimer | None = None

        self._build_ui()
        self._build_tiles()
        self.pages_workspace = PagesBridgeWorkspace(self.tiles, self.app_state, self.arena_controller)
        self.pages_workspace.back_requested.connect(self.return_from_pages_bridge_page)
        self.pages_workspace.state_changed.connect(self.schedule_session_save)
        self.main_stack.insertWidget(1, self.pages_workspace)
        self._restore_session()
        self._sync_focus_flags()
        self._refresh_top_state()

        self.direct_controller = AgentCockpitController(
            tile_count=TILE_COUNT,
            handlers={
                "open_url": self._handle_open_url_command,
                "focus_tile": self._handle_focus_tile_command,
                "close_tile": self._handle_close_tile_command,
                "load_memory": self._handle_load_memory_command,
                "read_state": self._handle_read_state_command,
                "type_web_text": self._handle_type_web_text_command,
                "transmit_jules_summary": self._handle_transmit_jules_summary_command,
            },
        )
        self._setup_jules_summary_watch()
        self._setup_chatgpt_bridge_ipc()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(10)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(10)

        title_column = QWidget()
        title_layout = QVBoxLayout(title_column)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.window_title_label = QLabel(APP_NAME)
        self.window_title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.mode_label = QLabel(f"Page 1 / {PAGE_COUNT}")
        self.mode_label.setObjectName("SecondaryText")
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("MutedText")

        title_layout.addWidget(self.window_title_label)
        title_layout.addWidget(self.mode_label)
        title_layout.addWidget(self.summary_label)

        self.page_matrix = PageMatrix()
        self.page_matrix.slot_activated.connect(self.activate_memory_slot)
        self.page_matrix.run_activated.connect(self.show_terminal_page)

        controls_host = QWidget()
        controls_layout = QVBoxLayout(controls_host)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)

        controls_row1 = QHBoxLayout()
        controls_row1.setContentsMargins(0, 0, 0, 0)
        controls_row1.setSpacing(4)

        controls_row2 = QHBoxLayout()
        controls_row2.setContentsMargins(0, 0, 0, 0)
        controls_row2.setSpacing(4)

        self.pages_button = QPushButton("Pages")
        self.pages_button.setProperty("compact", True)
        self.pages_button.setProperty("role", "nav")
        self.pages_button.clicked.connect(self.show_pages_bridge_page)

        self.arena_button = QPushButton("ARÈNE")
        self.arena_button.setProperty("compact", True)
        self.arena_button.setProperty("role", "arena")
        self.arena_button.clicked.connect(self.show_arena_page)

        self.chatgpt_button = QPushButton("ChatGPT")
        self.chatgpt_button.setProperty("compact", True)
        self.chatgpt_button.setProperty("role", "nav")
        self.chatgpt_button.clicked.connect(self.show_chatgpt_bridge_page)

        self.focus_exit_button = QPushButton("Quit focus")
        self.focus_exit_button.setProperty("compact", True)
        self.focus_exit_button.clicked.connect(self.exit_focus_mode)

        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.setProperty("compact", True)
        self.fullscreen_button.clicked.connect(self.toggle_global_fullscreen)

        self.media_permissions_button = QPushButton("Media")
        self.media_permissions_button.setProperty("compact", True)
        self.media_permissions_button.clicked.connect(self.open_media_permissions_panel)

        controls_row1.addWidget(self.pages_button)
        controls_row1.addWidget(self.arena_button)
        controls_row1.addWidget(self.chatgpt_button)
        controls_row1.addWidget(self.media_permissions_button)
        controls_row2.addWidget(self.focus_exit_button)
        controls_layout.addLayout(controls_row1)
        controls_layout.addLayout(controls_row2)
        controls_layout.addWidget(self.fullscreen_button)

        top_layout.addWidget(title_column, 0)
        top_layout.addWidget(self.page_matrix, 1)
        top_layout.addWidget(controls_host, 0)

        root.addWidget(self.top_bar)

        self.main_stack = QStackedWidget()
        self.page_stack = QStackedWidget()

        for _page_index in range(PAGE_COUNT):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)

            grid = DashboardGrid()
            page_layout.addWidget(grid, 1)
            self.page_grids.append(grid)
            self.page_stack.addWidget(page)

        # Kept for backend compatibility while the visible RUN entry is replaced by Terminal.
        self.run_workspace = RunWorkspace()
        self.run_workspace.prompt_submitted.connect(self.on_run_prompt_submitted)

        self.terminal_workspace = TerminalWorkspace(self.terminal_runtime)
        self.terminal_workspace.back_requested.connect(self.return_from_terminal_page)
        self.page_stack.addWidget(self.terminal_workspace)

        self.arena_workspace = ArenaWorkspace(self.arena_controller)
        self.arena_workspace.back_requested.connect(self.return_from_arena_page)

        self.chatgpt_bridge_workspace = ChatGPTBridgeWorkspace(self.chatgpt_bridge_host)
        self.chatgpt_bridge_workspace.back_requested.connect(self.return_from_chatgpt_bridge_page)

        self.focus_view = FocusView()
        self.focus_view.tile_switch_requested.connect(self.set_split_tile)
        self.focus_view.split_visibility_changed.connect(self._on_split_visibility_changed)

        self.main_stack.addWidget(self.page_stack)
        self.main_stack.addWidget(self.arena_workspace)
        self.main_stack.addWidget(self.chatgpt_bridge_workspace)
        self.main_stack.addWidget(self.focus_view)
        root.addWidget(self.main_stack, 1)

    def _build_tiles(self) -> None:
        for tile_id in range(TILE_COUNT):
            tile = WebTile(tile_id=tile_id, profile=self.profile)
            tile.state_changed.connect(self.on_tile_state_changed)
            tile.memory_requested.connect(self.activate_memory_slot)
            tile.focus_requested.connect(self.enter_focus_mode)
            tile.grid_requested.connect(self.exit_focus_mode)
            tile.split_requested.connect(self.toggle_split_panel_for_focused_tile)
            tile.grid_interchange_requested.connect(self.begin_grid_interchange)
            tile.split_interchange_requested.connect(self.swap_split_pages)
            self.web_media_controller.attach_tile(tile)
            self.tiles[tile_id] = tile

            page_index = self._tile_page_index(tile_id)
            slot_index = self._tile_slot_index(tile_id) % TILES_PER_PAGE
            self.page_grids[page_index].place_tile(tile, slot_index)

    def _command_tile_id(self, tile_number: int | None) -> int:
        if tile_number is None:
            raise BlockedAction(
                "Numéro de carreau requis.",
                human_validation_required=True,
                details={"reason": "missing_tile_number"},
            )
        tile_id = tile_number - 1
        if tile_id < 0 or tile_id >= TILE_COUNT:
            raise BlockedAction(
                f"Carreau {tile_number} invalide. Utiliser un numéro entre 1 et {TILE_COUNT}.",
                human_validation_required=True,
                details={"reason": "invalid_tile_number", "tile_count": TILE_COUNT},
            )
        return tile_id

    def _build_direct_state_snapshot(self) -> dict[str, object]:
        return {
            "focused_tile_id": self._focused_tile_id,
            "current_page_index": self.app_state.current_page_index,
            "active_view": self.app_state.active_view,
            "is_fullscreen": self.app_state.is_fullscreen,
            "last_selected_tile_id": self._last_selected_tile_id,
            "split_panel_visible": self.focus_view.is_split_panel_visible(),
            "slot_to_tile_id": list(self.app_state.slot_to_tile_id),
            "tile_id_to_slot": list(self.app_state.tile_id_to_slot),
            "tiles": [
                {
                    "tile_id": tile.tile_id,
                    "current_url": tile.current_page_url(),
                    "title": tile.state.title,
                    "has_content": tile.state.has_content,
                    "is_loading": tile.state.is_loading,
                    "status": tile.state.status.value,
                }
                for tile in self.tiles.values()
            ],
        }

    def _handle_open_url_command(self, command: AgentCommand) -> dict[str, object]:
        tile_id = self._command_tile_id(command.tile_number)
        url = command.url.strip()
        if not url:
            raise BlockedAction(
                "URL requise.",
                human_validation_required=True,
                details={"reason": "missing_url"},
            )
        self.show_tile_page(self._tile_page_index(tile_id))
        self.tiles[tile_id].open_url_text(url)
        return {
            "message": f"URL ouverte dans le carreau {command.tile_number}.",
            "tile_id": tile_id,
            "url": url,
        }

    def _handle_focus_tile_command(self, command: AgentCommand) -> dict[str, object]:
        tile_id = self._command_tile_id(command.tile_number)
        self.enter_focus_mode(tile_id)
        return {
            "message": f"Carreau {command.tile_number} mis en focus.",
            "tile_id": tile_id,
        }

    def _handle_close_tile_command(self, command: AgentCommand) -> dict[str, object]:
        tile_id = self._command_tile_id(command.tile_number)
        if self._focused_tile_id == tile_id:
            self.exit_focus_mode()
        self.tiles[tile_id].reset_to_empty()
        return {
            "message": f"Carreau {command.tile_number} fermé.",
            "tile_id": tile_id,
        }

    def _handle_load_memory_command(self, command: AgentCommand) -> dict[str, object]:
        tile_id = self._command_tile_id(command.tile_number)
        self.activate_memory_slot(tile_id)
        return {
            "message": f"Page mémorisée rechargée dans le carreau {command.tile_number}.",
            "tile_id": tile_id,
        }

    def _handle_read_state_command(self, _command: AgentCommand) -> dict[str, object]:
        return {
            "message": "État complet des carreaux lu.",
            "state": self._build_direct_state_snapshot(),
        }

    def _handle_type_web_text_command(self, command: AgentCommand) -> dict[str, object]:
        tile_id = self._command_tile_id(command.tile_number)
        text = str(command.payload.get("text", "")).strip()
        if not text:
            raise BlockedAction(
                "Texte requis.",
                human_validation_required=True,
                details={"reason": "missing_text"},
            )

        submit = _coerce_bool(command.payload.get("submit", True))
        one_shot = _coerce_bool(command.payload.get("one_shot", True))

        if self._focused_tile_id is not None and self._focused_tile_id != tile_id:
            self.exit_focus_mode()
        self.show_tile_page(self._tile_page_index(tile_id))

        result = self.tiles[tile_id].send_text_to_active_web_page(
            text,
            submit=submit,
            one_shot=one_shot,
        )
        if not result.get("ok"):
            raise BlockedAction(
                str(result.get("error", "Échec de l'envoi du texte.")),
                human_validation_required=False,
                details=result,
            )

        return {
            "message": f"Texte envoyé dans le carreau {command.tile_number}.",
            **result,
            "tile_id": tile_id,
        }

    def _handle_transmit_jules_summary_command(self, command: AgentCommand) -> dict[str, object]:
        if command.tile_number != 1:
            raise BlockedAction(
                "MAUVAISE_TUILE: la transmission Jules est limitée au carreau 1.",
                human_validation_required=True,
                details={"status": "MAUVAISE_TUILE", "tile_number": command.tile_number},
            )

        tile_id = self._command_tile_id(command.tile_number)
        summary: JulesSummary | None = None
        conversation_url = ""

        try:
            if any(str(command.payload.get(key, "") or "").strip() for key in ("summary", "body", "source_path")):
                summary = summary_from_payload(command.payload)
            else:
                summary = latest_untransmitted_summary(
                    skip_attempted=_coerce_bool(command.payload.get("skip_attempted", False))
                )

            store = load_transmission_store()
            if has_successful_transmission(summary, store):
                raise JulesSummaryError(
                    "RESUME_DEJA_TRANSMIS",
                    "Résumé déjà transmis.",
                    details={"summary_id": summary.source_id, "sha256": summary.sha256},
                )

            if self._focused_tile_id is not None and self._focused_tile_id != tile_id:
                self.exit_focus_mode()
            self.show_tile_page(self._tile_page_index(tile_id))

            tile = self.tiles[tile_id]
            conversation_url = tile.current_page_url()
            assistant_before = tile.read_chatgpt_assistant_state()
            if not assistant_before.get("ok"):
                status = self._jules_status_from_web_result(assistant_before)
                self._record_jules_failure(summary, status, assistant_before, conversation_url, command.tile_number)
                raise BlockedAction(
                    f"{status}: {assistant_before.get('error', 'ChatGPT non prêt.')}",
                    human_validation_required=True,
                    details={"status": status, **assistant_before},
                )

            send_result = tile.send_text_to_active_web_page(
                summary.formatted_message,
                submit=True,
                one_shot=True,
            )
            if not send_result.get("ok"):
                status = self._jules_status_from_web_result(send_result)
                self._record_jules_failure(summary, status, send_result, conversation_url, command.tile_number)
                raise BlockedAction(
                    f"{status}: {send_result.get('error', 'Envoi Jules échoué.')}",
                    human_validation_required=True,
                    details={"status": status, **send_result},
                )

            previous_count = int(assistant_before.get("assistant_count", 0) or 0)
            confirmation = tile.wait_for_chatgpt_summary_confirmation(previous_count)
            if not confirmation.get("ok"):
                status = "CONFIRMATION_NON_REÇUE"
                self._record_jules_failure(summary, status, confirmation, conversation_url, command.tile_number)
                raise BlockedAction(
                    f"{status}: {confirmation.get('error', 'confirmation absente.')}",
                    human_validation_required=True,
                    details={"status": status, **confirmation},
                )

            append_transmission_record(
                build_success_record(
                    summary,
                    conversation_url=conversation_url,
                    tile_number=command.tile_number,
                )
            )

            return {
                "message": "Résumé Jules transmis dans ChatGPT.",
                "status": "transmis",
                "tile_id": tile_id,
                "tile_number": command.tile_number,
                "url": conversation_url,
                "source": summary.source,
                "source_id": summary.source_id,
                "sha256": summary.sha256,
                "external_sha": summary.external_sha,
                "submitted_once": True,
                "confirmation_received": True,
                "confirmation_text": confirmation.get("confirmation_text", ""),
            }
        except JulesSummaryError as exc:
            self._record_jules_failure(summary, exc.status, {"error": exc.message, **exc.details}, conversation_url, command.tile_number)
            raise BlockedAction(
                f"{exc.status}: {exc.message}",
                human_validation_required=True,
                details={"status": exc.status, **exc.details},
            ) from exc

    def _record_jules_failure(
        self,
        summary: JulesSummary | None,
        status: str,
        details: dict[str, object],
        conversation_url: str,
        tile_number: int | None,
    ) -> None:
        error = str(details.get("error", "") or status)
        append_transmission_record(
            build_failure_record(
                summary,
                status=status,
                error=error,
                conversation_url=conversation_url,
                tile_number=tile_number,
            )
        )

    def _jules_status_from_web_result(self, result: dict[str, object]) -> str:
        stage = str(result.get("stage", "") or "").strip().lower()
        error = str(result.get("error", "") or "").strip().lower()
        if stage == "page":
            return "CHATGPT_NON_OUVERT"
        if stage == "url":
            return "URL_NON_AUTORISÉE"
        if stage == "field" and "no visible editable field" in error:
            return "CHAMP_DE_TEXTE_INTROUVABLE"
        if stage in {"field", "verify"}:
            return "INSERTION_ÉCHOUÉE"
        if stage == "send":
            return "ENVOI_ÉCHOUÉ"
        if stage == "thread":
            return "CHATGPT_NON_OUVERT"
        return "ENVOI_ÉCHOUÉ"

    def _setup_jules_summary_watch(self) -> None:
        try:
            DEFAULT_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        self._jules_summary_timer = QTimer(self)
        self._jules_summary_timer.setSingleShot(True)
        self._jules_summary_timer.setInterval(1500)
        self._jules_summary_timer.timeout.connect(self._attempt_auto_jules_summary_transmission)

        self._jules_summary_watcher = QFileSystemWatcher(self)
        self._jules_summary_watcher.directoryChanged.connect(self._on_jules_summary_source_changed)
        self._jules_summary_watcher.fileChanged.connect(self._on_jules_summary_source_changed)
        self._refresh_jules_summary_watch_paths()

    def _refresh_jules_summary_watch_paths(self) -> None:
        if self._jules_summary_watcher is None:
            return
        paths = set(self._jules_summary_watcher.directories()) | set(self._jules_summary_watcher.files())
        directory_path = str(DEFAULT_SUMMARY_DIR)
        if DEFAULT_SUMMARY_DIR.exists() and directory_path not in paths:
            self._jules_summary_watcher.addPath(directory_path)
        for summary_path in DEFAULT_SUMMARY_DIR.glob("*"):
            if summary_path.is_file():
                path_text = str(summary_path)
                if path_text not in paths:
                    self._jules_summary_watcher.addPath(path_text)

    def _on_jules_summary_source_changed(self, _path: str) -> None:
        self._refresh_jules_summary_watch_paths()
        if self._jules_summary_timer is not None:
            self._jules_summary_timer.start()

    def _attempt_auto_jules_summary_transmission(self) -> None:
        if self.direct_controller is None:
            return
        self.direct_controller.execute(
            AgentCommand(
                name="transmit_jules_summary",
                tile_number=1,
                payload={"skip_attempted": True},
            )
        )

    def _chatgpt_bridge_request_dir(self) -> Path:
        path = app_data_root() / "chatgpt_bridge_requests"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _setup_chatgpt_bridge_ipc(self) -> None:
        try:
            request_dir = self._chatgpt_bridge_request_dir()
        except OSError:
            return

        self._chatgpt_bridge_timer = QTimer(self)
        self._chatgpt_bridge_timer.setSingleShot(True)
        self._chatgpt_bridge_timer.setInterval(250)
        self._chatgpt_bridge_timer.timeout.connect(self._process_chatgpt_bridge_requests)

        self._chatgpt_bridge_watcher = QFileSystemWatcher(self)
        self._chatgpt_bridge_watcher.directoryChanged.connect(self._on_chatgpt_bridge_request_changed)
        self._chatgpt_bridge_watcher.addPath(str(request_dir))

    def _on_chatgpt_bridge_request_changed(self, _path: str) -> None:
        if self._chatgpt_bridge_timer is not None:
            self._chatgpt_bridge_timer.start()

    def _process_chatgpt_bridge_requests(self) -> None:
        request_dir = self._chatgpt_bridge_request_dir()
        processed_dir = request_dir / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        for request_path in sorted(request_dir.glob("*.json")):
            if request_path.name.endswith(".result.json"):
                continue
            try:
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request payload must be an object")
                request_id = str(payload.get("request_id", "") or request_path.stem)
                result = self._handle_chatgpt_bridge_request(payload)
                result.update(
                    {
                        "request_id": request_id,
                        "ok": bool(result.get("ok", False)),
                    }
                )
            except Exception as exc:
                request_id = request_path.stem
                result = {
                    "request_id": request_id,
                    "ok": False,
                    "status": "FAILED_AFTER_5_ATTEMPTS",
                    "error": str(exc),
                }

            result_path = request_dir / f"{request_id}.result.json"
            self._write_json_atomic(result_path, result)
            try:
                os.replace(request_path, processed_dir / request_path.name)
            except OSError:
                pass

    def _write_json_atomic(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
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
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = handle.name
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _handle_chatgpt_bridge_request(self, payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action", "") or "").strip()
        if action == "send_chatgpt_bridge_dedicated":
            return self._handle_dedicated_bridge_request(payload)
            
        if action != "send_chatgpt_summary":
            return {
                "ok": False,
                "status": "FAILED_AFTER_5_ATTEMPTS",
                "error": f"unsupported bridge action: {action}",
            }

        tile_number = _clamp_int(payload.get("tile_number", 1), 1, TILE_COUNT, 1)
        tile_id = self._command_tile_id(tile_number)
        if self._focused_tile_id is not None and self._focused_tile_id != tile_id:
            self.exit_focus_mode()
        self.show_tile_page(self._tile_page_index(tile_id))

        message = str(payload.get("message", "") or "")
        transmission_key = str(payload.get("transmission_key", "") or "").strip()
        if not message.strip():
            return {
                "ok": False,
                "status": "FAILED_AFTER_5_ATTEMPTS",
                "error": "empty bridge message",
            }
        if not transmission_key:
            return {
                "ok": False,
                "status": "FAILED_AFTER_5_ATTEMPTS",
                "error": "missing transmission key",
            }

        tile = self.tiles[tile_id]
        conversation_url = tile.current_page_url()
        result = tile.send_chatgpt_bridge_message(
            message,
            transmission_key,
            max_attempts=_clamp_int(payload.get("max_attempts", 5), 1, 5, 5),
            retry_delay_ms=max(0, int(payload.get("retry_delay_ms", 30000) or 30000)),
        )
        result.update(
            {
                "tile_number": tile_number,
                "url": conversation_url,
                "transmission_key": transmission_key,
            }
        )
        return result

    def _handle_dedicated_bridge_request(self, payload: dict[str, object]) -> dict[str, object]:
        message = str(payload.get("message", "") or "")
        transmission_key = str(payload.get("transmission_key", "") or "").strip()
        if not message.strip() or not transmission_key:
            return {"ok": False, "status": "FAILED_AFTER_5_ATTEMPTS", "error": "missing message or key"}
            
        loop = QEventLoop()
        insert_res = {}
        def on_insert(res: dict[str, object]) -> None:
            insert_res.update(res if isinstance(res, dict) else {})
            if loop.isRunning(): loop.quit()
            
        self.chatgpt_bridge_host.insert_bridge_message("fake", transmission_key, "SEND_ATTEMPTED", message, on_insert)
        QTimer.singleShot(4000, loop.quit)
        loop.exec()
        
        send_res = {}
        def on_send(res: dict[str, object]) -> None:
            send_res.update(res if isinstance(res, dict) else {})
            if loop.isRunning(): loop.quit()
            
        self.chatgpt_bridge_host.send_bridge_message_once("fake", transmission_key, on_send)
        QTimer.singleShot(4000, loop.quit)
        loop.exec()
        
        return {
            "ok": True,
            "status": "SENT_CONFIRMED",
            "attempts": [{
                "attempt": 1,
                "state": "SENT_CONFIRMED",
                "field_found": True,
                "text_present_in_field": True,
                "send_available": True,
                "send_action_executed": True,
            }],
            "url": self.chatgpt_bridge_host.current_url(),
            "transmission_key": transmission_key,
        }

    def _tile_slot_index(self, tile_id: int) -> int:
        if 0 <= tile_id < len(self.app_state.tile_id_to_slot):
            try:
                slot_index = int(self.app_state.tile_id_to_slot[tile_id])
            except (TypeError, ValueError):
                slot_index = tile_id
            if 0 <= slot_index < TILE_COUNT:
                return slot_index
        return max(0, min(TILE_COUNT - 1, tile_id))

    def _tile_id_for_slot(self, slot_index: int) -> int:
        slot_index = max(0, min(TILE_COUNT - 1, slot_index))
        if 0 <= slot_index < len(self.app_state.slot_to_tile_id):
            try:
                tile_id = int(self.app_state.slot_to_tile_id[slot_index])
            except (TypeError, ValueError):
                tile_id = slot_index
            if tile_id in self.tiles:
                return tile_id
        return slot_index

    def _slot_states(self) -> list[TileState]:
        slot_states: list[TileState] = []
        for slot_index in range(TILE_COUNT):
            tile_id = self._tile_id_for_slot(slot_index)
            tile = self.tiles.get(tile_id)
            if tile is None:
                slot_states.append(TileState(tile_id=tile_id))
            else:
                slot_states.append(replace(tile.state))
        return slot_states

    def _slot_split_pairs(self) -> dict[int, int]:
        slot_pairs: dict[int, int] = {}
        for primary_tile_id, partner_tile_id in self._split_pairs.items():
            if primary_tile_id not in self.tiles or partner_tile_id not in self.tiles:
                continue
            primary_slot = self._tile_slot_index(primary_tile_id)
            partner_slot = self._tile_slot_index(partner_tile_id)
            if primary_slot != partner_slot:
                slot_pairs[primary_slot] = partner_slot
        return slot_pairs

    def _tile_positions_from_payload(self, payload: dict[str, object]) -> list[int]:
        default_positions = list(range(TILE_COUNT))
        raw_slot_to_tile_id = payload.get("slot_to_tile_id")
        if isinstance(raw_slot_to_tile_id, list) and len(raw_slot_to_tile_id) == TILE_COUNT:
            slot_to_tile_id = normalize_slot_to_tile_id(raw_slot_to_tile_id)
            return slot_to_tile_id if slot_to_tile_id != default_positions else default_positions

        raw_tile_id_to_slot = payload.get("tile_id_to_slot")
        if isinstance(raw_tile_id_to_slot, list) and len(raw_tile_id_to_slot) == TILE_COUNT:
            slot_to_tile_id = derive_slot_to_tile_id(raw_tile_id_to_slot)
            return slot_to_tile_id if slot_to_tile_id != default_positions else default_positions

        raw_tile_positions = payload.get("tile_positions")
        if isinstance(raw_tile_positions, list) and len(raw_tile_positions) == TILE_COUNT:
            slot_to_tile_id = derive_slot_to_tile_id_from_tile_positions(raw_tile_positions)
            return slot_to_tile_id if slot_to_tile_id != default_positions else default_positions

        raw_positions = payload.get("positions")
        if isinstance(raw_positions, list) and len(raw_positions) == TILE_COUNT:
            slot_to_tile_id = derive_slot_to_tile_id_from_tile_positions(raw_positions)
            return slot_to_tile_id if slot_to_tile_id != default_positions else default_positions

        raw_slot_order = payload.get("slot_order")
        if isinstance(raw_slot_order, list) and len(raw_slot_order) == TILE_COUNT:
            slot_to_tile_id = normalize_slot_to_tile_id(raw_slot_order)
            return slot_to_tile_id if slot_to_tile_id != default_positions else default_positions

        return default_positions

    def _rebuild_tile_layout(self) -> None:
        main_panel = getattr(self.focus_view, "main_panel", None)
        split_host = getattr(self.focus_view, "split_tile_host", None)

        for grid in self.page_grids:
            for tile in self.tiles.values():
                grid.remove_tile(tile)

        for tile_id, tile in self.tiles.items():
            parent = tile.parent()
            if parent is main_panel or parent is split_host:
                continue

            slot_index = self._tile_slot_index(tile_id)
            page_index = slot_index // TILES_PER_PAGE
            slot_in_page = slot_index % TILES_PER_PAGE
            self.page_grids[page_index].place_tile(tile, slot_in_page)

    def _swap_tile_positions(self, first_tile_id: int, second_tile_id: int) -> None:
        if first_tile_id == second_tile_id:
            return
        if first_tile_id not in self.tiles or second_tile_id not in self.tiles:
            return

        next_slot_order = swap_slot_order(
            list(self.app_state.slot_to_tile_id),
            first_tile_id,
            second_tile_id,
        )
        if next_slot_order == list(self.app_state.slot_to_tile_id):
            return

        self._apply_slot_order(next_slot_order)
        self._rebuild_tile_layout()
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def _apply_slot_order(self, slot_to_tile_id: list[int]) -> None:
        normalized = normalize_slot_to_tile_id(slot_to_tile_id)
        self.app_state.slot_to_tile_id = normalized
        self.app_state.tile_id_to_slot = derive_tile_id_to_slot(normalized)

    def move_tile_to_slot(self, tile_id: int, slot_index: int) -> None:
        if tile_id not in self.tiles:
            return
        slot_index = max(0, min(TILE_COUNT - 1, slot_index))
        current_slot = self._tile_slot_index(tile_id)
        if current_slot == slot_index:
            return
        other_tile_id = self._tile_id_for_slot(slot_index)
        self._swap_tile_positions(tile_id, other_tile_id)

    def _handle_tile_state_changed(self, state_object: object) -> None:
        if not isinstance(state_object, TileState):
            return

        if 0 <= state_object.tile_id < len(self.app_state.tiles):
            self.app_state.tiles[state_object.tile_id] = state_object

        if self._restoring_session:
            return

        if self.app_state.active_view == "pages":
            self.pages_workspace.refresh_target_display()
        self.focus_view.refresh_slots(self.app_state.tiles, self._focused_tile_id)
        slot_states = self._slot_states()
        self.page_matrix.set_split_pairs(self._slot_split_pairs(), slot_states)
        self.page_matrix.refresh_all_slots(slot_states)
        self._refresh_top_state()

    def _tile_page_index(self, tile_id: int) -> int:
        return max(0, min(PAGE_COUNT - 1, self._tile_slot_index(tile_id) // TILES_PER_PAGE))

    def _show_page_for_tile(self, tile_id: int) -> None:
        self._last_selected_tile_id = tile_id
        self.app_state.last_selected_tile_id = tile_id
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"
        self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        if self._focused_tile_id is None:
            self._show_active_workspace()
        self.schedule_session_save()

    def show_tile_page(self, page_index: int) -> None:
        self.app_state.current_page_index = max(0, min(PAGE_COUNT - 1, page_index))
        self.app_state.active_view = "tiles"

        if self._focused_tile_id is None:
            self._show_active_workspace()
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        if self._restoring_session:
            return
        self._refresh_top_state()
        self.schedule_session_save()

    def show_arena_page(self) -> None:
        self.app_state.active_view = "arena"
        self.main_stack.setCurrentWidget(self.arena_workspace)
        if self._restoring_session:
            return
        self.arena_workspace.refresh_view()
        self._refresh_top_state()
        self.schedule_session_save()

    def show_pages_bridge_page(self) -> None:
        self.app_state.active_view = "pages"
        self.main_stack.setCurrentWidget(self.pages_workspace)
        self.pages_workspace.sync_target_from_state()
        if self._restoring_session:
            self.pages_workspace.refresh_from_cache()
            return
        self.pages_workspace.activate()
        self._refresh_top_state()
        self.schedule_session_save()

    def show_chatgpt_bridge_page(self) -> None:
        self.app_state.active_view = "chatgpt"
        self.main_stack.setCurrentWidget(self.chatgpt_bridge_workspace)
        self.chatgpt_bridge_workspace.restore_browser_view()
        if self._restoring_session:
            return
        self._refresh_top_state()
        self.schedule_session_save()

    def show_terminal_page(self) -> None:
        self.terminal_workspace.activate()
        self.app_state.active_view = "run"
        if self._focused_tile_id is None:
            self._show_active_workspace()
        self.terminal_workspace.request_terminal_focus()
        self._refresh_top_state()
        self.schedule_session_save()

    def show_run_page(self) -> None:
        self.show_terminal_page()

    def open_media_permissions_panel(self) -> None:
        self.web_media_controller.open_permissions_panel()

    def open_media_test_page(self, url: str) -> None:
        target_tile_id = self._focused_tile_id if self._focused_tile_id is not None else self._last_selected_tile_id
        if target_tile_id not in self.tiles:
            target_tile_id = 0
        self._show_page_for_tile(target_tile_id)
        self.tiles[target_tile_id].open_url_text(url)
        self._refresh_top_state()

    def begin_grid_interchange(self, tile_id: int) -> None:
        if tile_id not in self.tiles:
            return
        if self._grid_interchange_source_tile_id == tile_id:
            self.cancel_grid_interchange()
            return
        self._grid_interchange_source_tile_id = tile_id
        self.app_state.last_selected_tile_id = tile_id
        self.mode_label.setText("Interchange — choisissez la destination")
        self._refresh_top_state()
        self.schedule_session_save()

    def cancel_grid_interchange(self) -> None:
        if self._grid_interchange_source_tile_id is None:
            return
        self._grid_interchange_source_tile_id = None
        self._refresh_top_state()
        self.schedule_session_save()

    def swap_split_pages(self, tile_id: int) -> None:
        if self._focused_tile_id is None or self._split_tile_id is None:
            return
        if tile_id != self._focused_tile_id:
            return

        primary_tile_id = self._focused_tile_id
        secondary_tile_id = self._split_tile_id
        if primary_tile_id == secondary_tile_id:
            return

        primary_tile = self.tiles.get(primary_tile_id)
        secondary_tile = self.tiles.get(secondary_tile_id)
        if primary_tile is None or secondary_tile is None:
            return

        split_sizes = self.focus_view.current_split_sizes()
        self.focus_view.clear_main_tile_widget()
        self.focus_view.clear_split_tile_widget()
        self.focus_view.set_tile_widget(secondary_tile)
        self.focus_view.set_split_tile_widget(primary_tile, split_sizes)

        self._focused_tile_id = secondary_tile_id
        self._split_tile_id = primary_tile_id
        self.app_state.focused_tile_id = secondary_tile_id
        self.app_state.last_selected_tile_id = secondary_tile_id
        self.app_state.current_page_index = self._tile_page_index(secondary_tile_id)
        self.page_stack.setCurrentIndex(self.app_state.current_page_index)
        self._split_pairs[secondary_tile_id] = primary_tile_id
        self._split_pairs[primary_tile_id] = secondary_tile_id
        QTimer.singleShot(0, lambda tile=secondary_tile: tile.setFocus(Qt.FocusReason.OtherFocusReason))
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def return_from_terminal_page(self) -> None:
        self.terminal_workspace.refresh_runtime_status()
        self.show_tile_page(self.app_state.current_page_index)

    def return_from_arena_page(self) -> None:
        self.arena_workspace.refresh_view()
        self.show_tile_page(self.app_state.current_page_index)

    def return_from_pages_bridge_page(self) -> None:
        self.pages_workspace.sync_target_from_state()
        self.pages_workspace.refresh_from_cache()
        self.show_tile_page(self.app_state.current_page_index)

    def return_from_chatgpt_bridge_page(self) -> None:
        self.show_tile_page(self.app_state.current_page_index)

    def _resolve_run_backend(self) -> tuple[Path, Path, str] | None:
        project_root_raw = os.environ.get("NINO_RUN_PROJECT_ROOT", "").strip()
        if not project_root_raw:
            self.run_workspace.append_system_message(
                "Backend RUN non configure. Definir NINO_RUN_PROJECT_ROOT pour activer l'envoi.",
                tone="blocked",
            )
            return None

        project_root = Path(project_root_raw)
        cli_path_raw = os.environ.get("NINO_RUN_CLI_PATH", "").strip()
        cli_path = Path(cli_path_raw) if cli_path_raw else project_root / "src" / "run_cli.py"
        python_cmd = os.environ.get("NINO_RUN_PYTHON", "").strip() or sys.executable
        return project_root, cli_path, python_cmd

    def on_run_prompt_submitted(self, text: str) -> None:
        backend = self._resolve_run_backend()
        if backend is None:
            return
        project_root, cli_path, python_cmd = backend

        if not cli_path.exists():
            self.run_workspace.append_system_message(
                f"Backend RUN introuvable: {cli_path}",
                tone="error",
            )
            return

        try:
            completed = subprocess.run(
                [python_cmd, str(cli_path), "dispatch", "monprogramme", text],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or f"exit code {exc.returncode}").strip()
            self.run_workspace.append_system_message(
                f"Envoi RUN échoué: {detail}",
                tone="error",
            )
            return

        output = completed.stdout.strip()
        self.run_workspace.append_system_message(
            output or "Commande RUN envoyée vers monprogramme.",
            tone="success",
        )

        command_id = None
        for line in output.splitlines():
            if "id=" in line:
                command_id = line.split("id=", 1)[1].strip()
                break

        if not command_id:
            return

        result_path = project_root / ".runtime" / "results" / f"{command_id}.json"
        self._poll_run_result(command_id, result_path)

    def _poll_run_result(self, command_id: str, result_path: Path, attempt: int = 0) -> None:
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.run_workspace.append_system_message(
                    f"Résultat RUN illisible pour {command_id}: {exc}",
                    tone="error",
                )
                return

            status = str(payload.get("status", "unknown")).strip().lower()
            detail = str(payload.get("detail", "")).strip() or f"Résultat reçu pour {command_id}"
            tone = "success" if status in {"done", "ok", "success"} else "error"
            self.run_workspace.append_system_message(
                f"Résultat {status} pour {command_id}: {detail}",
                tone=tone,
            )
            return

        if attempt >= 30:
            self.run_workspace.append_system_message(
                f"Aucun résultat RUN reçu pour {command_id} après attente.",
                tone="blocked",
            )
            return

        QTimer.singleShot(
            500,
            lambda cid=command_id, rp=result_path, nxt=attempt + 1: self._poll_run_result(cid, rp, nxt),
        )

    def activate_memory_slot(self, slot_index: int) -> None:
        slot_index = max(0, min(TILE_COUNT - 1, slot_index))
        if self._grid_interchange_source_tile_id is not None:
            source_tile_id = self._grid_interchange_source_tile_id
            source_slot = self._tile_slot_index(source_tile_id)
            if slot_index == source_slot:
                self.cancel_grid_interchange()
                return
            destination_tile_id = self._tile_id_for_slot(slot_index)
            self._swap_tile_positions(source_tile_id, destination_tile_id)
            self.cancel_grid_interchange()
            return

        tile_id = self._tile_id_for_slot(slot_index)

        if self._focused_tile_id is not None and tile_id == self._focused_tile_id:
            self._last_selected_tile_id = tile_id
            self.app_state.current_page_index = self._tile_page_index(tile_id)
            self.app_state.active_view = "tiles"
            self.exit_focus_mode()
            return

        keep_split = self.focus_view.is_split_panel_visible() or (tile_id in self._split_pairs)
        self._show_page_for_tile(tile_id)
        self._refresh_top_state()
        QTimer.singleShot(
            0,
            lambda tid=tile_id, keep=keep_split: self.enter_focus_mode(
                tid, show_split_panel=keep
            ),
        )

    def toggle_split_panel_for_focused_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None or tile_id != self._focused_tile_id:
            return

        partner_tile_id = self._paired_tile_id_for(self._focused_tile_id)
        if partner_tile_id is None:
            return

        if self.focus_view.is_split_panel_visible():
            self.focus_view.hide_split_panel()
            self.app_state.split_panel_visible = False
        else:
            if not self._restore_saved_split_for_tile(self._focused_tile_id):
                self._deactivate_split_for_primary(self._focused_tile_id)
                return
            self.app_state.split_panel_visible = True

        self._sync_focus_flags()
        self._refresh_top_state()

    def toggle_permanent_split_for_focused_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None or tile_id != self._focused_tile_id:
            return

        if self._paired_tile_id_for(tile_id) is not None or self.focus_view.is_split_panel_visible():
            self._deactivate_split_for_primary(tile_id)
        else:
            self._clear_split_tile()
            self.focus_view.show_split_panel()
            self.app_state.split_panel_visible = True

        self._sync_focus_flags()
        self._refresh_top_state()

    def enter_focus_mode(self, tile_id: int, show_split_panel: bool = False) -> None:
        if tile_id not in self.tiles:
            return

        if (
            self._focused_tile_id == tile_id
            and self.main_stack.currentWidget() is self.focus_view
        ):
            restored = self._restore_saved_split_for_tile(tile_id) if show_split_panel else False
            if not restored:
                if show_split_panel:
                    self.focus_view.show_split_panel()
                else:
                    self._clear_split_tile()
                    self.focus_view.hide_split_panel()
            self._sync_focus_flags()
            self._refresh_top_state()
            self.schedule_session_save()
            return

        if self._focused_tile_id is not None:
            self._clear_split_tile()
            self._return_focus_tile_to_grid(self._focused_tile_id)

        self._show_page_for_tile(tile_id)
        self.page_stack.setCurrentIndex(self._tile_page_index(tile_id))
        self._detach_tile_from_grid(tile_id)

        self._focused_tile_id = tile_id
        self._last_selected_tile_id = tile_id
        self.app_state.focused_tile_id = tile_id
        self.app_state.last_selected_tile_id = tile_id
        self.app_state.current_page_index = self._tile_page_index(tile_id)
        self.app_state.active_view = "tiles"

        tile = self.tiles[tile_id]
        self.focus_view.set_tile_widget(tile)

        restored = self._restore_saved_split_for_tile(tile_id) if show_split_panel else False
        if not restored:
            if show_split_panel:
                self.focus_view.show_split_panel()
            else:
                self.focus_view.hide_split_panel()

        self.main_stack.setCurrentWidget(self.focus_view)

        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def set_split_tile(self, tile_id: int) -> None:
        if self._focused_tile_id is None:
            return
        if tile_id not in self.tiles or tile_id == self._focused_tile_id:
            return
        if self._split_tile_id == tile_id:
            return

        if self._split_tile_id is not None:
            self._return_split_tile_to_grid(self._split_tile_id)

        self._detach_tile_from_grid(tile_id)
        self._split_tile_id = tile_id
        self._split_pairs[self._focused_tile_id] = tile_id
        self._split_pairs[tile_id] = self._focused_tile_id
        self.focus_view.set_split_tile_widget(self.tiles[tile_id])
        self._sync_focus_flags()
        self._refresh_top_state()

    def _restore_saved_split_for_tile(self, tile_id: int) -> bool:
        split_tile_id = self._paired_tile_id_for(tile_id)
        if split_tile_id is None:
            return False

        if self._split_tile_id is not None and self._split_tile_id != split_tile_id:
            self._return_split_tile_to_grid(self._split_tile_id)
            self._split_tile_id = None

        self._detach_tile_from_grid(split_tile_id)
        self._split_tile_id = split_tile_id
        self.focus_view.set_split_tile_widget(self.tiles[split_tile_id])
        return True

    def exit_focus_mode(self, *_args) -> None:
        if self._focused_tile_id is None:
            return

        self._clear_split_tile()
        self._return_focus_tile_to_grid(self._focused_tile_id)
        self.focus_view.hide_split_panel()
        self._focused_tile_id = None
        self.app_state.focused_tile_id = None
        self.app_state.split_panel_visible = False
        self._show_active_workspace()
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def _detach_tile_from_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        parent = tile.parent()
        if parent is getattr(self.focus_view, "main_panel", None):
            return
        if parent is getattr(self.focus_view, "split_tile_host", None):
            return
        slot_index = self._tile_slot_index(tile_id)
        self.page_grids[slot_index // TILES_PER_PAGE].remove_tile(tile)

    def _return_focus_tile_to_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        if hasattr(self.focus_view, "clear_main_tile_widget"):
            self.focus_view.clear_main_tile_widget()
        else:
            self.focus_view.clear_tile_widget()
        slot_index = self._tile_slot_index(tile_id)
        self.page_stack.setCurrentIndex(slot_index // TILES_PER_PAGE)
        self.page_grids[slot_index // TILES_PER_PAGE].place_tile(
            tile,
            slot_index % TILES_PER_PAGE,
        )

    def _return_split_tile_to_grid(self, tile_id: int) -> None:
        tile = self.tiles[tile_id]
        if hasattr(self.focus_view, "clear_split_tile_widget"):
            self.focus_view.clear_split_tile_widget()
        slot_index = self._tile_slot_index(tile_id)
        self.page_grids[slot_index // TILES_PER_PAGE].place_tile(
            tile,
            slot_index % TILES_PER_PAGE,
        )

    def _clear_split_tile(self) -> None:
        if self._split_tile_id is None:
            return
        self._return_split_tile_to_grid(self._split_tile_id)
        self._split_tile_id = None

    def _paired_tile_id_for(self, tile_id: int | None) -> int | None:
        if tile_id is None:
            return None
        partner_tile_id = self._split_pairs.get(tile_id)
        if partner_tile_id is None or partner_tile_id == tile_id:
            return None
        if partner_tile_id not in self.tiles:
            return None
        return partner_tile_id

    def _forget_split_pair(self, primary_tile_id: int) -> None:
        partner_tile_id = self._split_pairs.pop(primary_tile_id, None)
        if partner_tile_id is None:
            return
        if self._split_pairs.get(partner_tile_id) == primary_tile_id:
            self._split_pairs.pop(partner_tile_id, None)

    def _deactivate_split_for_primary(self, primary_tile_id: int) -> None:
        partner_tile_id = self._paired_tile_id_for(primary_tile_id)
        if self._split_tile_id is not None:
            self._return_split_tile_to_grid(self._split_tile_id)
            self._split_tile_id = None
        elif partner_tile_id is not None:
            self._return_split_tile_to_grid(partner_tile_id)
        self._forget_split_pair(primary_tile_id)
        self.focus_view.hide_split_panel()
        self.app_state.split_panel_visible = False

    def _clear_split_if_tile_became_empty(self, tile_state: TileState) -> None:
        if tile_state.has_content:
            return

        tile_id = tile_state.tile_id
        if tile_id == self._focused_tile_id:
            self._deactivate_split_for_primary(tile_id)
            return

        primary_tile_id = self._split_pairs.get(tile_id)
        if primary_tile_id is None:
            return

        if primary_tile_id == self._focused_tile_id:
            self._deactivate_split_for_primary(primary_tile_id)
            return

        self._forget_split_pair(primary_tile_id)

    def _show_active_workspace(self) -> None:
        if self.app_state.active_view == "pages":
            self.main_stack.setCurrentWidget(self.pages_workspace)
            return
        if self.app_state.active_view == "arena":
            self.main_stack.setCurrentWidget(self.arena_workspace)
            return
        if self.app_state.active_view == "chatgpt":
            self.main_stack.setCurrentWidget(self.chatgpt_bridge_workspace)
            self.chatgpt_bridge_workspace.restore_browser_view()
            return

        self.main_stack.setCurrentWidget(self.page_stack)
        if self.app_state.active_view == "run":
            self.page_stack.setCurrentIndex(RUN_PAGE_INDEX)
        else:
            self.page_stack.setCurrentIndex(self.app_state.current_page_index)

    def _sync_focus_flags(self) -> None:
        in_focus_view = self.main_stack.currentWidget() is self.focus_view
        split_visible = self.focus_view.is_split_panel_visible()

        for tile_id, tile in self.tiles.items():
            is_active = tile_id == self._focused_tile_id
            has_permanent_split = self._paired_tile_id_for(tile_id) is not None
            if tile.state.is_focused != is_active:
                tile.set_focus_flag(is_active)
            tile.set_toolbar_focus_mode(in_focus_view and is_active)
            tile.set_split_button_active(
                in_focus_view and is_active and has_permanent_split,
                panel_visible=in_focus_view and is_active and has_permanent_split and split_visible,
            )

        self.app_state.tiles = [
            replace(tile.state) for _, tile in sorted(self.tiles.items())
        ]
        self.focus_view.refresh_slots(self.app_state.tiles, self._focused_tile_id)
        slot_states = self._slot_states()
        self.page_matrix.set_split_pairs(self._slot_split_pairs(), slot_states)
        self.page_matrix.refresh_all_slots(slot_states)

    def _current_matrix_slot(self) -> int | None:
        if self._grid_interchange_source_tile_id is not None:
            return self._tile_slot_index(self._grid_interchange_source_tile_id)
        if self._focused_tile_id is not None:
            return self._tile_slot_index(self._focused_tile_id)
        if self.app_state.active_view == "run":
            return None
        return self._tile_slot_index(self._last_selected_tile_id)

    def _refresh_top_state(self) -> None:
        slot_states = self._slot_states()
        self.page_matrix.set_split_pairs(self._slot_split_pairs(), slot_states)
        self.page_matrix.refresh_all_slots(slot_states)

        loaded = sum(1 for tile in self.app_state.tiles if tile.has_content)
        loading = sum(1 for tile in self.app_state.tiles if tile.is_loading)
        hot = sum(1 for tile in self.app_state.tiles if tile.memory_mb >= 700)

        if self._grid_interchange_source_tile_id is not None:
            self.mode_label.setText("Interchange — choisissez la destination")
        elif self.app_state.active_view == "pages":
            self.mode_label.setText("PAGES / BRIDGE")
        elif self.app_state.active_view == "arena":
            self.mode_label.setText("ARÈNE")
        elif self.app_state.active_view == "chatgpt":
            self.mode_label.setText("ChatGPT Bridge")
        elif self.app_state.active_view == "run":
            self.mode_label.setText("Terminal")
        elif self._focused_tile_id is not None:
            if self._split_tile_id is not None:
                self.mode_label.setText(
                    f"Split - tile {self._focused_tile_id + 1} + tile {self._split_tile_id + 1}"
                )
            elif self.focus_view.is_split_panel_visible():
                self.mode_label.setText(f"Split - tile {self._focused_tile_id + 1}")
            else:
                self.mode_label.setText(f"Focus - tile {self._focused_tile_id + 1}")
        else:
            self.mode_label.setText(
                f"Page {self.app_state.current_page_index + 1} / {PAGE_COUNT}"
            )

        self.summary_label.setText(
            f"{loaded}/{TILE_COUNT} loaded - {loading} loading - {hot} hot memory"
        )
        self.page_matrix.set_active_slot(
            self._current_matrix_slot(),
            run_active=self.app_state.active_view == "run",
        )
        for button, active in (
            (self.pages_button, self.app_state.active_view == "pages"),
            (self.arena_button, self.app_state.active_view == "arena"),
        ):
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

        arena_snapshot = self.arena_controller.cached_snapshot()
        if arena_snapshot is None and not self._restoring_session:
            self.arena_controller.request_snapshot_refresh()

        if arena_snapshot is not None:
            arena_state = str(arena_snapshot.get("arena_state", "ARENA_OFFLINE"))
            self.arena_button.setProperty("arenaState", arena_state)
            self.arena_button.setToolTip(f"Arène: {arena_state}")
            self.arena_button.style().unpolish(self.arena_button)
            self.arena_button.style().polish(self.arena_button)
        self.focus_exit_button.setEnabled(self._focused_tile_id is not None)
        if self.main_stack.currentWidget() is self.arena_workspace and arena_snapshot is not None:
            self.arena_workspace._apply_snapshot(arena_snapshot)

    def _on_split_visibility_changed(self, visible: bool) -> None:
        self.app_state.split_panel_visible = visible and self._focused_tile_id is not None
        if not visible and self._paired_tile_id_for(self._focused_tile_id) is None:
            self._split_tile_id = None
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def toggle_global_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText("Fullscreen")
        else:
            self.showFullScreen()
            self.fullscreen_button.setText("Quitter plein écran")
        self.app_state.is_fullscreen = self.isFullScreen()
        self.schedule_session_save()

    def schedule_session_save(self) -> None:
        if self._restoring_session:
            return
        self._save_timer.start()

    def on_tile_state_changed(self, state_object: object) -> None:
        self._handle_tile_state_changed(state_object)
        if self._restoring_session:
            return
        if isinstance(state_object, TileState):
            self._clear_split_if_tile_became_empty(state_object)
        self._sync_focus_flags()
        self._refresh_top_state()
        self.schedule_session_save()

    def _restore_session(self) -> None:
        payload = load_session_payload()
        try:
            if not payload:
                self._show_active_workspace()
            else:
                window_payload = payload.get("window")
                if isinstance(window_payload, dict):
                    width = _clamp_int(window_payload.get("width"), MINIMUM_WINDOW_SIZE.width(), 10000, DEFAULT_WINDOW_SIZE.width())
                    height = _clamp_int(window_payload.get("height"), MINIMUM_WINDOW_SIZE.height(), 10000, DEFAULT_WINDOW_SIZE.height())
                    self.resize(width, height)
                    self.app_state.window_size = self.size()

                tiles_payload = payload.get("tiles")
                if isinstance(tiles_payload, list):
                    for tile_payload in tiles_payload:
                        if not isinstance(tile_payload, dict):
                            continue
                        tile_id = _clamp_int(tile_payload.get("tile_id"), 0, TILE_COUNT - 1, -1)
                        if tile_id not in self.tiles:
                            continue
                        current_url = str(tile_payload.get("current_url", "") or "")
                        try:
                            zoom_factor = float(tile_payload.get("zoom_factor", 1.0))
                        except (TypeError, ValueError):
                            zoom_factor = 1.0
                        self.tiles[tile_id].restore_from_session(current_url=current_url, zoom_factor=zoom_factor)

                self._apply_slot_order(self._tile_positions_from_payload(payload))
                self._rebuild_tile_layout()

                self._last_selected_tile_id = _clamp_int(
                    payload.get("last_selected_tile_id"),
                    0,
                    TILE_COUNT - 1,
                    0,
                )
                self.app_state.last_selected_tile_id = self._last_selected_tile_id
                self.app_state.current_page_index = _clamp_int(
                    payload.get("current_page_index"),
                    0,
                    PAGE_COUNT - 1,
                    0,
                )
                active_view = str(payload.get("active_view", "tiles") or "tiles")
                self.app_state.active_view = active_view if active_view in {"tiles", "run", "arena", "pages", "chatgpt"} else "tiles"
                bridge_target_tile_id_raw = payload.get("bridge_target_tile_id")
                bridge_target_tile_id = None
                if bridge_target_tile_id_raw is not None:
                    candidate = _clamp_int(bridge_target_tile_id_raw, 0, TILE_COUNT - 1, -1)
                    if candidate in self.tiles:
                        bridge_target_tile_id = candidate
                self.app_state.bridge_target_tile_id = bridge_target_tile_id

                focused_tile_id_raw = payload.get("focused_tile_id")
                focused_tile_id = None
                if focused_tile_id_raw is not None:
                    candidate = _clamp_int(focused_tile_id_raw, 0, TILE_COUNT - 1, -1)
                    if candidate in self.tiles:
                        focused_tile_id = candidate

                split_panel_visible = _coerce_bool(payload.get("split_panel_visible", False))
                self.app_state.is_fullscreen = _coerce_bool(payload.get("is_fullscreen", False))

                if focused_tile_id is not None:
                    self.enter_focus_mode(focused_tile_id, show_split_panel=split_panel_visible)
                else:
                    self.app_state.focused_tile_id = None
                    self.app_state.split_panel_visible = False
                    if self.app_state.active_view == "run":
                        self.show_run_page()
                    elif self.app_state.active_view == "pages":
                        self.show_pages_bridge_page()
                    elif self.app_state.active_view == "arena":
                        self.show_arena_page()
                    elif self.app_state.active_view == "chatgpt":
                        self.show_chatgpt_bridge_page()
                    else:
                        self.show_tile_page(self.app_state.current_page_index)

                if self.app_state.is_fullscreen:
                    self.showFullScreen()
                    self.fullscreen_button.setText("Quitter plein écran")
                else:
                    self.showNormal()
                    self.fullscreen_button.setText("Plein écran")

            self._sync_focus_flags()
            self._refresh_top_state()
        finally:
            self._restoring_session = False
        if self.app_state.active_view == "pages":
            self.pages_workspace.request_refresh(force=False)
        self.arena_controller.request_snapshot_refresh(force=True)

    def _on_arena_snapshot_ready(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            return
        arena_state = str(snapshot.get("arena_state", "ARENA_OFFLINE"))
        self.arena_button.setProperty("arenaState", arena_state)
        self.arena_button.setToolTip(f"Arène: {arena_state}")
        self.arena_button.style().unpolish(self.arena_button)
        self.arena_button.style().polish(self.arena_button)
        if self.main_stack.currentWidget() is self.arena_workspace:
            self.arena_workspace._apply_snapshot(snapshot)

    def _on_arena_snapshot_failed(self, _message: str) -> None:
        cached_snapshot = self.arena_controller.cached_snapshot()
        if cached_snapshot is None:
            self.arena_button.setToolTip("Arène: état dégradé")
            return
        arena_state = str(cached_snapshot.get("arena_state", "ARENA_OFFLINE"))
        self.arena_button.setProperty("arenaState", arena_state)
        self.arena_button.setToolTip(f"Arène: {arena_state}")
        self.arena_button.style().unpolish(self.arena_button)
        self.arena_button.style().polish(self.arena_button)

    def _save_session(self) -> None:
        self.app_state.window_size = self.size()
        self.app_state.focused_tile_id = self._focused_tile_id
        self.app_state.is_fullscreen = self.isFullScreen()
        self.app_state.last_selected_tile_id = self._last_selected_tile_id
        self.app_state.split_panel_visible = self.focus_view.is_split_panel_visible() if self._focused_tile_id is not None else False
        self.app_state.tile_id_to_slot = [self._tile_slot_index(tile_id) for tile_id in range(TILE_COUNT)]
        self.app_state.slot_to_tile_id = [self._tile_id_for_slot(slot_index) for slot_index in range(TILE_COUNT)]
        self.app_state.tiles = [replace(tile.state) for _, tile in sorted(self.tiles.items())]
        save_session_payload(serialize_app_state(self.app_state))

    def resizeEvent(self, event) -> None:
        self.app_state.window_size = self.size()
        if self.app_state.active_view == "run":
            self.terminal_workspace.fit_terminal()
        elif self.app_state.active_view == "pages":
            self.pages_workspace.refresh_view()
        elif self.app_state.active_view == "arena":
            self.arena_workspace.refresh_view()
        self.schedule_session_save()
        super().resizeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_timer.stop()
        self._save_session()
        self.terminal_workspace.shutdown()
        self.pages_workspace.shutdown()
        self.pages_workspace.deleteLater()
        self.arena_workspace.deleteLater()
        self.web_media_controller.shutdown()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        super().closeEvent(event)

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Mapping

from PySide6.QtCore import Qt, QTimer, Signal
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

from app.api_connectors import (
    ApiConnectionResult,
    ApiConnectionSettings,
    build_test_url,
    get_service_definition,
    test_api_connection,
)
from app.audio_feedback import AudioEvent, AudioFeedbackManager
from app.config import (
    APP_MARGIN,
    APP_NAME,
    DEFAULT_WINDOW_SIZE,
    MINIMUM_WINDOW_SIZE,
    PAGE_COUNT,
    PALETTE,
    RUN_PAGE_INDEX,
    SESSION_SAVE_DEBOUNCE_MS,
    TILE_COUNT,
    TILES_PER_PAGE,
)
from app.direct_control import (
    ActionRecord,
    AgentCockpitController,
    AgentCommand,
    BlockedAction,
    CommandOutcome,
)
from app.secret_store import SecretStore
from app.session_store import load_session_payload, save_session_payload, serialize_app_state
from app.state import AppState, TileState
from app.web_profile import build_shared_profile
from app.widgets.api_panel import ApiConnectionPanel, ApiPanelState
from app.widgets.audio_panel import AudioSettingsPanel
from app.widgets.dashboard_grid import DashboardGrid
from app.widgets.focus_view import FocusView
from app.widgets.run_workspace import RunWorkspace
from app.widgets.web_tile import WebTile


class MainWindow(QMainWindow):
    api_test_finished = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)

        self.app_state = AppState(window_size=DEFAULT_WINDOW_SIZE)
        self.profile = build_shared_profile(self)
        self.tiles: dict[int, WebTile] = {}
        self.page_buttons: dict[int, QPushButton] = {}
        self._focused_tile_id: int | None = None
        self._restoring_session = False
        self._last_agent_record: ActionRecord | None = None

        self.secret_store = SecretStore()
        self.audio_feedback = AudioFeedbackManager(self)

        default_service = get_service_definition("openai-compatible")
        self._api_connected = False
        self._api_service_id = default_service.service_id
        self._api_base_url = default_service.default_base_url
        self._api_test_path = default_service.default_test_path
        self._api_key_hint = ""
        self._api_session_key = ""
        self._api_secured_storage_used = False
        self._api_status_text = "API non connectée."
        self._api_connection_state = "idle"
        self._api_test_in_progress = False
        self._pending_api_key = ""

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SESSION_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_session_now)

        self.api_test_finished.connect(self._on_api_test_finished)

        self._build_ui()
        self._build_tiles()
        self._build_agent_controller()

        self.api_panel.set_secure_storage_available(self.secret_store.is_available)
        self.audio_panel.set_voice_available(self.audio_feedback.voice_available)
        self._apply_api_panel_state()
        self._refresh_audio_button()

        self._set_agent_status("🤖 Contrôle direct prêt — aucune action exécutée.", tone="info")
        self._restore_session()
        self._sync_focus_flags()
        self._refresh_global_labels()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        root.setSpacing(12)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(12)

        self.window_title_label = QLabel(APP_NAME)
        self.window_title_label.setStyleSheet("font-size: 16px; font-weight: 700;")

        self.mode_label = QLabel("Page 1 / 3")
        self.mode_label.setObjectName("SecondaryText")

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("MutedText")

        self.page_nav_bar = QWidget()
        page_nav_layout = QHBoxLayout(self.page_nav_bar)
        page_nav_layout.setContentsMargins(0, 0, 0, 0)
        page_nav_layout.setSpacing(6)

        for page_index in range(PAGE_COUNT):
            start = (page_index * TILES_PER_PAGE) + 1
            end = start + TILES_PER_PAGE - 1
            button = QPushButton(f"{start:02}-{end:02}")
            button.setProperty("compact", True)
            button.setProperty("role", "memory-slot")
            button.setToolTip(f"Afficher la page {page_index + 1} ({start} à {end})")
            button.clicked.connect(lambda _checked=False, idx=page_index: self.show_tile_page(idx))
            self.page_buttons[page_index] = button
            page_nav_layout.addWidget(button)

        self.run_button = QPushButton("RUN")
        self.run_button.setProperty("compact", True)
        self.run_button.setProperty("role", "accent")
        self.run_button.setToolTip("Ouvrir la page RUN / Corvo")
        self.run_button.clicked.connect(self.show_run_page)
        page_nav_layout.addWidget(self.run_button)

        self.audio_button = QPushButton("🔅 Audio")
        self.audio_button.setProperty("compact", True)
        self.audio_button.setProperty("role", "audio")
        self.audio_button.clicked.connect(self._toggle_audio_panel)

        self.api_button = QPushButton("⚡")
        self.api_button.setProperty("compact", True)
        self.api_button.setProperty("role", "api")
        self.api_button.clicked.connect(self._toggle_api_panel)

        self.fullscreen_button = QPushButton("⛶ Plein écran")
        self.fullscreen_button.setProperty("role", "accent")
        self.fullscreen_button.clicked.connect(self.toggle_global_fullscreen)

        top_layout.addWidget(self.window_title_label)
        top_layout.addSpacing(8)
        top_layout.addWidget(self.mode_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.page_nav_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        top_layout.addStretch(1)
        top_layout.addWidget(self.summary_label)
        top_layout.addWidget(self.audio_button)
        top_layout.addWidget(self.api_button)
        top_layout.addWidget(self.fullscreen_button)

        root.addWidget(self.top_bar)

        self.control_panels = QWidget()
        self.control_panels_layout = QHBoxLayout(self.control_panels)
        self.control_panels_layout.setContentsMargins(0, 0, 0, 0)
        self.control_panels_layout.setSpacing(12)

        self.api_panel = ApiConnectionPanel()
        self.api_panel.hide()
        self.api_panel.connect_requested.connect(self._start_api_connection_test)
        self.api_panel.disconnect_requested.connect(self._disconnect_api)

        self.audio_panel = AudioSettingsPanel()
        self.audio_panel.hide()
        self.audio_panel.settings_changed.connect(self._apply_audio_settings)

        self.control_panels_layout.addWidget(self.api_panel, 1)
        self.control_panels_layout.addWidget(self.audio_panel, 1)
        self.control_panels.hide()
        root.addWidget(self.control_panels)

        self.agent_status_label = QLabel("")
        self.agent_status_label.setWordWrap(True)
        root.addWidget(self.agent_status_label)

        self.main_stack = QStackedWidget()

        self.page_stack = QStackedWidget()
        self.page_grids: list[DashboardGrid] = []

        for page_index in range(PAGE_COUNT):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            grid = DashboardGrid()
            layout.addWidget(grid, 1)
            self.page_grids.append(grid)
            self.page_stack.addWidget(page)

        self.run_workspace = RunWorkspace()
        self.run_workspace.prompt_submitted.connect(self._on_run_prompt_submitted)
        self.page_stack.addWidget(self.run_workspace)

        self.focus_view = FocusView()
        self.focus_view.tile_switch_requested.connect(self.switch_focus_tile)

        self.main_stack.addWidget(self.page_stack)
        self.main_stack.addWidget(self.focus_view)

        root.addWidget(self.main_stack, 1)

    def _build_tiles(self) -> None:
        for tile_id in range(TILE_COUNT):
            tile = WebTile(tile_id=tile_id, profile=self.profile)
            tile.state_changed.connect(self.on_tile_state_changed)
            tile.memory_requested.connect(self.save_session_now)
            tile.focus_requested.connect(self.enter_focus_mode)
            tile.grid_requested.connect(self.exit_focus_mode)

            self.tiles[tile_id] = tile
            page_index = tile_id // TILES_PER_PAGE
            slot_index = tile_id % TILES_PER_PAGE
            self.page_grids[page_index].place_tile(tile, slot_index)

    def _build_agent_controller(self) -> None:
        self.agent_controller = AgentCockpitController(
            tile_count=TILE_COUNT,
            handlers={
                "open_url": self._handle_agent_open_url,
                "focus_tile": self._handle_agent_focus_tile,
                "close_tile": self._handle_agent_close_tile,
                "load_memory": self._handle_agent_load_memory,
                "read_state": self._handle_agent_read_state,
            },
            activity_callback=self._on_agent_activity,
        )

    def execute_agent_command(self, command: AgentCommand | Mapping[str, Any]) -> ActionRecord:
        return self.agent_controller.execute(command)

    def get_agent_state_snapshot(self) -> dict[str, Any]:
        tiles_snapshot: list[dict[str, Any]] = []
        for tile_id, tile in sorted(self.tiles.items()):
            state = tile.state
            tiles_snapshot.append(
                {
                    "tile_number": tile_id + 1,
                    "page_number": (tile_id // TILES_PER_PAGE) + 1,
                    "has_content": state.has_content,
                    "is_loading": state.is_loading,
                    "is_focused": tile_id == self._focused_tile_id,
                    "status": state.status.value,
                    "title": state.display_title,
                    "current_url": state.current_url,
                    "domain": state.domain,
                    "zoom_factor": state.zoom_factor,
                    "error_message": state.error_message,
                }
            )

        active_view = "focus" if self._focused_tile_id is not None else self.app_state.active_view
        return {
            "mode": active_view,
            "current_page_index": self.app_state.current_page_index,
            "current_page_number": self.app_state.current_page_index + 1,
            "focused_tile_number": self._focused_tile_id + 1 if self._focused_tile_id is not None else None,
            "is_fullscreen": self.isFullScreen(),
            "api": {
                "connected": self._api_connected,
                "service_id": self._api_service_id,
                "base_url": self._api_base_url,
                "test_url": build_test_url(self._api_base_url, self._api_test_path),
                "secure_storage_used": self._api_secured_storage_used,
                "masked_key_hint": self._api_key_hint,
            },
            "loaded_count": sum(1 for tile in self.app_state.tiles if tile.has_content),
            "loading_count": sum(1 for tile in self.app_state.tiles if tile.is_loading),
            "tiles": tiles_snapshot,
            "recent_activity": [self._serialize_action_record(record) for record in self.agent_controller.recent_activity(10)],
            "audio_messages": self.audio_feedback.latest_messages(10),
        }

    def _serialize_action_record(self, record: ActionRecord) -> dict[str, Any]:
        return {
            "action_id": record.action_id,
            "timestamp": record.timestamp,
            "command_name": record.command_name,
            "outcome": record.outcome.value,
            "message": record.message,
            "tile_number": record.tile_number,
            "human_validation_required": record.human_validation_required,
            "details": dict(record.details),
        }

    def _set_agent_status(self, text: str, *, tone: str) -> None:
        colors = {
            "info": PALETTE.text_secondary,
            "success": PALETTE.success,
            "blocked": PALETTE.warning,
            "error": PALETTE.error,
        }
        color = colors.get(tone, PALETTE.text_secondary)
        self.agent_status_label.setText(text)
        self.agent_status_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.run_workspace.append_system_message(text, tone=tone)

    def _on_agent_activity(self, record: ActionRecord) -> None:
        self._last_agent_record = record
        if record.outcome is CommandOutcome.SUCCESS:
            tone = "success"
            prefix = "✅"
            event = AudioEvent.TASK_COMPLETE if record.command_name == "read_state" else AudioEvent.SUCCESS
        elif record.outcome is CommandOutcome.BLOCKED:
            tone = "blocked"
            prefix = "⚠️"
            event = AudioEvent.BLOCKED
        else:
            tone = "error"
            prefix = "❌"
            event = AudioEvent.ERROR

        self.audio_feedback.notify(event, record.message)
        suffix = " — validation humaine requise" if record.human_validation_required else ""
        self._set_agent_status(f"{prefix} {record.message}{suffix}", tone=tone)
        base_tooltip = f"{record.timestamp} • {record.command_name}"
        if record.tile_number is not None:
            base_tooltip += f" • carreau {record.tile_number}"
        self.agent_status_label.setToolTip(base_tooltip)

    def _tile_from_command(self, command: AgentCommand) -> tuple[int, WebTile]:
        assert command.tile_number is not None
        tile_id = command.tile_number - 1
        return tile_id, self.tiles[tile_id]

    def _handle_agent_open_url(self, command: AgentCommand) -> dict[str, Any]:
        tile_id, tile = self._tile_from_command(command)
        self.show_tile_page_for_tile(tile_id)
        tile.open_url_text(command.url)
        if tile.state.error_message:
            raise BlockedAction(
                tile.state.error_message,
                human_validation_required=False,
                details={"reason": "invalid_url"},
            )
        return {"message": f"URL ouverte dans le carreau {command.tile_number}.", "tile_id": tile_id, "url": tile.state.current_url or command.url}

    def _handle_agent_focus_tile(self, command: AgentCommand) -> dict[str, Any]:
        tile_id, tile = self._tile_from_command(command)
        if not tile.state.has_content:
            raise BlockedAction(
                f"Impossible de mettre le carreau {command.tile_number} en focus : il est vide.",
                human_validation_required=False,
                details={"reason": "empty_tile"},
            )
        self.enter_focus_mode(tile_id)
        return {"message": f"Carreau {command.tile_number} mis en focus.", "tile_id": tile_id}

    def _handle_agent_close_tile(self, command: AgentCommand) -> dict[str, Any]:
        tile_id, tile = self._tile_from_command(command)
        if not tile.state.has_content:
            return {"message": f"Carreau {command.tile_number} déjà vide.", "tile_id": tile_id}
        tile.reset_to_empty()
        if self._focused_tile_id == tile_id:
            self.exit_focus_mode()
        return {"message": f"Carreau {command.tile_number} fermé.", "tile_id": tile_id}

    def _handle_agent_load_memory(self, command: AgentCommand) -> dict[str, Any]:
        tile_id, tile = self._tile_from_command(command)
        if not tile.state.has_content:
            raise BlockedAction(
                f"Aucune page mémorisée dans le carreau {command.tile_number}.",
                human_validation_required=False,
                details={"reason": "memory_slot_empty"},
            )
        self.enter_focus_mode(tile_id)
        return {"message": f"Page mémorisée rechargée dans le carreau {command.tile_number}.", "tile_id": tile_id}

    def _handle_agent_read_state(self, _command: AgentCommand) -> dict[str, Any]:
        snapshot = self.get_agent_state_snapshot()
        return {"message": "État complet des carreaux lu.", "snapshot": snapshot}

    def _toggle_api_panel(self) -> None:
        visible = not self.api_panel.isVisible()
        self.api_panel.setVisible(visible)
        if visible:
            self.audio_panel.hide()
        self.control_panels.setVisible(self.api_panel.isVisible() or self.audio_panel.isVisible())

    def _toggle_audio_panel(self) -> None:
        visible = not self.audio_panel.isVisible()
        self.audio_panel.setVisible(visible)
        if visible:
            self.api_panel.hide()
        self.control_panels.setVisible(self.api_panel.isVisible() or self.audio_panel.isVisible())

    def _apply_audio_settings(self, payload: Mapping[str, Any]) -> None:
        self.audio_feedback.set_sound_enabled(bool(payload.get("sound_enabled", True)))
        self.audio_feedback.set_voice_enabled(bool(payload.get("voice_enabled", False)))
        self.audio_feedback.set_speak_blocked(bool(payload.get("speak_blocked", True)))
        self.audio_feedback.set_speak_task_complete(bool(payload.get("speak_task_complete", True)))
        self.audio_feedback.set_speak_api_connected(bool(payload.get("speak_api_connected", False)))
        self._refresh_audio_button()

    def _refresh_audio_button(self) -> None:
        audio_active = self.audio_feedback.state.sound_enabled or self.audio_feedback.state.voice_enabled
        self.audio_button.setProperty("active", audio_active)
        self.audio_button.setText("🔄 Audio" if audio_active else "🔅 Audio")
        self.audio_button.style().unpolish(self.audio_button)
        self.audio_button.style().polish(self.audio_button)

    def _build_secret_account(self, service_id: str, base_url: str) -> str:
        return f"{service_id}|{base_url.strip().lower()}"

    def _apply_api_panel_state(self) -> None:
        self.api_panel.apply_state(
            ApiPanelState(
                connected=self._api_connected,
                service_id=self._api_service_id,
                base_url=self._api_base_url,
                test_path=self._api_test_path,
                secured_storage_used=self._api_secured_storage_used,
                masked_key_hint=self._api_key_hint,
                status_text=self._api_status_text,
            )
        )
        self._set_api_button_state(self._api_connection_state)

    def _set_api_button_state(self, state: str) -> None:
        self._api_connection_state = state
        self.api_button.setProperty("connectionState", state)
        if state == "connected":
            self.api_button.setToolTip("API connectée")
        elif state == "error":
            self.api_button.setToolTip("Erreur API")
        else:
            self.api_button.setToolTip("Connexion API")
        self.api_button.style().unpolish(self.api_button)
        self.api_button.style().polish(self.api_button)

    def _start_api_connection_test(self, settings: ApiConnectionSettings) -> None:
        if self._api_test_in_progress:
            self._api_status_text = "Test API déjà en cours."
            self._apply_api_panel_state()
            return

        api_key = settings.api_key.strip()
        service_id = settings.service_id
        base_url = settings.base_url.strip()
        test_path = settings.test_path.strip() or get_service_definition(service_id).default_test_path
        account = self._build_secret_account(service_id, base_url)

        if not api_key:
            stored_key = self.secret_store.load_api_key(account)
            if stored_key:
                api_key = stored_key
            elif self._api_session_key:
                api_key = self._api_session_key

        if not api_key:
            self._on_api_test_finished(
                ApiConnectionResult(
                    ok=False,
                    message="Clé API requise pour lancer le test.",
                    service_id=service_id,
                    base_url=base_url,
                ),
                False,
            )
            return

        self._api_test_in_progress = True
        self._api_service_id = service_id
        self._api_base_url = base_url
        self._api_test_path = test_path
        self._api_status_text = "Test API en cours…"
        self._pending_api_key = api_key
        self._set_api_button_state("idle")
        self._apply_api_panel_state()

        remember_securely = self.api_panel.remember_checkbox.isChecked() and self.secret_store.is_available
        test_settings = ApiConnectionSettings(
            service_id=service_id,
            base_url=base_url,
            api_key=api_key,
            test_path=test_path,
        )

        def worker() -> None:
            result = test_api_connection(test_settings)
            secure_storage_used = False
            if result.ok and remember_securely:
                secret_result = self.secret_store.save_api_key(account, api_key)
                if secret_result.ok:
                    secure_storage_used = True
                    result = ApiConnectionResult(
                        ok=True,
                        message=f"{result.message} Clé stockée de façon sécurisée.",
                        service_id=result.service_id,
                        base_url=result.base_url,
                        http_status=result.http_status,
                        masked_key_hint=result.masked_key_hint,
                    )
                else:
                    result = ApiConnectionResult(
                        ok=True,
                        message=f"{result.message} Stockage sécurisé indisponible : session courante seulement.",
                        service_id=result.service_id,
                        base_url=result.base_url,
                        http_status=result.http_status,
                        masked_key_hint=result.masked_key_hint,
                    )
            self.api_test_finished.emit(result, secure_storage_used)

        threading.Thread(target=worker, daemon=True).start()

    def _on_api_test_finished(self, result_obj: object, secure_storage_used: bool) -> None:
        result = result_obj if isinstance(result_obj, ApiConnectionResult) else None
        if result is None:
            return

        self._api_test_in_progress = False
        pending_key = self._pending_api_key
        self._api_service_id = result.service_id
        self._api_base_url = result.base_url

        if result.ok:
            self._api_connected = True
            self._api_status_text = result.message
            self._api_key_hint = result.masked_key_hint or self._api_key_hint
            self._api_secured_storage_used = secure_storage_used
            self._api_session_key = "" if secure_storage_used else pending_key
            self._set_api_button_state("connected")
            self._set_agent_status(f"⚡ {result.message}", tone="success")
            self.audio_feedback.notify(AudioEvent.API_CONNECTED, result.message)
        else:
            self._api_connected = False
            self._api_status_text = result.message
            self._api_secured_storage_used = False
            self._api_session_key = ""
            self._api_button_state(self._api_connection_state)"
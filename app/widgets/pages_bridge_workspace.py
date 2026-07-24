from __future__ import annotations

import hashlib
import json
import time
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.arena_controller import ArenaController
from app.state import AppState, TileVisualStatus
from app.widgets.web_tile import WebTile


def _build_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("ControlPanel")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)
    heading = QLabel(title)
    heading.setStyleSheet("font-size: 16px; font-weight: 700;")
    layout.addWidget(heading)
    return card, layout


def _set_text(label: QLabel, value: object, default: str = "non mesuré") -> None:
    text = default if value in {None, ""} else str(value)
    label.setText(text)


class _BridgeRefreshSignals(QObject):
    snapshot_ready = Signal(int, object)
    snapshot_failed = Signal(int, str)


class _BridgeRefreshTask(QRunnable):
    def __init__(self, controller: ArenaController, generation: int, signals: _BridgeRefreshSignals) -> None:
        super().__init__()
        self._controller = controller
        self._generation = generation
        self._signals = signals

    def run(self) -> None:
        try:
            snapshot = self._controller.snapshot()
        except Exception as exc:  # pragma: no cover - defensive worker failure
            try:
                self._signals.snapshot_failed.emit(self._generation, str(exc))
            except RuntimeError:
                return
            return

        try:
            self._signals.snapshot_ready.emit(self._generation, deepcopy(snapshot))
        except RuntimeError:
            return


class PagesBridgeWorkspace(QFrame):
    back_requested = Signal()
    state_changed = Signal()

    def __init__(
        self,
        tiles: dict[int, WebTile],
        app_state: AppState,
        arena_controller: ArenaController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tiles = tiles
        self.app_state = app_state
        self.arena_controller = arena_controller
        self._selected_tile_id: int | None = app_state.bridge_target_tile_id
        self._draft_payload: dict[str, Any] = {}
        self._last_result: dict[str, Any] = {}
        self._request_counter = 0
        self._refresh_generation = 0
        self._active_generation = 0
        self._pending_generation = 0
        self._cached_snapshot: dict[str, Any] | None = None
        self._last_valid_snapshot: dict[str, Any] | None = None
        self._current_refresh_result: dict[str, Any] | None = None
        self._cached_snapshot_at = 0.0
        self._refresh_in_progress = False
        self._refresh_requested = False
        self._refresh_error = ""
        self._current_error = ""
        self._bridge_status = "AMBIGU"
        self._current_target_validation: dict[str, Any] = {
            "status": "NOT_CONFIGURED",
            "is_valid": False,
            "message": "",
            "label": "AMBIGU",
        }
        self._refresh_started_at = 0.0
        self._refresh_debounce_ms = 75
        self._refresh_timeout_ms = 15000
        self._refresh_shutdown = False
        self._bridge_locked = False
        self._bridge_refresh_signals = _BridgeRefreshSignals()
        self._bridge_refresh_signals.snapshot_ready.connect(self._on_refresh_snapshot_ready)
        self._bridge_refresh_signals.snapshot_failed.connect(self._on_refresh_snapshot_failed)
        self._bridge_refresh_pool = QThreadPool.globalInstance()
        self._refresh_debounce_timer = QTimer(self)
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.setInterval(self._refresh_debounce_ms)
        self._refresh_debounce_timer.timeout.connect(self._start_refresh_collection)
        self._refresh_timeout_timer = QTimer(self)
        self._refresh_timeout_timer.setSingleShot(True)
        self._refresh_timeout_timer.setInterval(self._refresh_timeout_ms)
        self._refresh_timeout_timer.timeout.connect(self._on_refresh_timeout)
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_column = QVBoxLayout()
        self.title_label = QLabel("PAGES / BRIDGE")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 800;")
        self.subtitle_label = QLabel(
            "Pont contrôlé vers ChatGPT, sélection explicite de la cible, et retour corrélé vers le terminal."
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setObjectName("MutedText")
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.subtitle_label)

        self.state_badge = QLabel("AMBIGU")
        self.state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_badge.setMinimumWidth(140)
        self.state_badge.setProperty("role", "statusBadge")

        self.refresh_button = QPushButton("Rafraîchir")
        self.refresh_button.setProperty("compact", True)
        self.lock_button = QPushButton("Verrouiller")
        self.lock_button.setProperty("compact", True)
        self.emergency_unlock_button = QPushButton("Emergency Unlock")
        self.emergency_unlock_button.setProperty("compact", True)

        self.back_button = QPushButton("Retour aux pages")
        self.back_button.setProperty("compact", True)
        self.back_button.clicked.connect(self.back_requested.emit)

        header.addLayout(title_column, 1)
        header.addWidget(self.state_badge)
        header.addWidget(self.refresh_button)
        header.addWidget(self.lock_button)
        header.addWidget(self.emergency_unlock_button)
        header.addWidget(self.back_button)
        root.addLayout(header)

        body = QGridLayout()
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(12)
        root.addLayout(body, 1)

        self.pages_card, self.pages_layout = _build_card("Pages disponibles")
        self.pages_table = QTableWidget(0, 7)
        self.pages_table.setHorizontalHeaderLabels(
            ["Tile", "Titre", "URL", "État", "Chargement", "Cible", "Dernier statut"]
        )
        self.pages_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pages_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pages_table.verticalHeader().setVisible(False)
        self.pages_table.setAlternatingRowColors(True)
        self.pages_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pages_table.itemSelectionChanged.connect(self._on_table_selection_changed)

        page_buttons = QHBoxLayout()
        self.select_target_button = QPushButton("Sélectionner comme cible ChatGPT")
        self.select_target_button.setProperty("role", "accent")
        self.test_target_button = QPushButton("Tester la cible")
        self.prepare_button = QPushButton("Préparer sans envoyer")
        self.view_report_button = QPushButton("Voir le rapport de job")
        for button in (
            self.select_target_button,
            self.test_target_button,
            self.prepare_button,
            self.view_report_button,
        ):
            page_buttons.addWidget(button)
        page_buttons.addStretch(1)

        self.pages_layout.addWidget(self.pages_table, 1)
        self.pages_layout.addLayout(page_buttons)

        self.bridge_card, self.bridge_layout = _build_card("Bridge Terminal ↔ ChatGPT")
        bridge_form = QFormLayout()
        bridge_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        bridge_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        bridge_form.setVerticalSpacing(6)

        self.selected_target_value = QLabel("AMBIGU")
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("Tile 1")
        self.target_apply_button = QPushButton("Edit")
        self.current_tile_value = QLabel("non mesuré")
        self.current_index_value = QLabel("non mesuré")
        self.current_url_value = QLabel("non mesuré")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["test-only", "no-enter", "send"])
        self.project_edit = QLineEdit("PROJECT-UNASSIGNED")
        self.job_edit = QLineEdit("JOB-UNASSIGNED")
        self.session_edit = QLineEdit("SESSION-UNASSIGNED")
        self.turn_edit = QLineEdit("1")
        self.request_edit = QLineEdit("")
        self.request_edit.setReadOnly(True)
        self.sha_edit = QLineEdit("")
        self.sha_edit.setReadOnly(True)
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText("Préparer ici le message Bridge à corréler.")
        self.message_edit.setMinimumHeight(160)

        for label, value in (
            ("Cible", self.selected_target_value),
            ("Cible éditable", self.target_edit),
            ("Appliquer", self.target_apply_button),
            ("Tile courant", self.current_tile_value),
            ("Index courant", self.current_index_value),
            ("URL courante", self.current_url_value),
            ("Mode", self.mode_combo),
            ("project_id", self.project_edit),
            ("job_id", self.job_edit),
            ("session_id", self.session_edit),
            ("turn_id", self.turn_edit),
            ("request_id", self.request_edit),
            ("sha256", self.sha_edit),
        ):
            bridge_form.addRow(label, value)

        bridge_buttons = QHBoxLayout()
        self.send_button = QPushButton("Envoyer")
        self.send_button.setProperty("role", "accent")
        self.cancel_button = QPushButton("Annuler")
        self.view_response_button = QPushButton("Voir la réponse")
        self.new_conversation_button = QPushButton("New Conversation")
        for button in (
            self.send_button,
            self.cancel_button,
            self.view_response_button,
            self.new_conversation_button,
        ):
            bridge_buttons.addWidget(button)
        bridge_buttons.addStretch(1)

        self.bridge_layout.addLayout(bridge_form)
        self.bridge_layout.addWidget(self.message_edit)
        self.bridge_layout.addLayout(bridge_buttons)

        self.result_card, self.result_layout = _build_card("Rapport de Bridge")
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText("Résultat, preuve de corrélation et dernier retour.")
        self.result_view.setMinimumHeight(200)
        self.result_layout.addWidget(self.result_view)

        self.health_card, self.health_layout = _build_card("Santé Bridge")
        health_form = QFormLayout()
        health_form.setVerticalSpacing(6)
        self.core_value = QLabel("non mesuré")
        self.jules_value = QLabel("non mesuré")
        self.bridge_value = QLabel("non mesuré")
        self.nino_value = QLabel("non mesuré")
        self.last_job_value = QLabel("non mesuré")
        self.last_request_value = QLabel("non mesuré")
        self.last_status_value = QLabel("non mesuré")
        self.last_block_value = QLabel("aucun")
        for label, value in (
            ("Antmux Core", self.core_value),
            ("Jules", self.jules_value),
            ("Bridge", self.bridge_value),
            ("Nino", self.nino_value),
            ("Dernier job", self.last_job_value),
            ("Dernier request_id", self.last_request_value),
            ("Dernier statut", self.last_status_value),
            ("Cause blocage", self.last_block_value),
        ):
            health_form.addRow(label, value)
        self.health_layout.addLayout(health_form)

        body.addWidget(self.pages_card, 0, 0)
        body.addWidget(self.bridge_card, 0, 1)
        body.addWidget(self.result_card, 1, 0)
        body.addWidget(self.health_card, 1, 1)

        self.refresh_button.clicked.connect(self.request_refresh_view)
        self.lock_button.clicked.connect(self.toggle_lock)
        self.emergency_unlock_button.clicked.connect(self.emergency_unlock)
        self.select_target_button.clicked.connect(self.select_current_row_as_target)
        self.target_apply_button.clicked.connect(self.apply_target_from_editor)
        self.test_target_button.clicked.connect(self.test_selected_target)
        self.prepare_button.clicked.connect(self.prepare_draft_only)
        self.send_button.clicked.connect(self.send_current_draft)
        self.cancel_button.clicked.connect(self.cancel_draft)
        self.view_response_button.clicked.connect(self.view_last_response)
        self.view_report_button.clicked.connect(self.view_job_report)
        self.new_conversation_button.clicked.connect(self.open_new_conversation)

        self.sync_target_from_state()
        self.refresh_from_cache()

    def activate(self) -> bool:
        self.sync_target_from_state()
        self.refresh_from_cache()
        if not self._refresh_shutdown and not self._refresh_requested and not self._refresh_in_progress:
            self.request_refresh(force=False)
        return True

    def refresh_view(self) -> None:
        self.refresh_from_cache()

    def request_refresh_view(self) -> None:
        self.refresh_from_cache()
        self.request_refresh(force=True)

    def refresh_from_cache(self) -> None:
        self._populate_table()
        self._sync_selection_widgets()
        self._refresh_result_view()
        self._render_cached_snapshot()

    def refresh_target_display(self) -> None:
        self._populate_table()
        self._sync_selection_widgets()
        self._render_cached_snapshot()

    def set_target_tile_id(self, tile_id: int | None) -> None:
        self._selected_tile_id = tile_id
        self.app_state.bridge_target_tile_id = tile_id
        self.refresh_target_display()

    def sync_target_from_state(self) -> None:
        self._selected_tile_id = self.app_state.bridge_target_tile_id
        self.refresh_target_display()

    def request_refresh(self, *, force: bool = False) -> bool:
        if self._refresh_shutdown:
            return False
        if self._refresh_in_progress:
            self._refresh_generation += 1
            self._refresh_requested = True
            self._pending_generation = self._refresh_generation
            return False

        if not force and self._cached_snapshot is not None and not self._is_snapshot_stale():
            return False

        self._refresh_generation += 1
        self._pending_generation = self._refresh_generation
        self._refresh_requested = True
        self._set_bridge_status("REFRESHING")
        self.subtitle_label.setText("Initialisation…")
        self.update_action_availability()
        self._refresh_debounce_timer.start()
        return True

    def shutdown(self) -> None:
        self._refresh_shutdown = True
        self._refresh_debounce_timer.stop()
        self._refresh_timeout_timer.stop()
        self._pending_generation = 0
        self._refresh_requested = False
        self._refresh_in_progress = False
        self.update_action_availability()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._refresh_shutdown:
            return
        if not self._refresh_requested and not self._refresh_in_progress:
            self.request_refresh(force=False)

    def select_current_row_as_target(self) -> None:
        row = self.pages_table.currentRow()
        if row < 0:
            self._append_result("AMBIGU: aucune ligne sélectionnée pour la cible ChatGPT.")
            return
        item = self.pages_table.item(row, 0)
        if item is None:
            self._append_result("AMBIGU: impossible de lire le tile sélectionné.")
            return
        tile_id = int(item.data(Qt.ItemDataRole.UserRole))
        if tile_id not in self.tiles:
            self._append_result(f"Cible invalide: tile {tile_id + 1}.")
            return
        self.set_target_tile_id(tile_id)
        if not self.session_edit.text().strip() or self.session_edit.text().startswith("SESSION-UNASSIGNED"):
            self.session_edit.setText(f"SESSION-TILE-{tile_id + 1:02d}")
        self._request_counter = max(self._request_counter, 0)
        self._append_result(
            f"CIBLE_VALIDEE: tile {tile_id + 1} ({self.tiles[tile_id].state.display_title})."
        )
        self.state_changed.emit()
        self.refresh_from_cache()

    def apply_target_from_editor(self) -> None:
        raw_value = self.target_edit.text().strip()
        if not raw_value:
            self.set_target_tile_id(None)
            self._append_result("CIBLE_EFFACEE: aucune cible explicite.")
            self.state_changed.emit()
            return
        try:
            tile_id = int(raw_value) - 1
        except ValueError:
            self._append_result("AMBIGU: la cible doit être un numéro de tile.")
            return
        if tile_id not in self.tiles:
            self._append_result(f"Cible invalide: tile {tile_id + 1}.")
            return
        self.set_target_tile_id(tile_id)
        self._append_result(f"CIBLE_EDITEE: tile {tile_id + 1} sélectionnée.")
        self.state_changed.emit()

    def toggle_lock(self) -> None:
        self._bridge_locked = not self._bridge_locked
        self.refresh_from_cache()

    def emergency_unlock(self) -> None:
        self._bridge_locked = False
        self._append_result("EMERGENCY_UNLOCK: bridge déverrouillé.")
        self.refresh_from_cache()

    def open_new_conversation(self) -> None:
        tile = self._selected_tile()
        if tile is None:
            self._append_result("BLOCKED: aucune cible ChatGPT explicite.")
            return
        tile.open_url_text("https://chatgpt.com/")
        self._append_result(f"NEW_CONVERSATION: tile {tile.tile_id + 1} ouverte sur ChatGPT.")
        self.state_changed.emit()
        self.refresh_view()

    def _require_valid_selected_tile(self, blocked_message: str) -> WebTile | None:
        validation = self._validate_selected_target()
        self._current_target_validation = validation
        if not validation.get("is_valid"):
            message = str(validation.get("message", "") or blocked_message)
            self._append_result(f"BLOCKED: {message}")
            return None
        tile = self._selected_tile()
        if tile is None:
            self._append_result(f"BLOCKED: {blocked_message}")
            return None
        return tile

    def test_selected_target(self) -> None:
        tile = self._require_valid_selected_tile("Cible ChatGPT non sélectionnée.")
        if tile is None:
            return
        result = tile.read_chatgpt_assistant_state()
        self._last_result = {
            "action": "test-target",
            "tile_id": tile.tile_id,
            "result": result,
        }
        self._append_result(json.dumps(self._last_result, ensure_ascii=False, indent=2))
        self.state_changed.emit()

    def prepare_draft_only(self) -> None:
        tile = self._require_valid_selected_tile("Cible ChatGPT non sélectionnée.")
        if tile is None:
            return
        draft = self._build_request_payload(tile, mode="no-enter")
        self._draft_payload = draft
        self._last_result = {"action": "prepare", "draft": draft}
        self._append_result(json.dumps(self._last_result, ensure_ascii=False, indent=2))
        self.state_changed.emit()
        self.refresh_view()

    def send_current_draft(self) -> None:
        tile = self._require_valid_selected_tile("Cible ChatGPT non sélectionnée.")
        if tile is None:
            return

        mode = self.mode_combo.currentText().strip().lower()
        draft = self._build_request_payload(tile, mode=mode)
        self._draft_payload = draft
        message = str(draft["message"])

        if mode == "test-only":
            result = tile.read_chatgpt_assistant_state()
        elif mode == "no-enter":
            result = tile.send_text_to_active_web_page(message, submit=False, one_shot=False)
        else:
            result = tile.send_chatgpt_bridge_message(
                message,
                str(draft["transmission_key"]),
                max_attempts=5,
                retry_delay_ms=1000,
            )

        self._last_result = {
            "action": "send",
            "mode": mode,
            "draft": draft,
            "result": result,
        }
        self._append_result(json.dumps(self._last_result, ensure_ascii=False, indent=2))
        self.state_changed.emit()
        self.refresh_view()

    def cancel_draft(self) -> None:
        self._draft_payload = {}
        self._last_result = {"action": "cancel", "status": "CANCELLED"}
        self._append_result("CANCELLED: brouillon et métadonnées réinitialisés.")
        self.state_changed.emit()
        self.refresh_view()

    def view_last_response(self) -> None:
        if not self._last_result:
            self._append_result("Aucune réponse disponible.")
            return
        self._append_result(json.dumps(self._last_result, ensure_ascii=False, indent=2))

    def view_job_report(self) -> None:
        snapshot = self._cached_snapshot
        if snapshot is None:
            self._append_result("REPORT_DEFERRED: initialisation Bridge en cours.")
            self.request_refresh(force=False)
            return
        report = {
            "arena_state": snapshot.get("arena_state"),
            "core": snapshot.get("core"),
            "reine": snapshot.get("reine"),
            "bridge": snapshot.get("core", {}).get("bridge") if isinstance(snapshot.get("core"), dict) else None,
            "jules": snapshot.get("core", {}).get("jules") if isinstance(snapshot.get("core"), dict) else None,
            "d_only": snapshot.get("d_only"),
        }
        self._last_result = {"action": "report", "report": report}
        self._append_result(json.dumps(self._last_result, ensure_ascii=False, indent=2))

    def _set_current_error(self, message: str) -> None:
        self._current_error = message
        self._refresh_error = message

    def _set_last_valid_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        if snapshot is None:
            self._cached_snapshot = None
            self._last_valid_snapshot = None
            return
        copied = deepcopy(snapshot)
        self._cached_snapshot = copied
        self._last_valid_snapshot = copied
        self._cached_snapshot_at = time.monotonic()

    def _is_chatgpt_origin(self, raw_url: str) -> bool:
        clean_url = raw_url.strip()
        if not clean_url:
            return False
        parsed = urlsplit(clean_url)
        hostname = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and hostname == "chatgpt.com"

    def _chatgpt_candidate_count(self) -> int:
        count = 0
        for tile in self.tiles.values():
            state = tile.state
            if not bool(getattr(state, "has_content", False)):
                continue
            if bool(getattr(state, "is_loading", False)):
                continue
            current_url = str(getattr(state, "current_url", "") or "").strip()
            if current_url and self._is_chatgpt_origin(current_url):
                count += 1
        return count

    def _validate_selected_target(self) -> dict[str, Any]:
        tile_id = self._selected_tile_id
        if tile_id is None:
            return {
                "status": "NOT_CONFIGURED",
                "is_valid": False,
                "message": "",
                "label": "AMBIGU",
            }

        tile = self.tiles.get(tile_id)
        tile_number = tile_id + 1
        if tile is None:
            return {
                "status": "INVALID_TILE",
                "is_valid": False,
                "message": f"Cible explicite invalide: Tile {tile_number} n'existe plus.",
                "label": f"Tile {tile_number} • INVALIDE",
            }

        state = tile.state
        current_url = str(getattr(state, "current_url", "") or "").strip()
        has_content = bool(getattr(state, "has_content", False))
        is_loading = bool(getattr(state, "is_loading", False))
        status_value = getattr(state, "status", TileVisualStatus.EMPTY)

        if not has_content:
            return {
                "status": "NOT_LOADED",
                "is_valid": False,
                "message": f"Cible explicite invalide: Tile {tile_number} n'est pas chargée.",
                "label": f"Tile {tile_number} • INVALIDE",
            }

        if is_loading or status_value == TileVisualStatus.LOADING:
            return {
                "status": "NOT_LOADED",
                "is_valid": False,
                "message": f"Cible explicite invalide: Tile {tile_number} est encore en chargement.",
                "label": f"Tile {tile_number} • INVALIDE",
            }

        if not current_url:
            return {
                "status": "PAGE_UNAVAILABLE",
                "is_valid": False,
                "message": f"Cible explicite invalide: Tile {tile_number} n'a pas d'URL actuelle.",
                "label": f"Tile {tile_number} • INVALIDE",
            }

        if not self._is_chatgpt_origin(current_url):
            return {
                "status": "WRONG_ORIGIN",
                "is_valid": False,
                "message": (
                    f"Cible explicite invalide: Tile {tile_number} pointe vers une origine non autorisée ({current_url})."
                ),
                "label": f"Tile {tile_number} • INVALIDE",
            }

        if status_value not in {TileVisualStatus.READY, TileVisualStatus.LOADING}:
            return {
                "status": "PAGE_UNAVAILABLE",
                "is_valid": False,
                "message": f"Cible explicite invalide: Tile {tile_number} n'est pas prête.",
                "label": f"Tile {tile_number} • INVALIDE",
            }

        return {
            "status": "VALID",
            "is_valid": True,
            "message": "",
            "label": f"Tile {tile_number} • {state.display_title}",
        }

    def _selected_tile(self) -> WebTile | None:
        if self._selected_tile_id is None:
            return None
        return self.tiles.get(self._selected_tile_id)

    def _on_table_selection_changed(self) -> None:
        row = self.pages_table.currentRow()
        if row < 0:
            return
        item = self.pages_table.item(row, 0)
        if item is None:
            return
        tile_id = int(item.data(Qt.ItemDataRole.UserRole))
        tile = self.tiles.get(tile_id)
        if tile is None:
            return
        self.selected_target_value.setText(f"Tile {tile_id + 1} • {tile.state.display_title}")

    def _render_cached_snapshot(self) -> None:
        validation = self._validate_selected_target()
        self._current_target_validation = validation
        explicit_target = self._selected_tile_id is not None
        candidate_count = self._chatgpt_candidate_count()
        display_snapshot = self._cached_snapshot if self._cached_snapshot is not None else self._current_refresh_result
        has_valid_cache = self._cached_snapshot is not None
        has_current_result = self._current_refresh_result is not None

        if self._refresh_in_progress:
            bridge_status = "REFRESHING"
            subtitle = "Initialisation…"
        elif self._refresh_error:
            bridge_status = "DEGRADED" if (has_valid_cache or has_current_result) else "ERROR"
            subtitle = f"Bridge indisponible: {self._refresh_error}"
        elif explicit_target and not validation.get("is_valid"):
            bridge_status = "DEGRADED" if (has_valid_cache or has_current_result) else "ERROR"
            subtitle = f"Bridge indisponible: {validation.get('message', '') or 'cible invalide'}"
        elif display_snapshot is not None:
            core = display_snapshot.get("core", {})
            bridge_status = "READY"
            subtitle = (
                f"{display_snapshot.get('workers_active', 0)} worker(s), core "
                f"{core.get('status', 'UNKNOWN') if isinstance(core, dict) else 'UNKNOWN'}"
            )
        else:
            bridge_status = "IDLE"
            subtitle = "Bridge en attente d'initialisation."

        self._set_bridge_status(bridge_status)
        self.subtitle_label.setText(subtitle)

        if display_snapshot is None:
            _set_text(self.core_value, None)
            _set_text(self.jules_value, None)
            _set_text(self.bridge_value, None)
            _set_text(self.nino_value, None)
            _set_text(self.last_job_value, None)
            _set_text(self.last_request_value, self._draft_payload.get("request_id"))
            _set_text(
                self.last_status_value,
                self._last_result.get("result", {}).get("status")
                if isinstance(self._last_result.get("result"), dict)
                else self._last_result.get("action"),
            )
            _set_text(self.last_block_value, validation.get("message") or self._refresh_error or "aucun")
            if explicit_target:
                target_label = validation.get("label", "AMBIGU")
            elif candidate_count > 1:
                target_label = "AMBIGU"
            else:
                target_label = "Aucune cible explicite"
            self.selected_target_value.setText(target_label)
            self.update_action_availability()
            return

        core = display_snapshot.get("core", {})
        jules = core.get("jules", {}) if isinstance(core, dict) else {}
        bridge = core.get("bridge", {}) if isinstance(core, dict) else {}
        _set_text(self.core_value, core.get("status") if isinstance(core, dict) else None)
        _set_text(self.jules_value, f"{jules.get('status', 'UNKNOWN')} | PID {jules.get('pid') or 'n/a'}")
        _set_text(self.bridge_value, f"{bridge.get('status', 'UNKNOWN')} | PID {bridge.get('pid') or 'n/a'}")
        _set_text(self.nino_value, "ACTIVE" if display_snapshot.get("nino_active") else "OFFLINE")
        _set_text(
            self.last_job_value,
            display_snapshot.get("jobs", [])[-1]["job_id"] if display_snapshot.get("jobs") else None,
        )
        _set_text(self.last_request_value, self._draft_payload.get("request_id"))
        _set_text(
            self.last_status_value,
            self._last_result.get("result", {}).get("status")
            if isinstance(self._last_result.get("result"), dict)
            else self._last_result.get("action"),
        )
        _set_text(
            self.last_block_value,
            self._refresh_error or validation.get("message") or display_snapshot.get("d_only", {}).get("last_refusal"),
        )
        if explicit_target:
            target_label = validation.get("label", "AMBIGU")
        elif candidate_count > 1:
            target_label = "AMBIGU"
        else:
            target_label = "Aucune cible explicite"
        self.selected_target_value.setText(target_label)
        self.update_action_availability()

    def _set_bridge_status(self, status: str) -> None:
        self._bridge_status = status
        self.state_badge.setText(status)
        self.state_badge.setProperty("arenaState", status)
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)

    def update_action_availability(self) -> None:
        validation = self._current_target_validation or self._validate_selected_target()
        bridge_status = str(self._bridge_status or "").strip().upper()
        actions_enabled = bool(validation.get("is_valid"))
        actions_enabled = actions_enabled and not self._refresh_shutdown
        actions_enabled = actions_enabled and not self._refresh_in_progress
        actions_enabled = actions_enabled and not self._refresh_requested
        actions_enabled = actions_enabled and bridge_status not in {"REFRESHING", "DEGRADED", "ERROR"}
        actions_enabled = actions_enabled and not self._bridge_locked
        for widget in (
            self.select_target_button,
            self.target_edit,
            self.target_apply_button,
            self.test_target_button,
            self.prepare_button,
            self.send_button,
            self.cancel_button,
            self.view_response_button,
            self.view_report_button,
            self.new_conversation_button,
        ):
            widget.setEnabled(actions_enabled)
        self.lock_button.setEnabled(not self._refresh_shutdown)
        self.emergency_unlock_button.setEnabled(self._bridge_locked)
        self.lock_button.setText("Déverrouiller" if self._bridge_locked else "Verrouiller")
        self.target_edit.setText("" if self._selected_tile_id is None else str(self._selected_tile_id + 1))

    def _is_snapshot_stale(self) -> bool:
        if self._cached_snapshot is None:
            return True
        if self._cached_snapshot_at <= 0:
            return False
        return (time.monotonic() - self._cached_snapshot_at) > 5.0

    def _start_refresh_collection(self) -> None:
        if self._refresh_shutdown or self._refresh_in_progress or not self._refresh_requested:
            return
        generation = self._pending_generation or self._refresh_generation
        self._active_generation = generation
        self._refresh_requested = False
        self._refresh_in_progress = True
        self._refresh_started_at = time.monotonic()
        self._refresh_timeout_timer.start()
        task = _BridgeRefreshTask(self.arena_controller, generation, self._bridge_refresh_signals)
        self._bridge_refresh_pool.start(task)

    def _finish_refresh_collection(self) -> None:
        self._refresh_in_progress = False
        self._refresh_timeout_timer.stop()

    def _on_refresh_snapshot_ready(self, generation: int, snapshot: object) -> None:
        if self._refresh_shutdown:
            return
        if generation != self._refresh_generation:
            if self._refresh_in_progress:
                self._finish_refresh_collection()
                if self._refresh_requested:
                    self._refresh_debounce_timer.start()
            return
        self._finish_refresh_collection()
        self._current_refresh_result = deepcopy(snapshot) if isinstance(snapshot, dict) else None
        if not isinstance(snapshot, dict):
            self._set_current_error("Bridge snapshot invalide.")
            self._render_cached_snapshot()
            return
        validation = self._validate_selected_target()
        self._current_target_validation = validation
        if validation.get("is_valid"):
            self._set_last_valid_snapshot(snapshot)
            self._set_current_error("")
        else:
            self._set_current_error(str(validation.get("message", "") or "Cible Bridge invalide."))
        self._render_cached_snapshot()
        self._refresh_result_view()
        if self._pending_generation > generation:
            self._refresh_requested = True
            self._refresh_debounce_timer.start()

    def _on_refresh_snapshot_failed(self, generation: int, message: str) -> None:
        if self._refresh_shutdown:
            return
        if generation != self._refresh_generation:
            if self._refresh_in_progress:
                self._finish_refresh_collection()
                if self._refresh_requested:
                    self._refresh_debounce_timer.start()
            return
        self._finish_refresh_collection()
        self._current_refresh_result = None
        self._set_current_error(message or "Bridge snapshot failed.")
        self._render_cached_snapshot()
        if self._pending_generation > generation:
            self._refresh_requested = True
            self._refresh_debounce_timer.start()

    def _on_refresh_timeout(self) -> None:
        if not self._refresh_in_progress:
            return
        timed_out_generation = self._active_generation
        self._finish_refresh_collection()
        if self._refresh_generation == timed_out_generation:
            self._refresh_generation += 1
            self._pending_generation = self._refresh_generation
            self._refresh_requested = False
        else:
            self._refresh_requested = True
            self._refresh_debounce_timer.start()
        self._current_refresh_result = None
        self._set_current_error("Bridge refresh timed out.")
        self._render_cached_snapshot()

    def _populate_table(self) -> None:
        rows = sorted(self.tiles.items())
        self.pages_table.setRowCount(len(rows))
        for row, (tile_id, tile) in enumerate(rows):
            state = tile.state
            values = [
                f"Tile {tile_id + 1}",
                state.display_title,
                state.current_url or "—",
                state.status.value.upper() if isinstance(state.status, TileVisualStatus) else str(state.status),
                "LOADING" if state.is_loading else "READY" if state.has_content else "EMPTY",
                "YES" if self._selected_tile_id == tile_id else "NO",
                self._last_result.get("result", {}).get("status") if self._selected_tile_id == tile_id and isinstance(self._last_result.get("result"), dict) else "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, tile_id)
                self.pages_table.setItem(row, column, item)

        self.pages_table.resizeColumnsToContents()
        self.pages_table.horizontalHeader().setStretchLastSection(True)
        if self._selected_tile_id is not None:
            for row, (tile_id, _tile) in enumerate(rows):
                if tile_id == self._selected_tile_id:
                    self.pages_table.selectRow(row)
                    break

    def _sync_selection_widgets(self) -> None:
        if self._selected_tile_id is None:
            self.current_tile_value.setText("AMBIGU")
            self.current_index_value.setText("non mesuré")
            self.current_url_value.setText("non mesuré")
            return
        tile = self.tiles.get(self._selected_tile_id)
        if tile is None:
            self.current_tile_value.setText(f"Tile {self._selected_tile_id + 1} • INVALIDE")
            self.current_index_value.setText(str(self._selected_tile_id + 1))
            self.current_url_value.setText("non mesuré")
            return
        current_session = self.session_edit.text().strip()
        if not current_session or current_session.startswith("SESSION-UNASSIGNED"):
            self.session_edit.setText(f"SESSION-TILE-{tile.tile_id + 1:02d}")
        self.current_tile_value.setText(f"Tile {tile.tile_id + 1} • {tile.state.display_title}")
        self.current_index_value.setText(str(tile.tile_id + 1))
        self.current_url_value.setText(tile.state.current_url or "—")

    def _build_request_payload(self, tile: WebTile, *, mode: str) -> dict[str, Any]:
        message = self.message_edit.toPlainText().strip()
        if not message:
            message = f"Bridge test for tile {tile.tile_id + 1}"

        if not self.request_edit.text().strip():
            self._request_counter += 1
            request_id = f"bridge-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"
            self.request_edit.setText(request_id)
        else:
            request_id = self.request_edit.text().strip()

        project_id = self.project_edit.text().strip() or "PROJECT-UNASSIGNED"
        job_id = self.job_edit.text().strip() or "JOB-UNASSIGNED"
        session_id = self.session_edit.text().strip() or f"SESSION-TILE-{tile.tile_id + 1:02d}"
        turn_id = self.turn_edit.text().strip() or "1"

        payload_seed = {
            "project_id": project_id,
            "job_id": job_id,
            "request_id": request_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "tile_id": tile.tile_id,
            "mode": mode,
            "message": message,
        }
        sha256 = hashlib.sha256(
            json.dumps(payload_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.sha_edit.setText(sha256)

        transmission_key = ";".join(
            (
                f"project_id={project_id}",
                f"job_id={job_id}",
                f"request_id={request_id}",
                f"session_id={session_id}",
                f"turn_id={turn_id}",
            )
        )
        draft = {
            **payload_seed,
            "sha256": sha256,
            "transmission_key": transmission_key,
            "selected_tile_id": tile.tile_id,
            "selected_tile_title": tile.state.display_title,
            "selected_tile_url": tile.state.current_url,
            "selected_tile_status": tile.state.status.value,
        }
        self.request_edit.setText(request_id)
        self._draft_payload = draft
        return draft

    def _append_result(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.result_view.appendPlainText(f"[{stamp}] {clean}")
        self.result_view.verticalScrollBar().setValue(self.result_view.verticalScrollBar().maximum())

    def _refresh_result_view(self) -> None:
        if self._last_result:
            self.result_view.setPlainText(json.dumps(self._last_result, ensure_ascii=False, indent=2))

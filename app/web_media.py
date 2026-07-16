from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Callable
from urllib.parse import quote

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePermission, QWebEngineProfile
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import app_data_root

MEDIA_PERMISSION_ASK = "ask"
MEDIA_PERMISSION_ALLOW = "allow"
MEDIA_PERMISSION_DENY = "deny"
MEDIA_PERMISSION_VALUES = (
    MEDIA_PERMISSION_ASK,
    MEDIA_PERMISSION_ALLOW,
    MEDIA_PERMISSION_DENY,
)

MEDIA_RESOURCE_MICROPHONE = "microphone"
MEDIA_RESOURCE_CAMERA = "camera"
MEDIA_RESOURCES = (
    MEDIA_RESOURCE_MICROPHONE,
    MEDIA_RESOURCE_CAMERA,
)

TEST_MEDIA_HOST = "127.0.0.1"
TEST_MEDIA_PORT_START = 8876
TEST_MEDIA_PORT_END = 8890


def _origin_to_key(origin: QUrl) -> str:
    scheme = origin.scheme().strip().lower()
    host = origin.host().strip().lower()
    if not scheme or not host:
        return ""
    port = origin.port(-1)
    if port > 0:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _permission_store_path() -> Path:
    path = app_data_root() / "permissions" / "web-media.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _permission_type_resources(
    permission_type: QWebEnginePermission.PermissionType,
) -> tuple[str, ...]:
    if permission_type == QWebEnginePermission.PermissionType.MediaAudioCapture:
        return (MEDIA_RESOURCE_MICROPHONE,)
    if permission_type == QWebEnginePermission.PermissionType.MediaVideoCapture:
        return (MEDIA_RESOURCE_CAMERA,)
    if permission_type == QWebEnginePermission.PermissionType.MediaAudioVideoCapture:
        return (MEDIA_RESOURCE_MICROPHONE, MEDIA_RESOURCE_CAMERA)
    return ()


def _resource_label(resource: str) -> str:
    if resource == MEDIA_RESOURCE_MICROPHONE:
        return "Microphone"
    if resource == MEDIA_RESOURCE_CAMERA:
        return "Caméra"
    return resource


def _resource_icon_text(resources: tuple[str, ...]) -> str:
    has_microphone = MEDIA_RESOURCE_MICROPHONE in resources
    has_camera = MEDIA_RESOURCE_CAMERA in resources
    if has_microphone and has_camera:
        return "🎤 📷"
    if has_microphone:
        return "🎤"
    if has_camera:
        return "📷"
    return ""


def _decision_label(value: str) -> str:
    if value == MEDIA_PERMISSION_ALLOW:
        return "Toujours autoriser"
    if value == MEDIA_PERMISSION_DENY:
        return "Toujours refuser"
    return "Demander"


def _safe_write_json(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)


@dataclass(frozen=True)
class MediaPermissionRequestResult:
    action: str


class WebMediaPermissionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _permission_store_path()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"origins": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"origins": {}}
        if not isinstance(data, dict):
            return {"origins": {}}
        origins = data.get("origins")
        if not isinstance(origins, dict):
            return {"origins": {}}
        normalized: dict[str, dict[str, str]] = {}
        for origin, values in origins.items():
            if not isinstance(origin, str) or not isinstance(values, dict):
                continue
            normalized[origin] = {
                MEDIA_RESOURCE_MICROPHONE: self._normalize_value(values.get(MEDIA_RESOURCE_MICROPHONE)),
                MEDIA_RESOURCE_CAMERA: self._normalize_value(values.get(MEDIA_RESOURCE_CAMERA)),
            }
        return {"origins": normalized}

    def _normalize_value(self, value: object) -> str:
        text = str(value or "").strip().lower()
        if text in MEDIA_PERMISSION_VALUES:
            return text
        return MEDIA_PERMISSION_ASK

    def reload(self) -> None:
        self._data = self._load()

    def save(self) -> None:
        _safe_write_json(self.path, self._data)

    def permissions_for_origin(self, origin_key: str) -> dict[str, str]:
        origins = self._data.setdefault("origins", {})
        values = origins.setdefault(
            origin_key,
            {
                MEDIA_RESOURCE_MICROPHONE: MEDIA_PERMISSION_ASK,
                MEDIA_RESOURCE_CAMERA: MEDIA_PERMISSION_ASK,
            },
        )
        return {
            MEDIA_RESOURCE_MICROPHONE: self._normalize_value(values.get(MEDIA_RESOURCE_MICROPHONE)),
            MEDIA_RESOURCE_CAMERA: self._normalize_value(values.get(MEDIA_RESOURCE_CAMERA)),
        }

    def decision_for(self, origin_key: str, resource: str) -> str:
        return self.permissions_for_origin(origin_key).get(resource, MEDIA_PERMISSION_ASK)

    def set_decision(self, origin_key: str, resource: str, decision: str) -> None:
        values = self.permissions_for_origin(origin_key)
        values[resource] = self._normalize_value(decision)
        self._data.setdefault("origins", {})[origin_key] = values
        self.save()

    def set_many(self, origin_key: str, decisions: dict[str, str]) -> None:
        values = self.permissions_for_origin(origin_key)
        for resource, decision in decisions.items():
            if resource in MEDIA_RESOURCES:
                values[resource] = self._normalize_value(decision)
        self._data.setdefault("origins", {})[origin_key] = values
        self.save()

    def reset_origin_to_ask(self, origin_key: str) -> None:
        self._data.setdefault("origins", {})[origin_key] = {
            MEDIA_RESOURCE_MICROPHONE: MEDIA_PERMISSION_ASK,
            MEDIA_RESOURCE_CAMERA: MEDIA_PERMISSION_ASK,
        }
        self.save()

    def delete_origin(self, origin_key: str) -> None:
        self._data.setdefault("origins", {}).pop(origin_key, None)
        self.save()

    def reset_all(self) -> None:
        self._data = {"origins": {}}
        self.save()

    def items(self) -> list[tuple[str, dict[str, str]]]:
        origins = self._data.setdefault("origins", {})
        return sorted(
            (
                origin,
                {
                    MEDIA_RESOURCE_MICROPHONE: self._normalize_value(values.get(MEDIA_RESOURCE_MICROPHONE)),
                    MEDIA_RESOURCE_CAMERA: self._normalize_value(values.get(MEDIA_RESOURCE_CAMERA)),
                },
            )
            for origin, values in origins.items()
            if isinstance(origin, str) and isinstance(values, dict)
        )


class _SilentStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:  # pragma: no cover - silence only
        return


class LocalWebMediaTestServer:
    def __init__(self, asset_root: Path) -> None:
        self.asset_root = asset_root
        self.host = TEST_MEDIA_HOST
        self.port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return

        last_error: Exception | None = None
        for port in range(TEST_MEDIA_PORT_START, TEST_MEDIA_PORT_END + 1):
            try:
                directory = str(self.asset_root)
                handler = lambda *args, directory=directory, **kwargs: _SilentStaticHandler(
                    *args,
                    directory=directory,
                    **kwargs,
                )
                server = ThreadingHTTPServer((self.host, port), handler)
                break
            except OSError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Impossible de démarrer le serveur de test média local: {last_error}")

        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="nino-web-media-test-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self.port = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=3.0)

    def url(self, host: str = "127.0.0.1") -> str:
        self.start()
        assert self.port is not None
        return f"http://{host}:{self.port}/index.html"


class MediaPermissionRequestDialog(QDialog):
    ACTION_ALLOW_ONCE = "allow-once"
    ACTION_ALLOW_ALWAYS = "allow-always"
    ACTION_DENY_ONCE = "deny-once"
    ACTION_DENY_ALWAYS = "deny-always"

    def __init__(
        self,
        origin_key: str,
        full_url: str,
        tile_id: int,
        resources: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autorisation média Web")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.result_action = self.ACTION_DENY_ONCE

        root = QVBoxLayout(self)
        root.setSpacing(12)

        intro = QLabel("Une page Web ouverte dans Nino demande un accès média.")
        intro.setWordWrap(True)
        intro.setObjectName("SecondaryText")

        details = QGroupBox("Demande")
        details_layout = QFormLayout(details)
        details_layout.addRow("Origine :", QLabel(origin_key))
        details_layout.addRow("Adresse :", QLabel(full_url or origin_key))
        details_layout.addRow("Carreau :", QLabel(str(tile_id + 1)))

        resources_box = QGroupBox("Ressources demandées")
        resources_layout = QVBoxLayout(resources_box)
        for resource in resources:
            resources_layout.addWidget(QLabel(f"{_resource_icon_text((resource,))} {_resource_label(resource)}"))

        buttons = QGridLayout()
        self.allow_once_button = QPushButton("Autoriser une fois")
        self.allow_once_button.setObjectName("mediaAllowOnceButton")
        self.allow_always_button = QPushButton("Toujours autoriser")
        self.allow_always_button.setObjectName("mediaAllowAlwaysButton")
        self.deny_once_button = QPushButton("Refuser")
        self.deny_once_button.setObjectName("mediaDenyOnceButton")
        self.deny_always_button = QPushButton("Toujours refuser")
        self.deny_always_button.setObjectName("mediaDenyAlwaysButton")

        self.allow_once_button.clicked.connect(lambda: self._finish(self.ACTION_ALLOW_ONCE))
        self.allow_always_button.clicked.connect(lambda: self._finish(self.ACTION_ALLOW_ALWAYS))
        self.deny_once_button.clicked.connect(lambda: self._finish(self.ACTION_DENY_ONCE))
        self.deny_always_button.clicked.connect(lambda: self._finish(self.ACTION_DENY_ALWAYS))

        buttons.addWidget(self.allow_once_button, 0, 0)
        buttons.addWidget(self.allow_always_button, 0, 1)
        buttons.addWidget(self.deny_once_button, 1, 0)
        buttons.addWidget(self.deny_always_button, 1, 1)

        root.addWidget(intro)
        root.addWidget(details)
        root.addWidget(resources_box)
        root.addLayout(buttons)

    def _finish(self, action: str) -> None:
        self.result_action = action
        self.accept()

    @classmethod
    def request_decision(
        cls,
        origin_key: str,
        full_url: str,
        tile_id: int,
        resources: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> MediaPermissionRequestResult:
        dialog = cls(origin_key, full_url, tile_id, resources, parent=parent)
        dialog.exec()
        return MediaPermissionRequestResult(dialog.result_action)


class MediaPermissionsPanelDialog(QDialog):
    def __init__(self, controller: WebMediaPermissionController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._loading = False
        self.setWindowTitle("Permissions microphone et caméra")
        self.setModal(True)
        self.resize(860, 520)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info = QLabel(
            "Décisions persistantes par origine. Les autorisations temporaires ne sont jamais enregistrées."
        )
        info.setWordWrap(True)
        info.setObjectName("SecondaryText")

        self.path_label = QLabel(f"Registre : {self.controller.store.path}")
        self.path_label.setWordWrap(True)
        self.path_label.setObjectName("SecondaryText")

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Origine", "Microphone", "Caméra"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.reset_site_button = QPushButton("Remettre le site sur demander")
        self.delete_site_button = QPushButton("Supprimer le site")
        self.reset_all_button = QPushButton("Réinitialiser toutes les permissions Web")
        self.open_localhost_button = QPushButton("Ouvrir le test localhost")
        self.open_loopback_button = QPushButton("Ouvrir le test 127.0.0.1")
        self.close_button = QPushButton("Fermer")

        self.reset_site_button.clicked.connect(self._reset_selected_site)
        self.delete_site_button.clicked.connect(self._delete_selected_site)
        self.reset_all_button.clicked.connect(self._reset_all_sites)
        self.open_localhost_button.clicked.connect(lambda: self.controller.open_test_page("localhost"))
        self.open_loopback_button.clicked.connect(lambda: self.controller.open_test_page("127.0.0.1"))
        self.close_button.clicked.connect(self.accept)

        actions.addWidget(self.reset_site_button)
        actions.addWidget(self.delete_site_button)
        actions.addStretch(1)
        actions.addWidget(self.open_localhost_button)
        actions.addWidget(self.open_loopback_button)

        button_box = QDialogButtonBox()
        button_box.addButton(self.reset_all_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(self.close_button, QDialogButtonBox.ButtonRole.AcceptRole)

        root.addWidget(info)
        root.addWidget(self.path_label)
        root.addWidget(self.table, 1)
        root.addLayout(actions)
        root.addWidget(button_box)

        self.controller.permissions_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        try:
            rows = self.controller.list_permissions()
            self.table.setRowCount(len(rows))
            for row_index, (origin, values) in enumerate(rows):
                origin_item = QTableWidgetItem(origin)
                self.table.setItem(row_index, 0, origin_item)
                self.table.setCellWidget(
                    row_index,
                    1,
                    self._build_decision_combo(origin, MEDIA_RESOURCE_MICROPHONE, values[MEDIA_RESOURCE_MICROPHONE]),
                )
                self.table.setCellWidget(
                    row_index,
                    2,
                    self._build_decision_combo(origin, MEDIA_RESOURCE_CAMERA, values[MEDIA_RESOURCE_CAMERA]),
                )
            self.table.resizeColumnsToContents()
        finally:
            self._loading = False
            self._update_buttons()

    def _build_decision_combo(self, origin: str, resource: str, value: str) -> QComboBox:
        combo = QComboBox()
        for entry in MEDIA_PERMISSION_VALUES:
            combo.addItem(_decision_label(entry), entry)
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(
            lambda _index, combo=combo, origin=origin, resource=resource: self._combo_changed(
                combo,
                origin,
                resource,
            )
        )
        return combo

    def _combo_changed(self, combo: QComboBox, origin: str, resource: str) -> None:
        if self._loading:
            return
        self.controller.set_permission(origin, resource, str(combo.currentData()))

    def _selected_origin(self) -> str | None:
        selected_items = self.table.selectedItems()
        if not selected_items:
            return None
        row = selected_items[0].row()
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.text().strip() or None

    def _update_buttons(self) -> None:
        has_selection = self._selected_origin() is not None
        self.reset_site_button.setEnabled(has_selection)
        self.delete_site_button.setEnabled(has_selection)

    def _reset_selected_site(self) -> None:
        origin = self._selected_origin()
        if origin is None:
            return
        self.controller.reset_origin_to_ask(origin)

    def _delete_selected_site(self) -> None:
        origin = self._selected_origin()
        if origin is None:
            return
        self.controller.delete_origin(origin)

    def _reset_all_sites(self) -> None:
        result = QMessageBox.question(
            self,
            "Réinitialiser les permissions Web",
            "Supprimer toutes les décisions microphone et caméra enregistrées ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset_all_permissions()


class WebMediaPermissionController(QObject):
    permissions_changed = Signal()

    def __init__(self, profile: QWebEngineProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.store = WebMediaPermissionStore()
        self.profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime
        )
        self._temporary_grants: dict[int, list[QWebEnginePermission]] = {}
        self._clear_profile_media_permissions()
        asset_root = Path(__file__).resolve().parent / "assets" / "web_media_test"
        self.test_server = LocalWebMediaTestServer(asset_root)
        self.test_server.start()
        self._tile_pages: dict[int, object] = {}
        self._page_tiles: dict[int, object] = {}
        self._open_test_page_callback: Callable[[str], None] | None = None

    def set_test_page_opener(self, callback: Callable[[str], None]) -> None:
        self._open_test_page_callback = callback

    def attach_tile(self, tile) -> None:
        tile.web_page_ready.connect(lambda page, tile=tile: self._bind_page(tile, page))
        tile.web_page_released.connect(lambda tile=tile: self._release_tile_page(tile))

    def _bind_page(self, tile, page) -> None:
        page_key = id(page)
        if self._page_tiles.get(page_key) is tile:
            return
        self._release_tile_page(tile)
        self._tile_pages[tile.tile_id] = page
        self._page_tiles[page_key] = tile
        page.loadStarted.connect(lambda tile=tile: self._reset_temporary_permissions_for_tile(tile))
        page.permissionRequested.connect(
            lambda permission, tile=tile, page=page: self._handle_permission_requested(
                tile,
                page,
                permission,
            )
        )

    def _release_tile_page(self, tile) -> None:
        page = self._tile_pages.pop(tile.tile_id, None)
        if page is not None:
            self._page_tiles.pop(id(page), None)
        self._reset_temporary_permissions_for_tile(tile)

    def _reset_runtime_permissions_for_origin(self, origin_key: str) -> None:
        if not origin_key:
            return
        for permission_type in (
            QWebEnginePermission.PermissionType.MediaAudioCapture,
            QWebEnginePermission.PermissionType.MediaVideoCapture,
            QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
        ):
            permission = self.profile.queryPermission(QUrl(origin_key), permission_type)
            if permission.isValid():
                permission.reset()

    def _reset_temporary_permissions_for_tile(self, tile) -> None:
        grants = self._temporary_grants.pop(tile.tile_id, [])
        for permission in grants:
            if permission.isValid():
                permission.reset()

    def _track_temporary_grant(
        self,
        tile_id: int,
        permission: QWebEnginePermission,
    ) -> None:
        grants = self._temporary_grants.setdefault(tile_id, [])
        grants.append(permission)

    def _clear_profile_media_permissions(self) -> None:
        for permission in self.profile.listAllPermissions():
            if permission.permissionType() not in {
                QWebEnginePermission.PermissionType.MediaAudioCapture,
                QWebEnginePermission.PermissionType.MediaVideoCapture,
                QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
            }:
                continue
            permission.reset()

    def _handle_permission_requested(self, tile, page, permission: QWebEnginePermission) -> None:
        if page is not self._tile_pages.get(tile.tile_id):
            permission.deny()
            return

        resources = _permission_type_resources(permission.permissionType())
        if not resources:
            permission.deny()
            return

        origin_key = _origin_to_key(permission.origin())
        if not origin_key:
            permission.deny()
            tile.show_media_message("Accès média refusé : origine invalide.")
            return

        if not tile.isVisible():
            permission.deny()
            tile.show_media_message(
                "Accès média refusé : la page n’est pas visible au moment de la demande."
            )
            return

        decisions = [self.store.decision_for(origin_key, resource) for resource in resources]
        if decisions and all(decision == MEDIA_PERMISSION_ALLOW for decision in decisions):
            permission.grant()
            return

        if any(decision == MEDIA_PERMISSION_DENY for decision in decisions):
            permission.deny()
            tile.show_media_message(
                "Accès média refusé par la règle enregistrée pour ce site."
            )
            return

        result = MediaPermissionRequestDialog.request_decision(
            origin_key=origin_key,
            full_url=tile.current_page_url(),
            tile_id=tile.tile_id,
            resources=resources,
            parent=self.parent(),
        )

        if result.action == MediaPermissionRequestDialog.ACTION_ALLOW_ALWAYS:
            self.store.set_many(
                origin_key,
                {resource: MEDIA_PERMISSION_ALLOW for resource in resources},
            )
            self.permissions_changed.emit()
            permission.grant()
            return

        if result.action == MediaPermissionRequestDialog.ACTION_ALLOW_ONCE:
            self._track_temporary_grant(tile.tile_id, permission)
            permission.grant()
            return

        if result.action == MediaPermissionRequestDialog.ACTION_DENY_ALWAYS:
            self.store.set_many(
                origin_key,
                {resource: MEDIA_PERMISSION_DENY for resource in resources},
            )
            self.permissions_changed.emit()
            permission.deny()
            tile.show_media_message(
                "Accès média refusé et mémorisé pour ce site."
            )
            return

        permission.deny()
        tile.show_media_message("Accès média refusé pour cette demande.")

    def open_permissions_panel(self) -> None:
        dialog = MediaPermissionsPanelDialog(self, parent=self.parent())
        dialog.exec()

    def open_test_page(self, host: str = "127.0.0.1") -> None:
        if self._open_test_page_callback is None:
            return
        self._open_test_page_callback(self.test_server.url(host))

    def list_permissions(self) -> list[tuple[str, dict[str, str]]]:
        return self.store.items()

    def set_permission(self, origin: str, resource: str, decision: str) -> None:
        self.store.set_decision(origin, resource, decision)
        self._reset_runtime_permissions_for_origin(origin)
        self.permissions_changed.emit()

    def reset_origin_to_ask(self, origin: str) -> None:
        self.store.reset_origin_to_ask(origin)
        self._reset_runtime_permissions_for_origin(origin)
        self.permissions_changed.emit()

    def delete_origin(self, origin: str) -> None:
        self.store.delete_origin(origin)
        self._reset_runtime_permissions_for_origin(origin)
        self.permissions_changed.emit()

    def reset_all_permissions(self) -> None:
        self.store.reset_all()
        self._clear_profile_media_permissions()
        self._temporary_grants.clear()
        self.permissions_changed.emit()

    def permissions_file_path(self) -> Path:
        return self.store.path

    def shutdown(self) -> None:
        for tile in list(self._page_tiles.values()):
            try:
                tile.reset_to_empty()
            except RuntimeError:
                continue
        self._temporary_grants.clear()
        self._tile_pages.clear()
        self._page_tiles.clear()
        self._open_test_page_callback = None
        self.test_server.stop()

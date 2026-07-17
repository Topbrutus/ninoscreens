from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.arena_controller import ArenaController


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


def _set_label_text(label: QLabel, value: Any, default: str = "non mesuré") -> None:
    text = default if value in {None, ""} else str(value)
    label.setText(text)


class ArenaWorkspace(QFrame):
    back_requested = Signal()

    def __init__(self, controller: ArenaController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("ControlPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_column = QVBoxLayout()
        self.title_label = QLabel("ARÈNE")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 800;")
        self.subtitle_label = QLabel("Plan de contrôle Antmux pour Reine-Linuxia et les Journaliers.")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setObjectName("MutedText")
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.subtitle_label)

        self.state_badge = QLabel("ARENA_OFFLINE")
        self.state_badge.setProperty("role", "statusBadge")
        self.state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_badge.setMinimumWidth(140)

        self.refresh_button = QPushButton("Rafraîchir")
        self.refresh_button.setProperty("compact", True)

        self.back_button = QPushButton("Retour à la grille")
        self.back_button.setProperty("compact", True)
        self.back_button.clicked.connect(self.back_requested.emit)

        header.addLayout(title_column, 1)
        header.addWidget(self.state_badge)
        header.addWidget(self.refresh_button)
        header.addWidget(self.back_button)

        root.addLayout(header)

        body = QGridLayout()
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(12)
        root.addLayout(body, 1)

        self.command_card, self.command_layout = _build_card("COMMANDEMENT")
        self.reine_state_value = QLabel("non mesuré")
        self.reine_pid_shell_value = QLabel("non mesuré")
        self.reine_pid_codex_value = QLabel("non mesuré")
        self.reine_session_value = QLabel("non mesuré")
        self.reine_model_value = QLabel("non mesuré")
        self.reine_reasoning_value = QLabel("non mesuré")
        self.reine_workspace_value = QLabel("non mesuré")
        self.reine_account_value = QLabel("non mesuré")
        self.reine_started_value = QLabel("non mesuré")
        self.reine_activity_value = QLabel("non mesuré")
        self.reine_stop_hook_value = QLabel("non mesuré")
        self.reine_summary_value = QLabel("non mesuré")
        self.reine_block_value = QLabel("non mesuré")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(6)
        for label, value in (
            ("Etat", self.reine_state_value),
            ("PID Terminal", self.reine_pid_shell_value),
            ("PID Codex", self.reine_pid_codex_value),
            ("session_id", self.reine_session_value),
            ("model", self.reine_model_value),
            ("reasoning", self.reine_reasoning_value),
            ("workspace", self.reine_workspace_value),
            ("compte logique", self.reine_account_value),
            ("heure de démarrage", self.reine_started_value),
            ("derniere activite", self.reine_activity_value),
            ("Stop hook charge", self.reine_stop_hook_value),
            ("dernier resume", self.reine_summary_value),
            ("dernier blocage", self.reine_block_value),
        ):
            form.addRow(label, value)

        self.reine_start_button = QPushButton("START REINE")
        self.reine_start_button.setProperty("role", "accent")
        self.reine_focus_button = QPushButton("FOCUS REINE")
        self.reine_restart_button = QPushButton("RESTART REINE")
        self.reine_restart_button.setProperty("role", "accent")
        self.reine_stop_button = QPushButton("STOP REINE")
        self.reine_stop_button.setProperty("role", "danger")
        self.reine_view_log_button = QPushButton("VIEW LOG")
        self.reine_copy_session_button = QPushButton("COPY SESSION ID")

        command_buttons = QHBoxLayout()
        for button in (
            self.reine_start_button,
            self.reine_focus_button,
            self.reine_restart_button,
            self.reine_stop_button,
            self.reine_view_log_button,
            self.reine_copy_session_button,
        ):
            command_buttons.addWidget(button)
        command_buttons.addStretch(1)

        self.command_layout.addLayout(form)
        self.command_layout.addLayout(command_buttons)

        self.worker_card, self.worker_layout = _build_card("JOURNALIERS")
        self.worker_table = QTableWidget(0, 11)
        self.worker_table.setHorizontalHeaderLabels(
            ["Nom", "Statut", "Modele", "Reasoning", "PID", "Job", "Workspace", "Lease", "Progression", "Confiance", "Derniere activite"]
        )
        self.worker_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.worker_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.worker_table.verticalHeader().setVisible(False)
        self.worker_table.setAlternatingRowColors(True)
        self.worker_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        worker_buttons = QHBoxLayout()
        self.worker_start_selected_button = QPushButton("START SELECTED")
        self.worker_stop_selected_button = QPushButton("STOP SELECTED")
        self.worker_start_available_button = QPushButton("START AVAILABLE")
        self.worker_pause_button = QPushButton("PAUSE DISPATCH")
        self.worker_resume_button = QPushButton("RESUME DISPATCH")
        self.worker_view_report_button = QPushButton("VIEW REPORT")
        self.worker_release_lease_button = QPushButton("RELEASE LEASE")
        for button in (
            self.worker_start_selected_button,
            self.worker_stop_selected_button,
            self.worker_start_available_button,
            self.worker_pause_button,
            self.worker_resume_button,
            self.worker_view_report_button,
            self.worker_release_lease_button,
        ):
            worker_buttons.addWidget(button)
        worker_buttons.addStretch(1)

        self.worker_layout.addWidget(self.worker_table, 1)
        self.worker_layout.addLayout(worker_buttons)

        self.job_card, self.job_layout = _build_card("FILE DES JOBS")
        self.job_table = QTableWidget(0, 8)
        self.job_table.setHorizontalHeaderLabels(
            ["Ordre", "Job ID", "Sous-job", "Proprietaire", "Worker", "Priorite", "Dependances", "Statut"]
        )
        self.job_table.verticalHeader().setVisible(False)
        self.job_table.setAlternatingRowColors(True)
        self.job_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.job_layout.addWidget(self.job_table, 1)

        self.health_card, self.health_layout = _build_card("SANTE")
        self.health_form = QFormLayout()
        self.health_form.setVerticalSpacing(6)
        self.core_value = QLabel("non mesure")
        self.jules_value = QLabel("non mesure")
        self.bridge_value = QLabel("non mesure")
        self.workerdock_value = QLabel("non mesure")
        self.nino_value = QLabel("non mesure")
        self.websocket_value = QLabel("non mesure")
        self.workers_active_value = QLabel("non mesure")
        self.cpu_value = QLabel("non mesure")
        self.ram_value = QLabel("non mesure")
        self.errors_value = QLabel("aucune")
        self.locks_value = QLabel("aucun")
        self.heartbeats_value = QLabel("aucun")
        for label, value in (
            ("Antmux Core", self.core_value),
            ("Jules", self.jules_value),
            ("Bridge", self.bridge_value),
            ("WorkerDock", self.workerdock_value),
            ("Nino", self.nino_value),
            ("Terminal WebSocket", self.websocket_value),
            ("workers actifs", self.workers_active_value),
            ("CPU", self.cpu_value),
            ("RAM", self.ram_value),
            ("erreurs", self.errors_value),
            ("verrous", self.locks_value),
            ("heartbeats", self.heartbeats_value),
        ):
            self.health_form.addRow(label, value)
        self.health_layout.addLayout(self.health_form)

        self.d_only_card, self.d_only_layout = _build_card("D-ONLY COMPLIANCE")
        self.d_only_form = QFormLayout()
        self.d_only_form.setVerticalSpacing(6)
        self.d_only_status_value = QLabel("unknown")
        self.d_only_components_value = QLabel("0")
        self.d_only_paths_value = QLabel("0")
        self.d_only_tools_value = QLabel("0")
        self.d_only_profiles_value = QLabel("0")
        self.d_only_caches_value = QLabel("0")
        self.d_only_temp_value = QLabel("0")
        self.d_only_checked_value = QLabel("non mesure")
        self.d_only_refusal_value = QLabel("aucun")
        self.d_only_codex_value = QLabel("non mesure")
        for label, value in (
            ("etat global", self.d_only_status_value),
            ("composants non conformes", self.d_only_components_value),
            ("chemins non conformes", self.d_only_paths_value),
            ("outils sur D", self.d_only_tools_value),
            ("profils sur D", self.d_only_profiles_value),
            ("caches sur D", self.d_only_caches_value),
            ("temp sur D", self.d_only_temp_value),
            ("derniere verification", self.d_only_checked_value),
            ("dernier chemin refuse", self.d_only_refusal_value),
            ("codex", self.d_only_codex_value),
        ):
            self.d_only_form.addRow(label, value)

        d_only_buttons = QHBoxLayout()
        self.d_only_run_audit_button = QPushButton("RUN AUDIT")
        self.d_only_view_violations_button = QPushButton("VIEW VIOLATIONS")
        self.d_only_prepare_migration_button = QPushButton("PREPARE MIGRATION")
        self.d_only_test_launch_button = QPushButton("TEST LAUNCH")
        self.d_only_export_report_button = QPushButton("EXPORT REPORT")
        for button in (
            self.d_only_run_audit_button,
            self.d_only_view_violations_button,
            self.d_only_prepare_migration_button,
            self.d_only_test_launch_button,
            self.d_only_export_report_button,
        ):
            d_only_buttons.addWidget(button)
        d_only_buttons.addStretch(1)

        self.d_only_layout.addLayout(self.d_only_form)
        self.d_only_layout.addLayout(d_only_buttons)

        self.event_feed = QTextEdit()
        self.event_feed.setReadOnly(True)
        self.event_feed.setPlaceholderText("Preuves et journal Arena.")
        self.event_feed.setMinimumHeight(180)

        body.addWidget(self.command_card, 0, 0)
        body.addWidget(self.worker_card, 0, 1)
        body.addWidget(self.job_card, 1, 0)
        body.addWidget(self.health_card, 1, 1)
        body.addWidget(self.d_only_card, 2, 0, 1, 2)

        root.addWidget(self.event_feed)

        self.refresh_button.clicked.connect(self.refresh_view)
        self.reine_start_button.clicked.connect(self._start_reine)
        self.reine_focus_button.clicked.connect(self._focus_reine)
        self.reine_restart_button.clicked.connect(self._restart_reine)
        self.reine_stop_button.clicked.connect(self._stop_reine)
        self.reine_view_log_button.clicked.connect(self._view_log)
        self.reine_copy_session_button.clicked.connect(self._copy_session_id)
        self.worker_start_selected_button.clicked.connect(self._start_selected_workers)
        self.worker_stop_selected_button.clicked.connect(self._stop_selected_workers)
        self.worker_start_available_button.clicked.connect(self._start_available_workers)
        self.worker_pause_button.clicked.connect(self._pause_dispatch)
        self.worker_resume_button.clicked.connect(self._resume_dispatch)
        self.worker_view_report_button.clicked.connect(self._view_report)
        self.worker_release_lease_button.clicked.connect(self._release_lease)
        self.d_only_run_audit_button.clicked.connect(self._run_d_only_audit)
        self.d_only_view_violations_button.clicked.connect(self._view_d_only_violations)
        self.d_only_prepare_migration_button.clicked.connect(self._prepare_d_only_migration)
        self.d_only_test_launch_button.clicked.connect(self._test_d_only_launch)
        self.d_only_export_report_button.clicked.connect(self._export_d_only_report)

        self.refresh_view()

    def activate(self) -> bool:
        self.refresh_view()
        return True

    def refresh_view(self) -> None:
        snapshot = self.controller.snapshot()
        self._apply_snapshot(snapshot)

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.state_badge.setText(str(snapshot.get("arena_state", "ARENA_OFFLINE")))
        self.state_badge.setProperty("arenaState", str(snapshot.get("arena_state", "ARENA_OFFLINE")))
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)

        reine = snapshot.get("reine", {})
        self.subtitle_label.setText(
            f"Reine {reine.get('status', 'OFFLINE')} | {snapshot.get('workers_active', 0)} worker(s) actifs | logs: {snapshot.get('log_path')}"
        )
        _set_label_text(self.reine_state_value, reine.get("status"))
        _set_label_text(self.reine_pid_shell_value, reine.get("pid_shell"))
        _set_label_text(self.reine_pid_codex_value, reine.get("pid_codex"))
        _set_label_text(self.reine_session_value, reine.get("session_id"))
        _set_label_text(self.reine_model_value, reine.get("model"))
        _set_label_text(self.reine_reasoning_value, reine.get("reasoning"))
        _set_label_text(self.reine_workspace_value, reine.get("workspace"))
        _set_label_text(self.reine_account_value, reine.get("account_alias"))
        _set_label_text(self.reine_started_value, reine.get("started_at"))
        _set_label_text(self.reine_activity_value, reine.get("last_activity"))
        _set_label_text(self.reine_stop_hook_value, reine.get("stop_hook_loaded", "non mesure"))
        _set_label_text(self.reine_summary_value, reine.get("last_summary"))
        _set_label_text(self.reine_block_value, reine.get("last_block"))

        self._populate_workers(snapshot.get("workers", []))
        self._populate_jobs(snapshot.get("jobs", []))
        self._populate_health(snapshot)
        self._populate_d_only(snapshot.get("d_only", {}))
        self._populate_events()

    def _populate_workers(self, workers: list[dict[str, Any]]) -> None:
        self.worker_table.setRowCount(len(workers))
        for row, worker in enumerate(workers):
            values = [
                worker.get("display_name"),
                worker.get("status"),
                worker.get("model"),
                worker.get("reasoning"),
                worker.get("pid_codex"),
                worker.get("job_id"),
                worker.get("workspace"),
                worker.get("lease_id"),
                worker.get("progress"),
                worker.get("confidence"),
                worker.get("last_activity"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem("" if value in {None, ""} else str(value))
                self.worker_table.setItem(row, column, item)

    def _populate_jobs(self, jobs: list[dict[str, Any]]) -> None:
        rows = jobs or [
            {
                "order": "1",
                "job_id": "none",
                "subjob_id": "none",
                "owner": "n/a",
                "worker": "n/a",
                "priority": "n/a",
                "dependencies": "none",
                "status": "empty",
            }
        ]
        self.job_table.setRowCount(len(rows))
        for row, job in enumerate(rows):
            values = [
                job.get("order") or "1",
                job.get("job_id"),
                job.get("subjob_id"),
                job.get("owner"),
                job.get("worker"),
                job.get("priority"),
                job.get("dependencies"),
                job.get("status"),
            ]
            for column, value in enumerate(values):
                self.job_table.setItem(row, column, QTableWidgetItem("" if value in {None, ""} else str(value)))

    def _populate_health(self, snapshot: dict[str, Any]) -> None:
        core = snapshot.get("core", {})
        jules = core.get("jules", {})
        bridge = core.get("bridge", {})
        _set_label_text(self.core_value, f"{core.get('status', 'UNKNOWN')} | PID {core.get('pid') or 'n/a'}")
        _set_label_text(self.jules_value, f"{jules.get('status', 'UNKNOWN')} | PID {jules.get('pid') or 'n/a'}")
        _set_label_text(self.bridge_value, f"{bridge.get('status', 'UNKNOWN')} | PID {bridge.get('pid') or 'n/a'}")
        _set_label_text(self.workerdock_value, f"{snapshot.get('workers_active', 0)}/{snapshot.get('max_running_workers', 0)} running")
        _set_label_text(self.nino_value, "ACTIVE" if snapshot.get("nino_active") else "INACTIVE")
        _set_label_text(self.websocket_value, "non mesure")
        _set_label_text(self.workers_active_value, snapshot.get("workers_active"))
        health = snapshot.get("health", {})
        _set_label_text(self.cpu_value, f"{health.get('cpu_percent', 'n/a')}%")
        _set_label_text(self.ram_value, f"{health.get('ram_percent', 'n/a')}%")
        _set_label_text(self.errors_value, ", ".join(map(str, health.get("errors", []))) or "aucune")
        _set_label_text(self.locks_value, ", ".join(map(str, health.get("locks", []))) or "aucun")
        _set_label_text(self.heartbeats_value, ", ".join(map(str, health.get("heartbeats", []))) or "aucun")

    def _populate_d_only(self, d_only: dict[str, Any]) -> None:
        _set_label_text(self.d_only_status_value, d_only.get("status"))
        _set_label_text(self.d_only_components_value, d_only.get("non_compliant_components", d_only.get("violation_count")))
        _set_label_text(self.d_only_paths_value, d_only.get("non_compliant_paths", d_only.get("violation_count")))
        _set_label_text(self.d_only_tools_value, d_only.get("tools_on_d"))
        _set_label_text(self.d_only_profiles_value, d_only.get("profiles_on_d"))
        _set_label_text(self.d_only_caches_value, d_only.get("caches_on_d"))
        _set_label_text(self.d_only_temp_value, d_only.get("temp_on_d"))
        _set_label_text(self.d_only_checked_value, d_only.get("last_checked"))
        _set_label_text(self.d_only_refusal_value, d_only.get("last_refusal"))
        _set_label_text(self.d_only_codex_value, d_only.get("codex_command"))

    def _populate_events(self) -> None:
        events = self.controller.store.tail_events(16)
        lines = []
        for event in events:
            stamp = str(event.get("timestamp", "")).replace("T", " ")
            lines.append(f"[{stamp}] {event.get('event')} {event.get('payload')}")
        self.event_feed.setPlainText("\n".join(lines))

    def _selected_worker_ids(self) -> list[str]:
        ids = []
        for row in {index.row() for index in self.worker_table.selectionModel().selectedRows()}:
            item = self.worker_table.item(row, 0)
            if item is not None and item.text().strip():
                label = item.text().strip()
                for worker in self.controller.store.load_registry().get("workers", []):
                    if worker.get("display_name") == label:
                        ids.append(str(worker.get("instance_id")))
                        break
        return ids

    def _start_reine(self) -> None:
        result = self.controller.plan_reine_start()
        self._append_action_result("START REINE", result)
        self.refresh_view()

    def _focus_reine(self) -> None:
        result = self.controller.focus_reine()
        self._append_action_result("FOCUS REINE", result)
        self.refresh_view()

    def _restart_reine(self) -> None:
        result = self.controller.restart_reine()
        self._append_action_result("RESTART REINE", result)
        self.refresh_view()

    def _stop_reine(self) -> None:
        result = QMessageBox.question(
            self,
            "Stop Reine",
            "Confirmer l'arret de Reine-Linuxia ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        outcome = self.controller.stop_reine(True)
        self._append_action_result("STOP REINE", outcome)
        self.refresh_view()

    def _view_log(self) -> None:
        self.controller.store.append_event("VIEW_LOG", {"path": self.controller.store.paths.events_path.as_posix()})
        self.refresh_view()

    def _copy_session_id(self) -> None:
        session_id = self.controller.snapshot().get("reine", {}).get("session_id")
        if not session_id:
            return
        QGuiApplication.clipboard().setText(str(session_id))
        self.controller.store.append_event("COPY_SESSION_ID", {"session_id": session_id})
        self.refresh_view()

    def _start_selected_workers(self) -> None:
        ids = self._selected_worker_ids()
        for instance_id in ids:
            self._append_action_result("START SELECTED", self.controller.start_worker(instance_id))
        self.refresh_view()

    def _stop_selected_workers(self) -> None:
        result = QMessageBox.question(
            self,
            "Stop workers",
            "Confirmer l'arret des journaliers selectionnes ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        registry = self.controller.store.load_registry()
        for instance_id in self._selected_worker_ids():
            for worker in registry["workers"]:
                if worker["instance_id"] == instance_id:
                    worker["status"] = "OFFLINE"
                    worker["pid_shell"] = None
                    worker["pid_codex"] = None
                    worker["job_id"] = None
                    worker["lease_id"] = None
        self.controller.store.save_registry(registry)
        self.controller.store.append_event("STOP_SELECTED", {"count": len(self._selected_worker_ids())})
        self.refresh_view()

    def _start_available_workers(self) -> None:
        self._append_action_result("START AVAILABLE", self.controller.start_available_workers())
        self.refresh_view()

    def _pause_dispatch(self) -> None:
        self._append_action_result("PAUSE DISPATCH", self.controller.pause_dispatch())
        self.refresh_view()

    def _resume_dispatch(self) -> None:
        self._append_action_result("RESUME DISPATCH", self.controller.resume_dispatch())
        self.refresh_view()

    def _view_report(self) -> None:
        self.controller.store.append_event("VIEW_REPORT", {"message": "Report viewed"})
        self.refresh_view()

    def _release_lease(self) -> None:
        registry = self.controller.store.load_registry()
        for worker in registry["workers"]:
            if worker.get("status") == "RESERVED":
                worker["status"] = "AVAILABLE"
                worker["lease_id"] = None
        self.controller.store.save_registry(registry)
        self.controller.store.append_event("RELEASE_LEASE", {"message": "lease released"})
        self.refresh_view()

    def _append_action_result(self, action: str, result: dict[str, Any]) -> None:
        self.event_feed.append(f"{action}: {result}")

    def _run_d_only_audit(self) -> None:
        snapshot = self.controller.snapshot()
        self.controller.store.append_event("RUN_AUDIT", {"status": snapshot.get("d_only", {}).get("status")})
        self.refresh_view()

    def _view_d_only_violations(self) -> None:
        d_only = self.controller.snapshot().get("d_only", {})
        self.controller.store.append_event("VIEW_VIOLATIONS", {"count": d_only.get("non_compliant_paths", d_only.get("violation_count", 0))})
        self.refresh_view()

    def _prepare_d_only_migration(self) -> None:
        d_only = self.controller.snapshot().get("d_only", {})
        self.controller.store.append_event("PREPARE_MIGRATION", {"status": d_only.get("status"), "last_refusal": d_only.get("last_refusal")})
        self.refresh_view()

    def _test_d_only_launch(self) -> None:
        d_only = self.controller.snapshot().get("d_only", {})
        self.controller.store.append_event("TEST_LAUNCH", {"codex": d_only.get("codex_command")})
        self.refresh_view()

    def _export_d_only_report(self) -> None:
        d_only = self.controller.snapshot().get("d_only", {})
        self.controller.store.append_event("EXPORT_REPORT", {"status": d_only.get("status"), "components": d_only.get("non_compliant_components", d_only.get("violation_count", 0)), "paths": d_only.get("non_compliant_paths", d_only.get("violation_count", 0))})
        self.refresh_view()

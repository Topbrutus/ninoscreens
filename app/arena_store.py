from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_ARENA_ROOT = Path(r"D:\modules\arena")
DEFAULT_DEMARAGE_ROOT = Path(r"D:\demarage")
DEFAULT_WORKER_COUNT = 10


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class ArenaPaths:
    root: Path
    config_path: Path
    registry_path: Path
    log_path: Path
    events_path: Path


class ArenaStore:
    def __init__(self, root: Path | None = None) -> None:
        arena_root = Path(root or os.environ.get("ANTMUX_ARENA_ROOT") or DEFAULT_ARENA_ROOT)
        self.paths = ArenaPaths(
            root=arena_root,
            config_path=arena_root / "config" / "arena.json",
            registry_path=arena_root / "runtime" / "instances.json",
            log_path=DEFAULT_DEMARAGE_ROOT / "logs" / "arena.log",
            events_path=DEFAULT_DEMARAGE_ROOT / "logs" / "arena-events.jsonl",
        )

    def ensure_initialized(self) -> dict[str, Any]:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.events_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_default_config()

        registry = _read_json(self.paths.registry_path)
        if registry is None:
            registry = self._default_registry()
            _atomic_write_json(self.paths.registry_path, registry)
        return registry

    def load_config(self) -> dict[str, Any]:
        config = _read_json(self.paths.config_path)
        if config is None:
            return self._default_config()
        return config

    def load_registry(self) -> dict[str, Any]:
        return self.ensure_initialized()

    def save_registry(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["last_updated_at"] = _utc_now()
        _atomic_write_json(self.paths.registry_path, payload)

    def append_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        payload = dict(payload or {})
        record = {
            "timestamp": _utc_now(),
            "event": event,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        self.paths.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        self.paths.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{record['timestamp']} | {event} | {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n")

    def tail_events(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.paths.events_path.exists():
            return []
        lines = self.paths.events_path.read_text(encoding="utf-8").splitlines()
        items: list[dict[str, Any]] = []
        for line in lines[-max(1, limit):]:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                items.append(parsed)
        return items

    def _ensure_default_config(self) -> None:
        if self.paths.config_path.exists():
            return
        _atomic_write_json(self.paths.config_path, self._default_config())

    def _default_config(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "arena_name": "Antmux Arena",
            "enabled": True,
            "core_mode": "reuse-existing",
            "reine": {
                "instance_id": "REINE-LINUXIA-01",
                "display_name": "Reine-Linuxia",
                "session_id": "REINE-LINUXIA-01",
                "role": "primary-interactive-worker",
                "workspace": "D:\\",
                "launch_mode": "nino-terminal-attached",
                "model": "gpt-5.4-mini",
                "reasoning": "extra_high",
                "account_alias": "primary-openai-account",
                "codex_command_path": "D:\\tools\\node-global\\codex.cmd",
                "codex_command": "auto",
                "known_codex_paths": [],
            },
            "workerdock": {
                "enabled": True,
                "max_registered_workers": 10,
                "max_running_workers": 2,
                "worker_launch_mode": "detached",
                "model": "gpt-5.4-mini",
                "reasoning": "low",
            },
        }

    def _default_registry(self) -> dict[str, Any]:
        config = self.load_config()
        workers = []
        for index in range(1, DEFAULT_WORKER_COUNT + 1):
            suffix = f"{index:02d}"
            workers.append(
                {
                    "instance_id": f"JOURNALIER-{suffix}",
                    "display_name": f"Journalier {suffix}",
                    "type": "codex",
                    "role": "journalier",
                    "launch_mode": config["workerdock"]["worker_launch_mode"],
                    "pid_shell": None,
                    "pid_codex": None,
                    "session_id": f"SESSION-JOURNALIER-{suffix}",
                    "workspace": str(DEFAULT_ARENA_ROOT.parent / "workers" / f"JOURNALIER-{suffix}"),
                    "model": config["workerdock"]["model"],
                    "reasoning": config["workerdock"]["reasoning"],
                    "account_alias": f"antmux-worker-{suffix}",
                    "status": "OFFLINE",
                    "started_at": None,
                    "last_heartbeat": None,
                    "nino_terminal_id": None,
                    "worker_id": f"JOURNALIER-{suffix}",
                    "job_id": None,
                    "lease_id": None,
                    "last_activity": None,
                    "progress": 0,
                    "confidence": "LOW",
                    "detached": True,
                    "report_path": str(DEFAULT_DEMARAGE_ROOT / "logs" / f"arena-worker-{suffix}.md"),
                    "log_path": str(DEFAULT_DEMARAGE_ROOT / "logs" / f"arena-worker-{suffix}.log"),
                }
            )

        return {
            "schema_version": 1,
            "arena_name": config["arena_name"],
            "enabled": bool(config["enabled"]),
            "core_mode": config["core_mode"],
            "paused": False,
            "arena_state": "ARENA_READY",
            "reine": {
                "instance_id": config["reine"]["instance_id"],
                "display_name": config["reine"]["display_name"],
                "type": "codex",
                "role": config["reine"]["role"],
                "launch_mode": config["reine"]["launch_mode"],
                "pid_shell": None,
                "pid_codex": None,
                "session_id": config["reine"]["session_id"],
                "workspace": config["reine"]["workspace"],
                "model": config["reine"]["model"],
                "reasoning": config["reine"]["reasoning"],
                "account_alias": config["reine"]["account_alias"],
                "status": "OFFLINE",
                "started_at": None,
                "last_heartbeat": None,
                "nino_terminal_id": None,
                "worker_id": None,
                "job_id": None,
                "lease_id": None,
                "last_activity": None,
                "last_summary": None,
                "last_block": None,
                "last_command": None,
                "detached": False,
            },
            "workers": workers,
            "jobs": [],
            "leases": [],
            "core": {
                "status": "UNKNOWN",
                "cli": "SINGLETON_UNKNOWN",
                "pid": None,
                "parent_pid": None,
                "command_line": None,
                "workspace": "D:\\",
                "instance_id": "antmux-core",
                "mutex": "Global\\Antmux-Core",
                "jules": {"status": "UNKNOWN", "pid": None, "command_line": None},
                "bridge": {"status": "UNKNOWN", "pid": None, "command_line": None},
            },
            "health": {
                "cpu_percent": None,
                "ram_percent": None,
                "errors": [],
                "locks": [],
                "heartbeats": [],
                "measured": False,
            },
            "last_updated_at": _utc_now(),
            "nino_appdata_root": "D:\\runtime\\profiles\\nino\\appdata",
            "last_event": None,
        }

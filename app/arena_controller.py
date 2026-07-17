from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.arena_store import ArenaStore


def _safe_json_load(text: str) -> Any:
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _ps_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    return _safe_json_load(completed.stdout)


def _first_process(pattern: str) -> dict[str, Any] | None:
    script = f"""
$item = Get-CimInstance Win32_Process | Where-Object {{
    $_.CommandLine -match {json.dumps(pattern)}
}} | Select-Object -First 1 ProcessId,ParentProcessId,CommandLine,ExecutablePath,CreationDate
if ($null -ne $item) {{
    $item | ConvertTo-Json -Depth 4 -Compress
}}
"""
    result = _ps_json(script)
    return result if isinstance(result, dict) else None


def _system_metrics() -> dict[str, Any]:
    script = """
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$os = Get-CimInstance Win32_OperatingSystem
$ram = if ($os.TotalVisibleMemorySize) {
    [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
} else { $null }
[pscustomobject]@{ cpu_percent = $cpu; ram_percent = $ram } | ConvertTo-Json -Compress
"""
    result = _ps_json(script)
    if isinstance(result, dict):
        return result
    return {"cpu_percent": None, "ram_percent": None}


def _path_on_d(path: str | None) -> bool:
    if not path:
        return False
    try:
        return str(Path(path).resolve()).upper().startswith("D:\\")
    except OSError:
        return False


def _first_where_path(tool_name: str) -> str | None:
    completed = subprocess.run(
        ["where.exe", tool_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        hit = line.strip()
        if hit:
            return hit
    return None


class ArenaController:
    def __init__(self, store: ArenaStore | None = None) -> None:
        self.store = store or ArenaStore()
        self.store.ensure_initialized()

    def snapshot(self) -> dict[str, Any]:
        config = self.store.load_config()
        registry = self.store.load_registry()
        core = _first_process(r"D:\\antmux\.exe")
        jules = _first_process(r"jules-watch\.cmd|Watch-AntmuxSummaries\.ps1")
        bridge = _first_process(r"ChatGPT-Bridge|bridge")
        nino = _first_process(r"D:\\tools\\ninoscreens|NinoScreen\.cmd|main\.py")
        metrics = _system_metrics()

        core_status = registry.get("core", {})
        if core:
            core_status = {
                "status": "ACTIVE",
                "cli": "SINGLETON_ALREADY_RUNNING",
                "pid": core.get("ProcessId"),
                "parent_pid": core.get("ParentProcessId"),
                "command_line": core.get("CommandLine"),
                "workspace": "D:\\",
                "instance_id": "antmux-core",
                "mutex": "Global\\Antmux-Core",
                "jules": {
                    "status": "ACTIVE" if jules else "UNKNOWN",
                    "pid": None if not jules else jules.get("ProcessId"),
                    "command_line": None if not jules else jules.get("CommandLine"),
                },
                "bridge": {
                    "status": "ACTIVE" if bridge else "UNKNOWN",
                    "pid": None if not bridge else bridge.get("ProcessId"),
                    "command_line": None if not bridge else bridge.get("CommandLine"),
                },
            }
        else:
            core_status = dict(core_status)

        nino_active = bool(nino)
        arena_state = "ARENA_PAUSED" if registry.get("paused") else "ARENA_READY" if (core and nino_active and registry.get("enabled", True)) else "ARENA_DEGRADED" if core else "ARENA_OFFLINE"
        workers = list(registry.get("workers", []))
        running_workers = sum(1 for worker in workers if str(worker.get("status", "")).upper() in {"STARTING", "RESERVED", "RUNNING"})
        health = {
            "cpu_percent": metrics.get("cpu_percent"),
            "ram_percent": metrics.get("ram_percent"),
            "errors": [],
            "locks": [],
            "heartbeats": [worker.get("last_heartbeat") for worker in workers if worker.get("last_heartbeat")],
            "measured": metrics.get("cpu_percent") is not None or metrics.get("ram_percent") is not None,
        }
        d_only_paths = {
            "arena_root": str(self.store.paths.root),
            "arena_registry": str(self.store.paths.registry_path),
            "arena_log": str(self.store.paths.log_path),
            "arena_events": str(self.store.paths.events_path),
            "reine_workspace": str(registry.get("reine", {}).get("workspace", "")),
            "python_runtime": r"D:\tools\python\tools",
            "python_venv": r"D:\venvs\nino",
            "python_cache": r"D:\cache\python",
            "python_userbase": r"D:\runtime\python-userbase",
            "python_temp": r"D:\temp\python",
            "python_config": r"D:\config\pip\pip.ini",
            "profiles_root": r"D:\runtime\profiles",
            "cache_root": r"D:\cache",
            "temp_root": r"D:\temp",
            "nino_appdata_root": "D:\\runtime\\profiles\\nino\\appdata",
        }
        codex_path = None
        codex_violation = None
        try:
            codex_path = self.resolve_codex_command()
        except RuntimeError as exc:
            codex_violation = str(exc)

        violations = []
        for label, path in d_only_paths.items():
            if path and not _path_on_d(path):
                violations.append({"component": label, "path": path})

        if codex_path and not _path_on_d(codex_path):
            violations.append({"component": "codex", "path": codex_path})
        elif codex_violation:
            violations.append({"component": "codex", "path": codex_violation})

        env_violations = {}
        for name in ("APPDATA", "LOCALAPPDATA", "HOME", "TEMP", "TMP"):
            value = os.environ.get(name, "").strip()
            if value and value.upper().startswith("C:\\"):
                env_violations[name] = value
                violations.append({"component": f"env:{name}", "path": value})

        tool_paths: dict[str, str | None] = {}
        tools_on_d = 0
        for tool in ("codex.cmd", "node", "npm", "python", "pwsh", "git", "gh"):
            resolved = _first_where_path(tool)
            tool_paths[tool] = resolved
            if resolved and _path_on_d(resolved):
                tools_on_d += 1
            elif resolved:
                violations.append({"component": f"tool:{tool}", "path": resolved})

        d_only_status = "COMPLIANT"
        if violations:
            d_only_status = "BLOCKED" if codex_violation else "MIGRATION_REQUIRED"
        non_compliant_components = sorted({str(item["component"]).split(":", 1)[-1] for item in violations})
        return {
            "config": config,
            "registry": registry,
            "arena_state": arena_state,
            "core": core_status,
            "reine": registry.get("reine", {}),
            "workers": workers,
            "jobs": list(registry.get("jobs", [])),
            "leases": list(registry.get("leases", [])),
            "workers_active": running_workers,
            "max_running_workers": int(config["workerdock"]["max_running_workers"]),
            "health": health,
            "nino_active": nino_active,
            "nino_appdata_root": "D:\\runtime\\profiles\\nino\\appdata",
            "log_path": str(self.store.paths.log_path),
            "events_path": str(self.store.paths.events_path),
            "d_only": {
                "status": d_only_status,
                "violations": violations,
                "violation_count": len(violations),
                "non_compliant_components": len(non_compliant_components),
                "non_compliant_paths": len(violations),
                "components": non_compliant_components,
                "last_checked": datetime.utcnow().isoformat(),
                "last_refusal": violations[0]["path"] if violations else None,
                "codex_command": codex_path,
                "env_violations": env_violations,
                "tools_on_d": tools_on_d,
                "tool_paths": tool_paths,
                "profiles_on_d": 1 if _path_on_d(r"D:\runtime\profiles") else 0,
                "caches_on_d": 1 if _path_on_d(r"D:\cache") else 0,
                "temp_on_d": 1 if _path_on_d(r"D:\temp") else 0,
            },
        }

    def resolve_codex_command(self) -> str:
        config = self.store.load_config()
        explicit = str(config["reine"].get("codex_command_path", "")).strip()
        candidates: list[str] = []
        if explicit:
            candidates.append(explicit)
        candidates.extend([
            r"D:\tools\codex\codex.cmd",
            r"D:\tools\node-global\codex.cmd",
        ])
        where_hit = subprocess.run(
            ["where.exe", "codex.cmd"],
            capture_output=True,
            text=True,
            check=False,
        )
        if where_hit.returncode == 0:
            for line in where_hit.stdout.splitlines():
                hit = line.strip()
                if hit and hit.upper().startswith("D:\\"):
                    candidates.append(hit)
        candidates.extend(str(item) for item in config["reine"].get("known_codex_paths", []) if str(item).strip())

        for candidate in candidates:
            path = Path(candidate)
            if path.is_file() and path.suffix.lower() == ".cmd" and str(path.resolve()).upper().startswith("D:\\"):
                resolved = str(path.resolve())
                self.store.append_event("CODEX_COMMAND_RESOLVED", {"path": resolved})
                return resolved
        self.store.append_event("ERROR", {"cause": "CODEX_COMMAND_NOT_FOUND"})
        raise RuntimeError("STATUS: BLOCKED\nCAUSE: CODEX_COMMAND_NOT_FOUND")

    def plan_reine_start(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        if not snapshot["nino_active"]:
            return {
                "status": "BLOCKED",
                "cause": "NINO_NOT_ACTIVE",
                "instance_id": snapshot["reine"]["instance_id"],
                "display_name": snapshot["reine"]["display_name"],
                "workspace": snapshot["reine"]["workspace"],
            }

        codex_command = self.resolve_codex_command()
        command_line = f'Set-Location D:\\; & "{codex_command}"'
        self.store.append_event("REINE_START_REQUESTED", {"instance_id": snapshot["reine"]["instance_id"]})
        if str(snapshot["reine"].get("status", "")).upper() in {"STARTING", "RUNNING", "FOCUSED"}:
            return {
                "status": "ALREADY_RUNNING",
                "cause": "REINE_ALREADY_RUNNING",
                "instance_id": snapshot["reine"]["instance_id"],
                "display_name": snapshot["reine"]["display_name"],
                "workspace": snapshot["reine"]["workspace"],
                "session_id": snapshot["reine"].get("session_id"),
                "command_line": command_line,
                "codex_command": codex_command,
            }
        return {
            "status": "PLANNED",
            "cause": "TESTONLY",
            "instance_id": snapshot["reine"]["instance_id"],
            "display_name": snapshot["reine"]["display_name"],
            "workspace": snapshot["reine"]["workspace"],
            "session_id": snapshot["reine"].get("session_id"),
            "command_line": command_line,
            "codex_command": codex_command,
            "pid_shell": None,
            "pid_codex": None,
            "launch_mode": snapshot["reine"].get("launch_mode"),
        }

    def focus_reine(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        self.store.append_event("REINE_FOCUSED", {"instance_id": snapshot["reine"]["instance_id"]})
        return {"status": "FOCUSED", "instance_id": snapshot["reine"]["instance_id"]}

    def restart_reine(self, *, ambiguous: bool = False, detached_session: bool = False) -> dict[str, Any]:
        if ambiguous:
            self.store.append_event("ERROR", {"cause": "HUMAN_REVIEW_REQUIRED"})
            return {"status": "HUMAN_REVIEW_REQUIRED", "cause": "PROCESS_STATE_AMBIGUOUS"}
        if detached_session:
            self.store.append_event("REINE_DISCONNECTED", {"cause": "DETACHED_SESSION_FOUND"})
            return {"status": "DETACHED_SESSION_FOUND", "cause": "DETACHED_SESSION_FOUND"}
        return self.plan_reine_start()

    def stop_reine(self, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            return {"status": "BLOCKED", "cause": "CONFIRMATION_REQUIRED"}
        registry = self.store.load_registry()
        registry["reine"]["status"] = "OFFLINE"
        registry["reine"]["last_activity"] = datetime.utcnow().isoformat()
        self.store.save_registry(registry)
        self.store.append_event("REINE_STOPPED", {"instance_id": registry["reine"]["instance_id"]})
        return {"status": "STOPPED", "instance_id": registry["reine"]["instance_id"]}

    def start_worker(self, instance_id: str, *, max_running_workers: int | None = None) -> dict[str, Any]:
        registry = self.store.load_registry()
        config = self.store.load_config()
        snapshot = self.snapshot()
        worker = next((item for item in registry["workers"] if str(item.get("instance_id")) == instance_id), None)
        if worker is None:
            self.store.append_event("JOURNALIER_BLOCKED", {"instance_id": instance_id, "cause": "UNKNOWN_WORKER"})
            return {"status": "BLOCKED", "cause": "UNKNOWN_WORKER", "instance_id": instance_id}

        if registry.get("paused"):
            self.store.append_event("JOURNALIER_BLOCKED", {"instance_id": instance_id, "cause": "ARENA_PAUSED"})
            return {"status": "BLOCKED", "cause": "ARENA_PAUSED", "instance_id": instance_id}

        limit = int(max_running_workers or config["workerdock"]["max_running_workers"])
        running = sum(1 for item in registry["workers"] if str(item.get("status", "")).upper() in {"STARTING", "RESERVED", "RUNNING"})
        if running >= limit and str(worker.get("status", "")).upper() not in {"STARTING", "RESERVED", "RUNNING"}:
            self.store.append_event("WORKER_LIMIT_REACHED", {"instance_id": instance_id, "max_running_workers": limit})
            return {"status": "WORKER_LIMIT_REACHED", "instance_id": instance_id, "max_running_workers": limit}

        if not snapshot["core"]["pid"]:
            self.store.append_event("JOURNALIER_BLOCKED", {"instance_id": instance_id, "cause": "CORE_NOT_ACTIVE"})
            return {"status": "BLOCKED", "cause": "CORE_NOT_ACTIVE", "instance_id": instance_id}

        launcher = Path(r"D:\demarage\Start-AntmuxJournalier.ps1")
        plan = {
            "status": "PLANNED",
            "cause": "TESTONLY",
            "workerdock": "USED",
            "launcher": str(launcher),
            "instance_id": worker["instance_id"],
            "display_name": worker["display_name"],
            "workspace": worker["workspace"],
            "model": worker["model"],
            "reasoning": worker["reasoning"],
            "session_id": worker["session_id"],
            "launch_mode": worker["launch_mode"],
            "detached": bool(worker.get("detached", True)),
            "max_running_workers": limit,
            "running_workers": running,
            "workspace_ready": Path(worker["workspace"]).exists(),
        }
        self.store.append_event("JOURNALIER_START_REQUESTED", {"instance_id": instance_id, "test_only": True})
        return plan

    def start_available_workers(self, limit: int | None = None) -> dict[str, Any]:
        registry = self.store.load_registry()
        config = self.store.load_config()
        running_limit = int(limit or config["workerdock"]["max_running_workers"])
        results = []
        for worker in registry["workers"]:
            if len([item for item in results if item.get("status") in {"PLANNED", "RESERVED"}]) >= running_limit:
                results.append({"instance_id": worker["instance_id"], "status": "QUEUED"})
                continue
            if str(worker.get("status", "")).upper() == "OFFLINE":
                results.append({"instance_id": worker["instance_id"], "status": "PLANNED"})
                worker["status"] = "RESERVED"
            else:
                results.append({"instance_id": worker["instance_id"], "status": str(worker.get("status", "UNKNOWN"))})
        self.store.save_registry(registry)
        self.store.append_event("WORKER_LIMIT_REACHED" if len(results) > running_limit else "JOURNALIER_STARTED", {"limit": running_limit})
        return {"status": "OK", "results": results, "limit": running_limit}

    def pause_dispatch(self) -> dict[str, Any]:
        registry = self.store.load_registry()
        registry["paused"] = True
        registry["arena_state"] = "ARENA_PAUSED"
        self.store.save_registry(registry)
        self.store.append_event("EMERGENCY_PAUSE", {"arena_state": "ARENA_PAUSED"})
        return {"status": "ARENA_PAUSED"}

    def resume_dispatch(self) -> dict[str, Any]:
        registry = self.store.load_registry()
        registry["paused"] = False
        registry["arena_state"] = "ARENA_READY"
        self.store.save_registry(registry)
        self.store.append_event("RESUME_DISPATCH", {"arena_state": "ARENA_READY"})
        return {"status": "ARENA_READY"}

    def stop_all_journaliers(self, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            return {"status": "BLOCKED", "cause": "CONFIRMATION_REQUIRED"}
        registry = self.store.load_registry()
        for worker in registry["workers"]:
            worker["status"] = "OFFLINE"
            worker["pid_shell"] = None
            worker["pid_codex"] = None
            worker["job_id"] = None
            worker["lease_id"] = None
            worker["last_activity"] = datetime.utcnow().isoformat()
        self.store.save_registry(registry)
        self.store.append_event("STOP_ALL_JOURNALIERS", {"count": len(registry["workers"])})
        return {"status": "STOPPED", "count": len(registry["workers"])}

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from winpty import PtyProcess


TERMINAL_HOST = "127.0.0.1"
TERMINAL_PORT = int(os.environ.get("NINO_TERMINAL_PORT", "8765"))
TERMINAL_BUFFER_LIMIT = 500_000
TERMINAL_DEFAULT_COLS = 120
TERMINAL_DEFAULT_ROWS = 30
TERMINAL_READY_TIMEOUT_SECONDS = 8.0
TERMINAL_REQUEST_TIMEOUT_SECONDS = 8.0
TERMINAL_SHUTDOWN_TIMEOUT_SECONDS = 8.0
TERMINAL_TYPE = "powershell"


class TerminalRuntimeError(RuntimeError):
    pass


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _powershell_command() -> list[str]:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell_path = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return [str(powershell_path), "-NoLogo", "-NoProfile"]


class _TerminalSession:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        session_id: str,
        display_name: str,
        start_dir: Path,
    ) -> None:
        self.loop = loop
        self.session_id = session_id
        self.display_name = display_name
        self.start_dir = start_dir
        self.command = _powershell_command()
        self.terminal_type = TERMINAL_TYPE
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.process: PtyProcess | None = None
        self.clients: set[ServerConnection] = set()
        self.output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.buffer = ""
        self.buffer_lock = threading.Lock()
        self.reader_thread: threading.Thread | None = None
        self.pump_task: asyncio.Task[None] | None = None
        self.closed = False

    async def start(self) -> None:
        if self.process is not None:
            return

        self.process = PtyProcess.spawn(
            self.command,
            cwd=str(self.start_dir),
            dimensions=(TERMINAL_DEFAULT_ROWS, TERMINAL_DEFAULT_COLS),
        )
        self.pump_task = asyncio.create_task(
            self._pump_output(),
            name=f"nino-terminal-output-{self.session_id}",
        )
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"nino-terminal-reader-{self.session_id}",
            daemon=True,
        )
        self.reader_thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self.buffer_lock:
            buffer_size = len(self.buffer)
        process = self.process
        alive = bool(process and process.isalive())
        return {
            "session_id": self.session_id,
            "display_name": self.display_name,
            "pid": getattr(process, "pid", None),
            "cwd": str(self.start_dir),
            "command": list(self.command),
            "host": TERMINAL_HOST,
            "port": TERMINAL_PORT,
            "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
            "manual_mode": True,
            "terminal_type": self.terminal_type,
            "created_at": self.created_at,
            "alive": alive,
            "state": "running" if alive else "stopped",
            "client_count": len(self.clients),
            "buffer_size": buffer_size,
        }

    def attach_client(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)

    def detach_client(self, websocket: ServerConnection) -> None:
        self.clients.discard(websocket)

    def _reader_loop(self) -> None:
        if self.process is None:
            return

        try:
            while not self.closed and self.process.isalive():
                try:
                    chunk = self.process.read(1024)
                except EOFError:
                    break
                except Exception as exc:  # pragma: no cover - defensive path
                    chunk = f"\r\n[terminal] read error: {exc}\r\n"
                    self.loop.call_soon_threadsafe(self.output_queue.put_nowait, chunk)
                    break
                if chunk:
                    self.loop.call_soon_threadsafe(self.output_queue.put_nowait, chunk)
        finally:
            self.loop.call_soon_threadsafe(self.output_queue.put_nowait, None)

    async def _pump_output(self) -> None:
        while True:
            chunk = await self.output_queue.get()
            if chunk is None:
                await self._broadcast({"type": "meta", **self.snapshot()})
                return
            self._append_to_buffer(chunk)
            await self._broadcast(
                {
                    "type": "output",
                    "session_id": self.session_id,
                    "data": chunk,
                }
            )

    def _append_to_buffer(self, chunk: str) -> None:
        with self.buffer_lock:
            self.buffer += chunk
            if len(self.buffer) > TERMINAL_BUFFER_LIMIT:
                self.buffer = self.buffer[-TERMINAL_BUFFER_LIMIT:]

    def buffer_copy(self) -> str:
        with self.buffer_lock:
            return self.buffer

    async def send_snapshot(self, websocket: ServerConnection) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "snapshot",
                    "session_id": self.session_id,
                    "data": self.buffer_copy(),
                }
            )
        )
        await websocket.send(json.dumps({"type": "meta", **self.snapshot()}))

    async def handle_client_message(self, websocket: ServerConnection, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None:
            return

        message_type = str(payload.get("type", "")).strip().lower()
        if message_type == "input":
            data = str(payload.get("data", ""))
            if data:
                process.write(data)
        elif message_type == "resize":
            rows = int(payload.get("rows", TERMINAL_DEFAULT_ROWS))
            cols = int(payload.get("cols", TERMINAL_DEFAULT_COLS))
            rows = max(10, min(200, rows))
            cols = max(20, min(320, cols))
            process.setwinsize(rows, cols)
        elif message_type == "interrupt":
            process.sendintr()
        elif message_type == "ping":
            await websocket.send(
                json.dumps(
                    {
                        "type": "pong",
                        "session_id": self.session_id,
                    }
                )
            )

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return
        data = json.dumps(payload)
        stale: list[ServerConnection] = []
        for websocket in list(self.clients):
            try:
                await websocket.send(data)
            except ConnectionClosed:
                stale.append(websocket)
        for websocket in stale:
            self.clients.discard(websocket)

    async def shutdown(self, notify_clients: bool = True) -> None:
        self.closed = True

        if notify_clients:
            await self._broadcast(
                {
                    "type": "session_closed",
                    "session_id": self.session_id,
                }
            )

        process = self.process
        if process is not None:
            try:
                process.write("exit\r")
            except Exception:
                pass

            for _ in range(10):
                if not process.isalive():
                    break
                await asyncio.sleep(0.1)

            if process.isalive():
                try:
                    process.terminate(force=False)
                except Exception:
                    pass
                for _ in range(10):
                    if not process.isalive():
                        break
                    await asyncio.sleep(0.1)

            if process.isalive():
                try:
                    process.terminate(force=True)
                except Exception:
                    pass

            try:
                process.close(force=True)
            except Exception:
                pass

        self.clients.clear()
        if self.pump_task is not None:
            await asyncio.sleep(0)


class _TerminalServerThread(threading.Thread):
    def __init__(self, start_dir: Path) -> None:
        super().__init__(name="nino-terminal-service", daemon=True)
        self.start_dir = start_dir
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_event: asyncio.Event | None = None
        self.ready_event = threading.Event()
        self.stopped_event = threading.Event()
        self.error: str | None = None
        self.server = None
        self.sessions: dict[str, _TerminalSession] = {}
        self.client_sessions: dict[ServerConnection, str | None] = {}
        self._session_counter = 0

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()
        try:
            self.loop.run_until_complete(self._run_async())
        except Exception as exc:  # pragma: no cover - defensive path
            self.error = str(exc)
            self.ready_event.set()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
            self.stopped_event.set()

    async def _run_async(self) -> None:
        async with serve(
            self._handle_client,
            TERMINAL_HOST,
            TERMINAL_PORT,
            compression=None,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=10,
        ) as server:
            self.server = server
            self.ready_event.set()
            await self.stop_event.wait()

        await self._shutdown_all_sessions()

    async def _handle_client(self, websocket: ServerConnection) -> None:
        self.client_sessions[websocket] = None
        await websocket.send(json.dumps({"type": "service", **self.service_snapshot()}))
        await self._send_sessions_list(websocket)
        try:
            async for raw_message in websocket:
                if isinstance(raw_message, bytes):
                    continue
                try:
                    payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                await self._dispatch_client_message(websocket, payload)
        finally:
            self._detach_client(websocket)
            self.client_sessions.pop(websocket, None)

    async def _dispatch_client_message(self, websocket: ServerConnection, payload: dict[str, Any]) -> None:
        message_type = str(payload.get("type", "")).strip().lower()
        if message_type == "list_sessions":
            await self._send_sessions_list(websocket)
            return

        if message_type == "create_session":
            session = await self.create_session()
            await websocket.send(json.dumps({"type": "session_created", **session}))
            if payload.get("attach", True):
                await self.attach_session(websocket, session["session_id"])
            return

        session_id = str(payload.get("session_id", "")).strip()

        if message_type == "attach_session":
            if session_id:
                await self.attach_session(websocket, session_id)
            return

        if message_type == "close_session":
            if session_id:
                await self.close_session(session_id)
            return

        if message_type == "ping":
            target_session = self._resolve_session_for_payload(websocket, payload)
            if target_session is None:
                await websocket.send(json.dumps({"type": "pong"}))
                return
            await target_session.handle_client_message(websocket, payload)
            return

        target_session = self._resolve_session_for_payload(websocket, payload)
        if target_session is None:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "message": "session_id invalide",
                    }
                )
            )
            return
        await target_session.handle_client_message(websocket, payload)

    def _resolve_session_for_payload(
        self,
        websocket: ServerConnection,
        payload: dict[str, Any],
    ) -> _TerminalSession | None:
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            attached_session_id = self.client_sessions.get(websocket)
            if attached_session_id:
                session_id = attached_session_id
        if not session_id:
            return None
        return self.sessions.get(session_id)

    async def create_session(self) -> dict[str, Any]:
        self._session_counter += 1
        session_id = f"powershell-{self._session_counter}"
        display_name = f"PowerShell {self._session_counter}"
        session = _TerminalSession(self.loop, session_id, display_name, self.start_dir)
        await session.start()
        self.sessions[session_id] = session
        await self._broadcast_sessions_list()
        return session.snapshot()

    async def close_session(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False

        detached_clients = [
            websocket
            for websocket, attached_session_id in self.client_sessions.items()
            if attached_session_id == session_id
        ]
        for websocket in detached_clients:
            self.client_sessions[websocket] = None
            session.detach_client(websocket)

        await session.shutdown(notify_clients=True)
        await self._broadcast_sessions_list()
        return True

    async def list_sessions(self) -> list[dict[str, Any]]:
        sessions = [session.snapshot() for session in self.sessions.values()]
        sessions.sort(key=lambda item: item["created_at"])
        return sessions

    async def session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return session.snapshot()

    async def attach_session(self, websocket: ServerConnection, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Session introuvable: {session_id}",
                        "session_id": session_id,
                    }
                )
            )
            return False

        self._detach_client(websocket)
        self.client_sessions[websocket] = session_id
        session.attach_client(websocket)
        await session.send_snapshot(websocket)
        return True

    def _detach_client(self, websocket: ServerConnection) -> None:
        session_id = self.client_sessions.get(websocket)
        if not session_id:
            return
        session = self.sessions.get(session_id)
        if session is not None:
            session.detach_client(websocket)
        self.client_sessions[websocket] = None

    async def _send_sessions_list(self, websocket: ServerConnection) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "sessions",
                    "sessions": await self.list_sessions(),
                }
            )
        )

    async def _broadcast_sessions_list(self) -> None:
        if not self.client_sessions:
            return
        data = json.dumps(
            {
                "type": "sessions",
                "sessions": await self.list_sessions(),
            }
        )
        stale: list[ServerConnection] = []
        for websocket in list(self.client_sessions):
            try:
                await websocket.send(data)
            except ConnectionClosed:
                stale.append(websocket)
        for websocket in stale:
            self._detach_client(websocket)
            self.client_sessions.pop(websocket, None)

    async def _shutdown_all_sessions(self) -> None:
        sessions = list(self.sessions.values())
        self.sessions.clear()
        for websocket in list(self.client_sessions):
            try:
                await websocket.close()
            except Exception:
                pass
        self.client_sessions.clear()
        for session in sessions:
            await session.shutdown(notify_clients=False)

    def request_stop(self) -> None:
        if self.loop is not None and self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def service_snapshot(self) -> dict[str, Any]:
        return {
            "host": TERMINAL_HOST,
            "port": TERMINAL_PORT,
            "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
            "manual_mode": True,
            "session_count": len(self.sessions),
            "ready": self.ready_event.is_set() and not self.error,
        }


class TerminalRuntime:
    def __init__(self, start_dir: Path | None = None) -> None:
        self.start_dir = start_dir or _project_root()
        self._thread: _TerminalServerThread | None = None
        self._lock = threading.Lock()

    def ensure_started(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                thread = _TerminalServerThread(self.start_dir)
                self._thread = thread
                thread.start()

        if not thread.ready_event.wait(TERMINAL_READY_TIMEOUT_SECONDS):
            raise TerminalRuntimeError("Le service terminal local n’a pas démarré à temps.")

        if thread.error:
            raise TerminalRuntimeError(thread.error)

        return thread.service_snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
        if thread is None:
            return {
                "host": TERMINAL_HOST,
                "port": TERMINAL_PORT,
                "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
                "manual_mode": True,
                "session_count": 0,
                "ready": False,
            }
        return thread.service_snapshot()

    def list_sessions(self) -> list[dict[str, Any]]:
        self.ensure_started()
        return self._call_threadsafe(lambda thread: thread.list_sessions())

    def create_session(self) -> dict[str, Any]:
        self.ensure_started()
        return self._call_threadsafe(lambda thread: thread.create_session())

    def close_session(self, session_id: str) -> bool:
        self.ensure_started()
        return self._call_threadsafe(lambda thread: thread.close_session(session_id))

    def session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        self.ensure_started()
        return self._call_threadsafe(lambda thread: thread.session_snapshot(session_id))

    def _call_threadsafe(
        self,
        coroutine_factory: Callable[[_TerminalServerThread], Awaitable[Any]],
    ) -> Any:
        with self._lock:
            thread = self._thread
        if thread is None or thread.loop is None:
            raise TerminalRuntimeError("Le service terminal local n’est pas disponible.")
        if thread.error:
            raise TerminalRuntimeError(thread.error)

        future = asyncio.run_coroutine_threadsafe(coroutine_factory(thread), thread.loop)
        try:
            return future.result(timeout=TERMINAL_REQUEST_TIMEOUT_SECONDS)
        except FutureTimeoutError as exc:
            raise TerminalRuntimeError("Le service terminal local n’a pas répondu à temps.") from exc

    def shutdown(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None

        if thread is None:
            return

        thread.request_stop()
        thread.stopped_event.wait(TERMINAL_SHUTDOWN_TIMEOUT_SECONDS)

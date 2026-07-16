from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import json
import os
from pathlib import Path
import threading
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from winpty import PtyProcess


TERMINAL_HOST = "127.0.0.1"
TERMINAL_PORT = int(os.environ.get("NINO_TERMINAL_PORT", "8765"))
TERMINAL_SESSION_ID = "powershell-main"
TERMINAL_BUFFER_LIMIT = 500_000
TERMINAL_DEFAULT_COLS = 120
TERMINAL_DEFAULT_ROWS = 30
TERMINAL_READY_TIMEOUT_SECONDS = 8.0
TERMINAL_SHUTDOWN_TIMEOUT_SECONDS = 8.0


class TerminalRuntimeError(RuntimeError):
    pass


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _powershell_command() -> list[str]:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell_path = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return [str(powershell_path), "-NoLogo", "-NoProfile"]


class _TerminalSession:
    def __init__(self, loop: asyncio.AbstractEventLoop, start_dir: Path) -> None:
        self.loop = loop
        self.start_dir = start_dir
        self.command = _powershell_command()
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
        self.pump_task = asyncio.create_task(self._pump_output(), name="nino-terminal-output-pump")
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            name="nino-terminal-reader",
            daemon=True,
        )
        self.reader_thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self.buffer_lock:
            buffer_size = len(self.buffer)
        process = self.process
        return {
            "session_id": TERMINAL_SESSION_ID,
            "pid": getattr(process, "pid", None),
            "cwd": str(self.start_dir),
            "command": list(self.command),
            "host": TERMINAL_HOST,
            "port": TERMINAL_PORT,
            "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
            "manual_mode": True,
            "alive": bool(process and process.isalive()),
            "client_count": len(self.clients),
            "buffer_size": buffer_size,
        }

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
                return
            self._append_to_buffer(chunk)
            await self._broadcast({"type": "output", "data": chunk})

    def _append_to_buffer(self, chunk: str) -> None:
        with self.buffer_lock:
            self.buffer += chunk
            if len(self.buffer) > TERMINAL_BUFFER_LIMIT:
                self.buffer = self.buffer[-TERMINAL_BUFFER_LIMIT:]

    async def attach(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)
        await websocket.send(json.dumps({"type": "snapshot", "data": self._buffer_copy()}))
        await websocket.send(json.dumps({"type": "meta", **self.snapshot()}))
        try:
            async for raw_message in websocket:
                if isinstance(raw_message, bytes):
                    continue
                await self._handle_message(websocket, raw_message)
        finally:
            self.clients.discard(websocket)

    def _buffer_copy(self) -> str:
        with self.buffer_lock:
            return self.buffer

    async def _handle_message(self, websocket: ServerConnection, raw_message: str) -> None:
        process = self.process
        if process is None:
            return

        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
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
            await websocket.send(json.dumps({"type": "pong"}))

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

    async def shutdown(self) -> None:
        self.closed = True

        for websocket in list(self.clients):
            try:
                await websocket.close()
            except Exception:
                pass
        self.clients.clear()

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
        self.session: _TerminalSession | None = None
        self.server = None

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
        self.session = _TerminalSession(self.loop, self.start_dir)
        await self.session.start()

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

        if self.session is not None:
            await self.session.shutdown()

    async def _handle_client(self, websocket: ServerConnection) -> None:
        if self.session is None:
            await websocket.close(code=1011, reason="session unavailable")
            return
        await self.session.attach(websocket)

    def request_stop(self) -> None:
        if self.loop is not None and self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def snapshot(self) -> dict[str, Any]:
        if self.session is None:
            return {
                "session_id": TERMINAL_SESSION_ID,
                "pid": None,
                "cwd": str(self.start_dir),
                "command": _powershell_command(),
                "host": TERMINAL_HOST,
                "port": TERMINAL_PORT,
                "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
                "manual_mode": True,
                "alive": False,
                "client_count": 0,
                "buffer_size": 0,
            }
        return self.session.snapshot()


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

        snapshot = thread.snapshot()
        if not snapshot.get("alive"):
            raise TerminalRuntimeError("La session PowerShell locale n’est pas active.")
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
        if thread is None:
            return {
                "session_id": TERMINAL_SESSION_ID,
                "pid": None,
                "cwd": str(self.start_dir),
                "command": _powershell_command(),
                "host": TERMINAL_HOST,
                "port": TERMINAL_PORT,
                "ws_url": f"ws://{TERMINAL_HOST}:{TERMINAL_PORT}",
                "manual_mode": True,
                "alive": False,
                "client_count": 0,
                "buffer_size": 0,
            }
        return thread.snapshot()

    def shutdown(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None

        if thread is None:
            return

        thread.request_stop()
        thread.stopped_event.wait(TERMINAL_SHUTDOWN_TIMEOUT_SECONDS)


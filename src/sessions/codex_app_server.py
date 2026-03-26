"""Async JSON-RPC client for `codex app-server` over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INITIALIZE_METHOD = "initialize"
THREAD_START_METHOD = "thread/start"
THREAD_RESUME_METHOD = "thread/resume"
THREAD_ARCHIVE_METHOD = "thread/archive"
THREAD_COMPACT_START_METHOD = "thread/compact/start"
TURN_START_METHOD = "turn/start"
TURN_STEER_METHOD = "turn/steer"
TURN_INTERRUPT_METHOD = "turn/interrupt"


class CodexAppServerError(RuntimeError):
    """Raised for transport or JSON-RPC protocol failures."""


class CodexAppServerClient:
    """Small async JSON-RPC client tailored for one Codex session thread."""

    def __init__(
        self,
        *,
        cwd: str,
        codex_bin: str | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.cwd = cwd
        self.codex_bin = codex_bin or shutil.which("codex")
        if not self.codex_bin:
            raise CodexAppServerError("Could not find `codex` binary in PATH")

        self.request_timeout = request_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=200)

    async def start(self) -> None:
        """Start app-server and perform initialize handshake."""
        if self._proc is not None:
            return

        self._proc = await asyncio.create_subprocess_exec(
            self.codex_bin,
            "app-server",
            "--listen",
            "stdio://",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self.request(
            INITIALIZE_METHOD,
            {
                "clientInfo": {
                    "name": "telegram-multi-thread-router",
                    "title": "Telegram Multi-Thread Router",
                    "version": "2.0.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                },
            },
        )

    async def close(self) -> None:
        """Terminate the subprocess and fail any pending requests."""
        proc = self._proc
        self._proc = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(CodexAppServerError("app-server client is closing"))
        self._pending.clear()

        for task in (self._stdout_task, self._stderr_task):
            if task is not None:
                task.cancel()
        if self._stdout_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._stdout_task
        if self._stderr_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
        self._stdout_task = None
        self._stderr_task = None

        if proc is None:
            return
        if proc.stdin is not None:
            proc.stdin.close()
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send one JSON-RPC request and wait for its result."""
        if self._proc is None or self._proc.stdin is None:
            raise CodexAppServerError("app-server is not running")

        self._request_id += 1
        request_id = self._request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

        try:
            response = await asyncio.wait_for(future, timeout=self.request_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise CodexAppServerError(
                f"Timed out waiting for app-server response to {method}"
            ) from exc

        if "error" in response:
            error = response["error"]
            message = error.get("message", "JSON-RPC error") if isinstance(error, dict) else str(error)
            raise CodexAppServerError(f"{method} failed: {message}")
        return response.get("result")

    async def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        """Respond to one server-initiated JSON-RPC request."""
        if self._proc is None or self._proc.stdin is None:
            raise CodexAppServerError("app-server is not running")
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def next_message(self) -> dict[str, Any]:
        """Return the next non-response message from the server."""
        return await self._messages.get()

    async def _read_stdout(self) -> None:
        """Continuously route JSON-RPC responses and notifications."""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    raise CodexAppServerError(
                        "app-server closed stdout. stderr_tail=" + "\n".join(self._stderr_tail)
                    )
                message = json.loads(line.decode("utf-8"))
                if "id" in message and "method" not in message:
                    future = self._pending.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                await self._messages.put(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Codex app-server stdout reader failed: %s", e)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(e)
            self._pending.clear()

    async def _read_stderr(self) -> None:
        """Drain stderr and keep a short tail for diagnostics."""
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._stderr_tail.append(text)
                    logger.debug("Codex app-server stderr: %s", text)
        except asyncio.CancelledError:
            raise

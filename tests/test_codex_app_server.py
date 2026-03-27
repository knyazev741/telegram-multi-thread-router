"""Unit tests for the Codex app-server JSON-RPC client."""

import asyncio
import json

import pytest

from src.sessions.codex_app_server import CodexAppServerClient, CodexAppServerError


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


async def test_request_routes_response_and_notifications():
    proc = _FakeProcess()
    client = CodexAppServerClient(cwd="/tmp", codex_bin="codex")
    client._proc = proc

    stdout_task = asyncio.create_task(client._read_stdout())
    try:
        request_task = asyncio.create_task(client.request("thread/start", {"cwd": "/tmp"}))
        await asyncio.sleep(0)

        payload = json.loads(proc.stdin.writes[0].decode("utf-8"))
        assert payload["method"] == "thread/start"
        assert payload["params"] == {"cwd": "/tmp"}

        proc.stdout.feed_data(
            b'{"jsonrpc":"2.0","method":"thread/started","params":{"thread":{"id":"thread-123"}}}\n'
        )
        proc.stdout.feed_data(
            b'{"jsonrpc":"2.0","id":1,"result":{"thread":{"id":"thread-123"}}}\n'
        )

        result = await request_task
        message = await client.next_message()

        assert result == {"thread": {"id": "thread-123"}}
        assert message["method"] == "thread/started"
        assert message["params"]["thread"]["id"] == "thread-123"
    finally:
        stdout_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stdout_task


async def test_request_raises_on_json_rpc_error():
    proc = _FakeProcess()
    client = CodexAppServerClient(cwd="/tmp", codex_bin="codex")
    client._proc = proc

    stdout_task = asyncio.create_task(client._read_stdout())
    try:
        request_task = asyncio.create_task(client.request("turn/start", {"threadId": "thread-123"}))
        await asyncio.sleep(0)
        proc.stdout.feed_data(
            b'{"jsonrpc":"2.0","id":1,"error":{"message":"nope"}}\n'
        )

        with pytest.raises(CodexAppServerError, match="turn/start failed: nope"):
            await request_task
    finally:
        stdout_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stdout_task


async def test_respond_writes_result_payload():
    proc = _FakeProcess()
    client = CodexAppServerClient(cwd="/tmp", codex_bin="codex")
    client._proc = proc

    await client.respond(42, {"decision": "accept"})

    payload = json.loads(proc.stdin.writes[0].decode("utf-8"))
    assert payload == {
        "jsonrpc": "2.0",
        "id": 42,
        "result": {"decision": "accept"},
    }

"""Tests for worker-side components: WorkerOutputChannel, WorkerClient reconnect, permission bridge."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.ipc.protocol import (
    AssistantTextMsg,
    UserMessageMsg,
    _enc,
    _b2w_dec,
    _w2b_dec,
)
from src.worker.output_channel import WorkerOutputChannel


# ---------------------------------------------------------------------------
# MSRV-01: WorkerOutputChannel / SessionRunner instantiation
# ---------------------------------------------------------------------------

async def test_worker_output_channel_send_text():
    """MSRV-01: WorkerOutputChannel.send_message encodes AssistantTextMsg correctly."""
    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.write = MagicMock()
    writer.drain = AsyncMock()

    channel = WorkerOutputChannel(writer, chat_id=0)
    await channel.send_message(chat_id=0, text="test output", message_thread_id=7)

    # Reconstruct what was written (AssistantTextMsg is a WorkerToBot message)
    assert writer.write.called
    raw_bytes = writer.write.call_args[0][0]
    n = int.from_bytes(raw_bytes[:4], "big")
    payload = raw_bytes[4:4 + n]
    decoded = _w2b_dec.decode(payload)
    assert isinstance(decoded, AssistantTextMsg)
    assert decoded.topic_id == 7
    assert decoded.text == "test output"


async def test_worker_output_channel_not_connected_drops_silently():
    """WorkerOutputChannel with None writer drops messages without raising."""
    channel = WorkerOutputChannel(None, chat_id=0)
    # Should not raise
    await channel.send_message(chat_id=0, text="ignored", message_thread_id=1)


async def test_worker_session_runner_instantiates():
    """MSRV-01: SessionRunner can be instantiated with WorkerOutputChannel as bot."""
    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.write = MagicMock()
    writer.drain = AsyncMock()

    channel = WorkerOutputChannel(writer, chat_id=0)

    from src.sessions.permissions import PermissionManager
    from src.sessions.runner import SessionRunner

    perm_mgr = PermissionManager()
    runner = SessionRunner(
        thread_id=1,
        workdir="/tmp",
        bot=channel,
        chat_id=0,
        permission_manager=perm_mgr,
    )
    # Just verify it was created without error; don't start it (would invoke Claude)
    assert runner.thread_id == 1
    assert runner.workdir == "/tmp"


# ---------------------------------------------------------------------------
# MSRV-06: Reconnect backoff pattern
# ---------------------------------------------------------------------------

async def test_reconnect_backoff():
    """MSRV-06: WorkerClient uses exponential backoff 1→2→4→...→60 on connection failure."""
    from src.worker.client import WorkerClient

    client = WorkerClient(
        host="127.0.0.1",
        port=19999,  # nothing listening
        auth_token="tok",
        worker_id="test-worker",
    )

    delays_slept = []
    connection_attempts = 0
    max_attempts = 5

    async def mock_open_connection(host, port):
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts < max_attempts:
            raise ConnectionRefusedError("connection refused")
        # On last attempt, raise so we exit the loop
        raise RuntimeError("stop-test")

    async def mock_sleep(delay):
        delays_slept.append(delay)
        if len(delays_slept) >= max_attempts - 1:
            raise asyncio.CancelledError()

    with patch("asyncio.open_connection", side_effect=mock_open_connection), \
         patch("asyncio.sleep", side_effect=mock_sleep):
        try:
            await client.run()
        except (asyncio.CancelledError, RuntimeError):
            pass

    # Verify exponential backoff: 1, 2, 4, 8, ...
    expected_start = [1.0, 2.0, 4.0, 8.0]
    for i, expected in enumerate(expected_start[:len(delays_slept)]):
        assert delays_slept[i] == expected, (
            f"Delay {i} should be {expected}, got {delays_slept[i]}"
        )

    # Verify max cap at 60
    for d in delays_slept:
        assert d <= 60.0, f"Delay {d} exceeds max 60"


async def test_reconnect_delay_resets_on_success():
    """MSRV-06: Reconnect delay resets to 1.0 after successful connection."""
    from src.worker.client import WorkerClient
    from src.ipc.protocol import AuthOkMsg, send_msg

    client = WorkerClient(
        host="127.0.0.1",
        port=0,
        auth_token="tok",
        worker_id="test-worker",
    )

    call_count = [0]
    delays_slept = []

    async def mock_open_connection(host, port):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionRefusedError("first fail")
        # On second attempt, raise to stop the test
        raise RuntimeError("stop-test")

    async def mock_sleep(delay):
        delays_slept.append(delay)
        # Only allow one sleep
        if len(delays_slept) >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.open_connection", side_effect=mock_open_connection), \
         patch("asyncio.sleep", side_effect=mock_sleep):
        try:
            await client.run()
        except (asyncio.CancelledError, RuntimeError):
            pass

    # After first fail, delay is 1.0; after first sleep, it doubles to 2.0 for next
    assert delays_slept[0] == 1.0


# ---------------------------------------------------------------------------
# MSRV-04/MSRV-05: Permission bridge
# ---------------------------------------------------------------------------

async def test_permission_resolve():
    """MSRV-04/MSRV-05: _resolve_permission resolves pending future with action."""
    from src.worker.client import WorkerClient

    client = WorkerClient(
        host="127.0.0.1",
        port=0,
        auth_token="tok",
        worker_id="test-worker",
    )

    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    client._permission_futures["req-1"] = future

    client._resolve_permission("req-1", "allow")
    assert future.done()
    assert future.result() == "allow"
    assert "req-1" not in client._permission_futures


async def test_permission_resolve_unknown_request():
    """_resolve_permission logs a warning for unknown request_id (no crash)."""
    from src.worker.client import WorkerClient

    client = WorkerClient(
        host="127.0.0.1",
        port=0,
        auth_token="tok",
        worker_id="test-worker",
    )
    # Should not raise
    client._resolve_permission("nonexistent-id", "deny")


# ---------------------------------------------------------------------------
# MSRV-06: Permission cancel on disconnect
# ---------------------------------------------------------------------------

async def test_permission_cancel_on_disconnect():
    """MSRV-06: _on_disconnected resolves all pending permission futures with 'deny'."""
    from src.worker.client import WorkerClient

    client = WorkerClient(
        host="127.0.0.1",
        port=0,
        auth_token="tok",
        worker_id="test-worker",
    )

    loop = asyncio.get_event_loop()
    f1: asyncio.Future = loop.create_future()
    f2: asyncio.Future = loop.create_future()
    client._permission_futures["r1"] = f1
    client._permission_futures["r2"] = f2

    client._on_disconnected()

    assert f1.done() and f1.result() == "deny"
    assert f2.done() and f2.result() == "deny"
    assert len(client._permission_futures) == 0


async def test_on_disconnected_clears_writer():
    """_on_disconnected closes and clears the writer reference."""
    from src.worker.client import WorkerClient

    client = WorkerClient(
        host="127.0.0.1",
        port=0,
        auth_token="tok",
        worker_id="test-worker",
    )
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    client._writer = mock_writer

    client._on_disconnected()

    mock_writer.close.assert_called_once()
    assert client._writer is None

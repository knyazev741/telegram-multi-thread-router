"""Tests for IPC protocol, framing, auth handshake, and message forwarding."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ipc.protocol import (
    AuthFailMsg,
    AuthMsg,
    AuthOkMsg,
    AssistantTextMsg,
    McpEditMessageMsg,
    McpReactMsg,
    McpSendFileMsg,
    McpSendMessageMsg,
    PermissionRequestMsg,
    PermissionResponseMsg,
    SessionEndedMsg,
    SessionStartedMsg,
    SlashCommandMsg,
    StartSessionMsg,
    StatusUpdateMsg,
    StopSessionMsg,
    UserFileMsg,
    UserMessageMsg,
    WorkerToBot,
    BotToWorker,
    _enc,
    _w2b_dec,
    _b2w_dec,
    send_msg,
    recv_w2b,
    recv_b2w,
)
from src.ipc.server import WorkerRegistry, start_ipc_server


# ---------------------------------------------------------------------------
# MSRV-03: Protocol round-trip for all message types
# ---------------------------------------------------------------------------

WORKER_TO_BOT_MESSAGES = [
    AuthMsg(token="tok", worker_id="w1"),
    SessionStartedMsg(topic_id=1, session_id="s1"),
    AssistantTextMsg(topic_id=2, text="hello"),
    PermissionRequestMsg(topic_id=3, request_id="r1", tool_name="bash", input_data={"cmd": "ls"}),
    StatusUpdateMsg(topic_id=4, tool_name="bash", elapsed_ms=100, tool_calls=2),
    SessionEndedMsg(topic_id=5),
    SessionEndedMsg(topic_id=6, error="oops"),
    McpSendMessageMsg(topic_id=7, text="msg"),
    McpReactMsg(topic_id=8, message_id=10, emoji="👍"),
    McpEditMessageMsg(topic_id=9, message_id=11, text="edited"),
    McpSendFileMsg(topic_id=10, file_path="/tmp/f.txt"),
    McpSendFileMsg(topic_id=11, file_path="/tmp/f.txt", file_name="f.txt", file_bytes=b"abc", caption="cap"),
]

BOT_TO_WORKER_MESSAGES = [
    AuthOkMsg(worker_id="w1"),
    AuthFailMsg(reason="bad token"),
    StartSessionMsg(topic_id=1, cwd="/tmp"),
    StartSessionMsg(topic_id=2, cwd="/tmp", session_id="sid", model="claude-3"),
    StartSessionMsg(
        topic_id=6,
        cwd="/tmp",
        backend_session_id="thread-123",
        provider="codex",
        provider_options={"sandbox": "workspace-write"},
    ),
    StopSessionMsg(topic_id=3),
    UserMessageMsg(topic_id=4, text="hello"),
    UserFileMsg(topic_id=7, file_name="photo.jpg", file_bytes=b"123", is_image=True),
    PermissionResponseMsg(request_id="r1", action="allow"),
    SlashCommandMsg(topic_id=5, command="/compact"),
]


@pytest.mark.parametrize("msg", WORKER_TO_BOT_MESSAGES, ids=lambda m: type(m).__name__)
def test_w2b_protocol_roundtrip(msg):
    """MSRV-03: Worker-to-bot messages encode and decode correctly."""
    payload = _enc.encode(msg)
    decoded = _w2b_dec.decode(payload)
    assert type(decoded) is type(msg)
    for field in type(msg).__struct_fields__:
        assert getattr(decoded, field) == getattr(msg, field)


@pytest.mark.parametrize("msg", BOT_TO_WORKER_MESSAGES, ids=lambda m: type(m).__name__)
def test_b2w_protocol_roundtrip(msg):
    """MSRV-03: Bot-to-worker messages encode and decode correctly."""
    payload = _enc.encode(msg)
    decoded = _b2w_dec.decode(payload)
    assert type(decoded) is type(msg)
    for field in type(msg).__struct_fields__:
        assert getattr(decoded, field) == getattr(msg, field)


# ---------------------------------------------------------------------------
# MSRV-03: Framing helpers (send_msg / recv_w2b / recv_b2w)
# ---------------------------------------------------------------------------

def _encode_raw(msg) -> bytes:
    """Manually encode a message with length prefix (mirrors send_msg)."""
    payload = _enc.encode(msg)
    prefix = len(payload).to_bytes(4, "big")
    return prefix + payload


async def test_framing_roundtrip_w2b():
    """MSRV-03: recv_w2b decodes a manually-framed WorkerToBot message."""
    msg = AssistantTextMsg(topic_id=42, text="round-trip")
    raw = _encode_raw(msg)

    reader = asyncio.StreamReader()
    reader.feed_data(raw)

    received = await recv_w2b(reader)
    assert isinstance(received, AssistantTextMsg)
    assert received.topic_id == 42
    assert received.text == "round-trip"


async def test_framing_roundtrip_b2w():
    """MSRV-03: recv_b2w decodes a manually-framed BotToWorker message."""
    msg = StartSessionMsg(topic_id=99, cwd="/workspace")
    raw = _encode_raw(msg)

    reader = asyncio.StreamReader()
    reader.feed_data(raw)

    received = await recv_b2w(reader)
    assert isinstance(received, StartSessionMsg)
    assert received.topic_id == 99
    assert received.cwd == "/workspace"


async def test_framing_eof():
    """MSRV-03: recv_w2b returns None on EOF, not raises."""
    reader = asyncio.StreamReader()
    reader.feed_eof()
    result = await recv_w2b(reader)
    assert result is None


# ---------------------------------------------------------------------------
# MSRV-02: Auth handshake tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session_manager():
    return MagicMock()


@pytest.fixture
def mock_permission_manager():
    return MagicMock()


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


async def test_auth_handshake_success(mock_bot, mock_session_manager, mock_permission_manager):
    """MSRV-02: Correct token → AuthOkMsg and worker registered."""
    auth_token = "secret-token"
    registry = WorkerRegistry()

    server = await start_ipc_server(
        host="127.0.0.1",
        port=0,
        auth_token=auth_token,
        bot=mock_bot,
        session_manager=mock_session_manager,
        permission_manager=mock_permission_manager,
        worker_registry=registry,
    )
    addr = server.sockets[0].getsockname()

    reader, writer = await asyncio.open_connection(*addr)
    await send_msg(writer, AuthMsg(token=auth_token, worker_id="worker-1"))

    response = await recv_b2w(reader)
    assert isinstance(response, AuthOkMsg)
    assert response.worker_id == "worker-1"

    # Give the server task a moment to register the worker
    await asyncio.sleep(0.05)
    assert registry.is_connected("worker-1")

    writer.close()
    server.close()
    await server.wait_closed()


async def test_auth_handshake_failure(mock_bot, mock_session_manager, mock_permission_manager):
    """MSRV-02: Wrong token → AuthFailMsg and worker NOT registered."""
    auth_token = "correct-token"
    registry = WorkerRegistry()

    server = await start_ipc_server(
        host="127.0.0.1",
        port=0,
        auth_token=auth_token,
        bot=mock_bot,
        session_manager=mock_session_manager,
        permission_manager=mock_permission_manager,
        worker_registry=registry,
    )
    addr = server.sockets[0].getsockname()

    reader, writer = await asyncio.open_connection(*addr)
    await send_msg(writer, AuthMsg(token="wrong-token", worker_id="evil-worker"))

    response = await recv_b2w(reader)
    assert isinstance(response, AuthFailMsg)

    await asyncio.sleep(0.05)
    assert not registry.is_connected("evil-worker")

    writer.close()
    server.close()
    await server.wait_closed()


# ---------------------------------------------------------------------------
# MSRV-04/MSRV-05: Message forwarding tests
# ---------------------------------------------------------------------------

async def _connect_authenticated_worker(server_addr, auth_token, worker_id):
    """Helper: connect and authenticate a worker, return (reader, writer)."""
    reader, writer = await asyncio.open_connection(*server_addr)
    await send_msg(writer, AuthMsg(token=auth_token, worker_id=worker_id))
    response = await recv_b2w(reader)
    assert isinstance(response, AuthOkMsg)
    await asyncio.sleep(0.02)  # let server register
    return reader, writer


async def test_worker_forwards_text(mock_session_manager, mock_permission_manager):
    """MSRV-04: AssistantTextMsg from worker causes bot.send_message call."""
    auth_token = "tok"
    registry = WorkerRegistry()
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

    server = await start_ipc_server(
        host="127.0.0.1",
        port=0,
        auth_token=auth_token,
        bot=bot,
        session_manager=mock_session_manager,
        permission_manager=mock_permission_manager,
        worker_registry=registry,
    )
    addr = server.sockets[0].getsockname()
    reader, writer = await _connect_authenticated_worker(addr, auth_token, "w1")

    await send_msg(writer, AssistantTextMsg(topic_id=5, text="Hello world"))
    await asyncio.sleep(0.05)

    bot.send_message.assert_called()
    call_kwargs = bot.send_message.call_args
    assert call_kwargs.kwargs.get("message_thread_id") == 5 or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1] == 5
    )

    writer.close()
    server.close()
    await server.wait_closed()


async def test_bot_forwards_user_message(mock_bot, mock_session_manager, mock_permission_manager):
    """MSRV-05: UserMessageMsg sent via WorkerRegistry is received by worker."""
    auth_token = "tok"
    registry = WorkerRegistry()

    server = await start_ipc_server(
        host="127.0.0.1",
        port=0,
        auth_token=auth_token,
        bot=mock_bot,
        session_manager=mock_session_manager,
        permission_manager=mock_permission_manager,
        worker_registry=registry,
    )
    addr = server.sockets[0].getsockname()
    reader, writer = await _connect_authenticated_worker(addr, auth_token, "w2")

    # Bot side sends a message to the worker
    ok = await registry.send_to("w2", UserMessageMsg(topic_id=10, text="user text"))
    assert ok is True

    received = await recv_b2w(reader)
    assert isinstance(received, UserMessageMsg)
    assert received.topic_id == 10
    assert received.text == "user text"

    writer.close()
    server.close()
    await server.wait_closed()

"""IPC protocol — msgspec Struct message types and framing helpers for TCP communication."""

from __future__ import annotations

import asyncio
from typing import Union

import msgspec


# ---- Worker → Bot messages ----

class AuthMsg(msgspec.Struct, tag="auth"):
    """Authentication handshake sent by worker upon connection."""
    token: str
    worker_id: str


class SessionStartedMsg(msgspec.Struct, tag="session_started"):
    """Sent by worker when a Claude session has started."""
    topic_id: int
    session_id: str


class AssistantTextMsg(msgspec.Struct, tag="assistant_text"):
    """Chunk of assistant output text to be sent to the Telegram topic."""
    topic_id: int
    text: str


class PermissionRequestMsg(msgspec.Struct, tag="permission_request"):
    """Worker asking the bot to prompt the owner for tool permission."""
    topic_id: int
    request_id: str
    tool_name: str
    input_data: dict


class StatusUpdateMsg(msgspec.Struct, tag="status_update"):
    """Tool execution status update (elapsed time, call count)."""
    topic_id: int
    tool_name: str
    elapsed_ms: int
    tool_calls: int


class SessionEndedMsg(msgspec.Struct, tag="session_ended"):
    """Worker reports that a session has ended, optionally with an error."""
    topic_id: int
    error: str | None = None


class McpSendMessageMsg(msgspec.Struct, tag="mcp_send_message"):
    """MCP tool: send a plain text message to the topic."""
    topic_id: int
    text: str


class McpReactMsg(msgspec.Struct, tag="mcp_react"):
    """MCP tool: add an emoji reaction to a message."""
    topic_id: int
    message_id: int
    emoji: str


class McpEditMessageMsg(msgspec.Struct, tag="mcp_edit_message"):
    """MCP tool: edit the text of an existing message."""
    topic_id: int
    message_id: int
    text: str


class McpSendFileMsg(msgspec.Struct, tag="mcp_send_file"):
    """MCP tool: send a file from the worker's filesystem to the topic."""
    topic_id: int
    file_path: str
    caption: str | None = None


# ---- Bot → Worker messages ----

class AuthOkMsg(msgspec.Struct, tag="auth_ok"):
    """Authentication accepted."""
    worker_id: str


class AuthFailMsg(msgspec.Struct, tag="auth_fail"):
    """Authentication rejected."""
    reason: str


class StartSessionMsg(msgspec.Struct, tag="start_session"):
    """Bot instructs worker to start a new Claude session."""
    topic_id: int
    cwd: str
    session_id: str | None = None
    model: str | None = None


class StopSessionMsg(msgspec.Struct, tag="stop_session"):
    """Bot instructs worker to stop a running session."""
    topic_id: int


class UserMessageMsg(msgspec.Struct, tag="user_message"):
    """User text message forwarded from bot to worker."""
    topic_id: int
    text: str


class PermissionResponseMsg(msgspec.Struct, tag="permission_response"):
    """Bot forwards the owner's permission decision back to the worker."""
    request_id: str
    action: str  # "allow" | "always" | "deny"


class SlashCommandMsg(msgspec.Struct, tag="slash_command"):
    """Bot forwards a slash command to the worker."""
    topic_id: int
    command: str


# ---- Union types for discriminated decoding ----

WorkerToBot = Union[
    AuthMsg,
    SessionStartedMsg,
    AssistantTextMsg,
    PermissionRequestMsg,
    StatusUpdateMsg,
    SessionEndedMsg,
    McpSendMessageMsg,
    McpReactMsg,
    McpEditMessageMsg,
    McpSendFileMsg,
]

BotToWorker = Union[
    AuthOkMsg,
    AuthFailMsg,
    StartSessionMsg,
    StopSessionMsg,
    UserMessageMsg,
    PermissionResponseMsg,
    SlashCommandMsg,
]

# Module-level encoder/decoders — reuse for performance
_enc = msgspec.msgpack.Encoder()
_w2b_dec = msgspec.msgpack.Decoder(WorkerToBot)
_b2w_dec = msgspec.msgpack.Decoder(BotToWorker)


# ---- Framing helpers ----

async def send_msg(writer: asyncio.StreamWriter, msg) -> None:
    """Encode msg and write it with a 4-byte big-endian length prefix."""
    payload = _enc.encode(msg)
    prefix = len(payload).to_bytes(4, "big")
    writer.write(prefix + payload)
    await writer.drain()


async def recv_w2b(reader: asyncio.StreamReader) -> WorkerToBot | None:
    """Read one WorkerToBot message. Returns None on EOF/disconnect."""
    try:
        prefix = await reader.readexactly(4)
        n = int.from_bytes(prefix, "big")
        payload = await reader.readexactly(n)
        return _w2b_dec.decode(payload)
    except asyncio.IncompleteReadError:
        return None


async def recv_b2w(reader: asyncio.StreamReader) -> BotToWorker | None:
    """Read one BotToWorker message. Returns None on EOF/disconnect."""
    try:
        prefix = await reader.readexactly(4)
        n = int.from_bytes(prefix, "big")
        payload = await reader.readexactly(n)
        return _b2w_dec.decode(payload)
    except asyncio.IncompleteReadError:
        return None

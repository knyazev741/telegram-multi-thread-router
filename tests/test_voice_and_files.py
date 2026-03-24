"""Tests covering voice transcription (INPT-02) and MCP output tools (FILE-01 through FILE-04).

Phase 5 test suite — all tests use mocks, no real Telegram API or Whisper model required.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from aiogram.types import ReactionTypeEmoji

import src.sessions.voice as voice
from src.sessions.mcp_tools import create_telegram_mcp_server


# ---------------------------------------------------------------------------
# Group 1: Voice transcription (INPT-02)
# ---------------------------------------------------------------------------


def _make_segments(texts: list[str]):
    """Return mock segment objects with .text attributes."""
    return [MagicMock(text=t) for t in texts]


@pytest.fixture(autouse=True)
def reset_voice_module():
    """Reset voice module state before each test to ensure isolation."""
    original_model = voice._model
    original_semaphore = voice._semaphore
    voice._model = None
    voice._semaphore = asyncio.Semaphore(1)
    yield
    voice._model = None
    voice._semaphore = original_semaphore


async def test_transcribe_voice_returns_text():
    """INPT-02: transcribe_voice joins segment texts into a single stripped string."""
    mock_segments = _make_segments([" Hello ", " world "])
    mock_info = MagicMock()

    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.return_value = (mock_segments, mock_info)

    with patch("src.sessions.voice.WhisperModel", return_value=mock_model_instance) as mock_cls:
        result = await voice.transcribe_voice("/tmp/test.ogg")

    assert result == "Hello world"
    mock_cls.assert_called_once_with("medium", compute_type="int8", device="cpu")


async def test_transcribe_voice_lazy_loads_model():
    """INPT-02: WhisperModel is instantiated exactly once across multiple calls."""
    mock_segments = _make_segments(["Hi"])
    mock_info = MagicMock()

    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.return_value = (mock_segments, mock_info)

    with patch("src.sessions.voice.WhisperModel", return_value=mock_model_instance) as mock_cls:
        await voice.transcribe_voice("/tmp/test.ogg")
        await voice.transcribe_voice("/tmp/test.ogg")

    # WhisperModel constructor called only once — model cached after first call
    assert mock_cls.call_count == 1


async def test_transcribe_voice_semaphore_prevents_concurrent():
    """INPT-02: Semaphore(1) ensures only one transcription runs at a time."""
    # Use an event to block the first call so we can observe serialization
    block_event = asyncio.Event()
    running_count = 0
    max_concurrent = 0

    mock_info = MagicMock()

    async def slow_transcribe(*args, **kwargs):
        nonlocal running_count, max_concurrent
        running_count += 1
        max_concurrent = max(max_concurrent, running_count)
        await block_event.wait()
        running_count -= 1
        return (_make_segments(["text"]), mock_info)

    mock_model_instance = MagicMock()
    # transcribe runs in asyncio.to_thread; patch to_thread to run our coroutine directly
    with patch("src.sessions.voice.WhisperModel", return_value=mock_model_instance):
        with patch("asyncio.to_thread", side_effect=slow_transcribe):
            task1 = asyncio.create_task(voice.transcribe_voice("/tmp/test1.ogg"))
            task2 = asyncio.create_task(voice.transcribe_voice("/tmp/test2.ogg"))

            # Let both tasks start; task1 will acquire semaphore, task2 will wait
            await asyncio.sleep(0.05)

            # Only one task should be inside the semaphore at this point
            assert max_concurrent == 1

            # Release the event so both can complete
            block_event.set()
            await asyncio.gather(task1, task2)

    # After both complete, max concurrent is still 1
    assert max_concurrent == 1


# ---------------------------------------------------------------------------
# Helpers: extract tool handlers from create_telegram_mcp_server
# ---------------------------------------------------------------------------

def _get_tools(bot, chat_id=123, thread_id=456):
    """Create server and return dict of {tool_name: SdkMcpTool} for direct testing."""
    from claude_agent_sdk import SdkMcpTool  # noqa: PLC0415
    server = create_telegram_mcp_server(bot, chat_id=chat_id, thread_id=thread_id)
    # The server is a dict: {'type': 'sdk', 'name': ..., 'instance': mcp.Server}
    # Tools are SdkMcpTool dataclasses with .handler callable
    # We reconstruct them by calling create_telegram_mcp_server and capturing via tool decorator
    return server


def _make_bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_document = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


# ---------------------------------------------------------------------------
# Group 2: MCP tools (FILE-01 through FILE-04)
#
# Strategy: the @tool decorator stores the original handler on SdkMcpTool.handler.
# We re-create the server and capture the tool closures by patching create_sdk_mcp_server.
# ---------------------------------------------------------------------------

def _capture_tools(bot, chat_id=123, thread_id=456):
    """Return the raw tool handler functions by capturing them at construction time."""
    captured = {}

    original_create = None

    def capturing_create(name, tools=None, **kwargs):
        if tools:
            for t in tools:
                captured[t.name] = t.handler
        # Return a minimal dict like the real function
        return {"type": "sdk", "name": name, "instance": None}

    with patch("src.sessions.mcp_tools.create_sdk_mcp_server", side_effect=capturing_create):
        create_telegram_mcp_server(bot, chat_id=chat_id, thread_id=thread_id)

    return captured


# ---------------------------------------------------------------------------
# FILE-01: reply tool
# ---------------------------------------------------------------------------

async def test_reply_tool_sends_message():
    """FILE-01: reply tool calls bot.send_message with correct chat_id and thread_id."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    assert "reply" in tools, "reply tool not registered"
    result = await tools["reply"]({"text": "Hello"})

    bot.send_message.assert_called_once_with(
        chat_id=123,
        message_thread_id=456,
        text="Hello",
    )
    assert result["content"][0]["text"] == "Message sent"


# ---------------------------------------------------------------------------
# FILE-02: send_file tool
# ---------------------------------------------------------------------------

async def test_send_file_tool_sends_document():
    """FILE-02: send_file tool sends a document for an existing file under 50MB."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    assert "send_file" in tools, "send_file tool not registered"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        tmp.write(b"hello content")
        tmp_path = tmp.name

    try:
        result = await tools["send_file"]({"path": tmp_path})
        bot.send_document.assert_called_once()
        call_kwargs = bot.send_document.call_args.kwargs
        assert call_kwargs["chat_id"] == 123
        assert call_kwargs["message_thread_id"] == 456
    finally:
        os.unlink(tmp_path)


async def test_send_file_tool_rejects_oversized():
    """FILE-02: send_file returns error and does NOT call send_document for files > 50MB."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(b"x")
        tmp_path = tmp.name

    try:
        mock_stat = MagicMock()
        mock_stat.st_size = 51 * 1024 * 1024  # 51 MB

        with patch.object(Path, "stat", return_value=mock_stat):
            result = await tools["send_file"]({"path": tmp_path})

        text = result["content"][0]["text"]
        assert "50MB" in text or "limit" in text.lower(), f"Unexpected message: {text}"
        bot.send_document.assert_not_called()
    finally:
        os.unlink(tmp_path)


async def test_send_file_tool_rejects_missing():
    """FILE-02: send_file returns error and does NOT call send_document for missing files."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    result = await tools["send_file"]({"path": "/tmp/nonexistent_file_xyz_12345.txt"})

    text = result["content"][0]["text"]
    assert "Error" in text or "not found" in text.lower(), f"Unexpected message: {text}"
    bot.send_document.assert_not_called()


# ---------------------------------------------------------------------------
# FILE-03: react tool
# ---------------------------------------------------------------------------

async def test_react_tool_adds_reaction():
    """FILE-03: react tool calls bot.set_message_reaction with correct args."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    assert "react" in tools, "react tool not registered"
    result = await tools["react"]({"emoji": "👍", "message_id": 789})

    bot.set_message_reaction.assert_called_once()
    call_kwargs = bot.set_message_reaction.call_args.kwargs
    assert call_kwargs["chat_id"] == 123
    assert call_kwargs["message_id"] == 789
    reaction = call_kwargs["reaction"]
    assert len(reaction) == 1
    assert reaction[0].emoji == "👍"


# ---------------------------------------------------------------------------
# FILE-04: edit_message tool
# ---------------------------------------------------------------------------

async def test_edit_message_tool_edits():
    """FILE-04: edit_message tool calls bot.edit_message_text with correct args."""
    bot = _make_bot()
    tools = _capture_tools(bot, chat_id=123, thread_id=456)

    assert "edit_message" in tools, "edit_message tool not registered"
    result = await tools["edit_message"]({"text": "Updated", "message_id": 789})

    bot.edit_message_text.assert_called_once_with(
        chat_id=123,
        message_id=789,
        text="Updated",
    )
    assert result["content"][0]["text"] == "Message edited"


# ---------------------------------------------------------------------------
# Group 3: Runner MCP wiring
# ---------------------------------------------------------------------------

async def test_runner_creates_mcp_server():
    """Verify SessionRunner._run wires up create_telegram_mcp_server and mcp_servers."""
    from src.sessions.runner import SessionRunner

    source = inspect.getsource(SessionRunner._run)
    assert "create_telegram_mcp_server" in source, (
        "SessionRunner._run must call create_telegram_mcp_server"
    )
    assert "mcp_servers" in source, (
        "SessionRunner._run must pass mcp_servers to ClaudeAgentOptions"
    )

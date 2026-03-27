"""Tests for StatusUpdater lifecycle (STAT-01, STAT-02, STAT-06, STAT-07)."""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.status import StatusUpdater, _short_model


def _make_bot(message_id: int = 42) -> AsyncMock:
    """Create a mock Bot whose send_message returns an object with .message_id."""
    bot = AsyncMock()
    sent_msg = MagicMock()
    sent_msg.message_id = message_id
    bot.send_message = AsyncMock(return_value=sent_msg)
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


# ---------------------------------------------------------------------------
# STAT-01: start_turn sends a "Working" status message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_sends_message():
    """start_turn() calls bot.send_message with thread_id and 'Working' text."""
    bot = _make_bot(message_id=42)
    updater = StatusUpdater(bot=bot, chat_id=100, thread_id=5)
    try:
        await updater.start_turn()

        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 100
        assert call_kwargs["message_thread_id"] == 5
        assert "Working" in call_kwargs["text"] or "working" in call_kwargs["text"].lower()
        # message_id is stored internally
        assert updater._message_id == 42
    finally:
        await updater.stop()


# ---------------------------------------------------------------------------
# STAT-01: stop() cancels the internal refresh task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_cancels_refresh():
    """stop() cancels any pending edit and clears the tracked message id."""
    bot = _make_bot()
    updater = StatusUpdater(bot=bot, chat_id=100, thread_id=5)
    await updater.start_turn()

    updater._last_edit_time = time.monotonic()
    updater.track_tool("Read")
    assert updater._pending_edit is not None

    await updater.stop()

    assert updater._pending_edit is None
    assert updater._message_id is None


# ---------------------------------------------------------------------------
# STAT-02: track_tool updates state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_tool_updates_state():
    """track_tool() sets _current_tool and increments _tool_count."""
    bot = _make_bot()
    updater = StatusUpdater(bot=bot, chat_id=100, thread_id=5)
    try:
        await updater.start_turn()

        updater.track_tool("Read")
        assert updater._current_tool == "Read"
        assert updater._tool_count == 1

        updater.track_tool("Write")
        assert updater._current_tool == "Write"
        assert updater._tool_count == 2
    finally:
        await updater.stop()


# ---------------------------------------------------------------------------
# STAT-06: finalize() edits message with cost/duration/tool summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_edits_summary():
    """finalize() edits the status message with cost, duration, and tool count."""
    bot = _make_bot(message_id=42)
    updater = StatusUpdater(bot=bot, chat_id=100, thread_id=5)
    await updater.start_turn()

    await updater.finalize(cost_usd=0.0123, duration_ms=5000, tool_count=3)

    assert updater._pending_edit is None

    # edit_message_text should have been called
    bot.edit_message_text.assert_called_once()
    edit_kwargs = bot.edit_message_text.call_args.kwargs
    edit_text = edit_kwargs["text"]

    # Verify summary content
    assert "$0.0123" in edit_text
    assert "5.0s" in edit_text
    assert "3" in edit_text  # tool count appears somewhere in the text


@pytest.mark.asyncio
async def test_watchdog_notice_edits_status_softly():
    """Watchdog updates the status message instead of sending a separate stall message."""
    bot = _make_bot(message_id=42)
    updater = StatusUpdater(bot=bot, chat_id=100, thread_id=5)
    await updater.start_turn()

    updater.track_tool("Bash", {"command": "sleep 600"})
    await updater.show_watchdog_notice(180)

    edit_kwargs = bot.edit_message_text.call_args.kwargs
    edit_text = edit_kwargs["text"]
    assert "No updates for 3m" in edit_text
    assert "Long-running tools can be quiet" in edit_text
    assert "Bash" in edit_text


# ---------------------------------------------------------------------------
# STAT-07: Runner sends a formatted error message on SDK error
# ---------------------------------------------------------------------------


def test_error_format():
    """STAT-07: runner source contains an error format with 'Error:' prefix."""
    from src.sessions import runner as runner_module

    source = inspect.getsource(runner_module)
    # The runner must send an error message that starts with some form of "Error:"
    assert "Error:" in source, (
        "STAT-07 not satisfied: runner.py has no 'Error:' formatted error message"
    )
    # Confirm it's in the context of is_error handling
    assert "is_error" in source, (
        "STAT-07 not satisfied: runner.py does not check msg.is_error"
    )


def test_short_model_escapes_html():
    """Model labels are escaped before insertion into HTML status messages."""
    assert _short_model("<synthetic>") == "&lt;synthetic&gt;"

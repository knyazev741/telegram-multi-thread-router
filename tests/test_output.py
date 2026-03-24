"""Tests for split_message and TypingIndicator (STAT-03, STAT-04, STAT-05)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, call

import pytest

from src.bot.output import TypingIndicator, split_message


# ---------------------------------------------------------------------------
# split_message tests (STAT-03, STAT-04)
# ---------------------------------------------------------------------------


def test_short_message_unchanged():
    """Text shorter than max_len is returned as a single-element list."""
    text = "Hello, world!"
    result = split_message(text)
    assert result == [text]


def test_empty_message():
    """Empty string returns ['']."""
    result = split_message("")
    assert result == [""]


def test_exact_boundary():
    """Text of exactly max_len characters is NOT split."""
    text = "a" * 4096
    result = split_message(text)
    assert result == [text]


def test_split_at_newline():
    """Text with a newline before the boundary splits at the last newline."""
    # Build a string: 4000 'a' chars + newline + 999 'b' chars = 5000 total
    text = "a" * 4000 + "\n" + "b" * 999
    result = split_message(text)
    assert len(result) == 2
    # First chunk ends at the newline boundary (newline not included)
    assert result[0] == "a" * 4000
    assert result[1] == "b" * 999
    # Both chunks within limit
    assert all(len(chunk) <= 4096 for chunk in result)


def test_split_preserves_code_block():
    """Code-block boundary (\\n```) is preferred over a bare newline split."""
    # Construct: content before code block, \n``` marker, then more content.
    # Keep total > 4096 so a split happens.
    before_block = "x" * 3000
    code_block_end = "\n```"
    after_block = "y" * 2000  # pushes total over 4096
    text = before_block + code_block_end + after_block

    result = split_message(text)
    # First chunk should end with the \n``` boundary
    assert result[0].endswith("\n```")
    # No chunk exceeds max_len
    assert all(len(chunk) <= 4096 for chunk in result)


def test_split_multiple_chunks():
    """10 000-char string (no newlines) splits into 3+ chunks all <= 4096."""
    text = "z" * 10_000
    result = split_message(text)
    assert len(result) >= 3
    assert all(len(chunk) <= 4096 for chunk in result)
    # Reassembled text equals original
    assert "".join(result) == text


def test_hard_split_no_newline():
    """Single 5000-char string with no newlines splits at hard boundary (4096)."""
    text = "q" * 5000
    result = split_message(text)
    assert len(result) == 2
    assert result[0] == "q" * 4096
    assert result[1] == "q" * 904
    assert all(len(chunk) <= 4096 for chunk in result)


# ---------------------------------------------------------------------------
# TypingIndicator tests (STAT-05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_typing_sends_action():
    """TypingIndicator calls send_chat_action with correct parameters."""
    bot = AsyncMock()
    bot.send_chat_action = AsyncMock()

    indicator = TypingIndicator(bot=bot, chat_id=100, thread_id=5)
    await indicator.start()

    # Let the loop tick at least once (it sends immediately on first iteration)
    await asyncio.sleep(0.05)

    await indicator.stop()

    # Verify send_chat_action was called with expected keyword arguments
    bot.send_chat_action.assert_called_with(
        chat_id=100,
        action="typing",
        message_thread_id=5,
    )


@pytest.mark.asyncio
async def test_typing_stop_cancels_task():
    """After stop(), the internal asyncio task is done (cancelled)."""
    bot = AsyncMock()
    bot.send_chat_action = AsyncMock()

    indicator = TypingIndicator(bot=bot, chat_id=200, thread_id=10)
    await indicator.start()

    # Grab a reference to the task before stop clears it
    task = indicator._task
    assert task is not None

    await indicator.stop()

    # Task should be done and internal reference cleared
    assert task.done()
    assert indicator._task is None

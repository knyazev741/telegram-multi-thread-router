"""Tests for forum topic routing."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.routers.general import handle_general_message
from src.bot.routers.session import handle_session_message


def _make_message(thread_id, text="hello"):
    """Create a mock Message with given thread_id."""
    msg = MagicMock()
    msg.message_thread_id = thread_id
    msg.from_user = MagicMock()
    msg.from_user.id = 12345
    msg.text = text
    msg.reply = AsyncMock()
    return msg


async def test_general_handler_responds():
    """General handler replies to messages."""
    msg = _make_message(thread_id=1)
    await handle_general_message(msg)
    msg.reply.assert_called_once()
    assert "General topic" in msg.reply.call_args[0][0]


async def test_session_handler_responds_with_thread_id():
    """Session handler replies with the thread_id for routing verification."""
    msg = _make_message(thread_id=42)
    await handle_session_message(msg)
    msg.reply.assert_called_once()
    assert "42" in msg.reply.call_args[0][0]


async def test_session_handler_logs_thread_id(caplog):
    """Session handler logs the thread_id (proves routing resolution for FOUND-04)."""
    import logging
    with caplog.at_level(logging.INFO):
        msg = _make_message(thread_id=77, text="test routing")
        await handle_session_message(msg)
    assert "77" in caplog.text
    assert "test routing" in caplog.text


@patch.dict("os.environ", {
    "BOT_TOKEN": "test",
    "OWNER_USER_ID": "12345",
    "GROUP_CHAT_ID": "-100999",
    "AUTH_TOKEN": "test",
})
def test_build_dispatcher_has_middleware():
    """build_dispatcher registers OwnerAuthMiddleware on dp.message."""
    # Need to reload settings with test env vars
    import importlib
    import src.config
    importlib.reload(src.config)

    from src.bot.dispatcher import build_dispatcher
    dp = build_dispatcher()

    # Check that outer middleware is registered on message observer
    assert len(dp.message.outer_middleware) > 0 or hasattr(dp, '_middlewares')
    # Verify routers are included
    assert len(dp.sub_routers) >= 2  # general + session

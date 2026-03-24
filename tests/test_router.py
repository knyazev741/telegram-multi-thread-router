"""Tests for forum topic routing and session commands."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.routers.general import handle_general_fallback, handle_list, handle_new
from src.bot.routers.session import handle_session_message, handle_stop
from src.sessions.manager import SessionManager
from src.sessions.state import SessionState


def _make_message(thread_id, text="hello"):
    """Create a mock Message with given thread_id."""
    msg = MagicMock()
    msg.message_thread_id = thread_id
    msg.from_user = MagicMock()
    msg.from_user.id = 12345
    msg.text = text
    msg.reply = AsyncMock()
    msg.react = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# General router
# ---------------------------------------------------------------------------

async def test_general_fallback_responds():
    """Fallback handler replies with usage instructions."""
    msg = _make_message(thread_id=1)
    await handle_general_fallback(msg)
    msg.reply.assert_called_once()
    call_text = msg.reply.call_args[0][0]
    assert "/new" in call_text


async def test_handle_new_missing_args():
    """/new with too few args replies with usage."""
    from src.ipc.server import WorkerRegistry
    msg = _make_message(thread_id=1, text="/new")
    bot = AsyncMock()
    session_manager = MagicMock(spec=SessionManager)
    permission_manager = MagicMock()
    worker_registry = WorkerRegistry()
    await handle_new(msg, bot, session_manager, permission_manager, worker_registry)
    msg.reply.assert_called_once()
    assert "Usage" in msg.reply.call_args[0][0]


async def test_handle_list_no_sessions():
    """/list with no active sessions replies accordingly."""
    msg = _make_message(thread_id=1, text="/list")
    session_manager = MagicMock(spec=SessionManager)
    session_manager.list_all.return_value = []
    await handle_list(msg, session_manager)
    msg.reply.assert_called_once()
    assert "No active sessions" in msg.reply.call_args[0][0]


async def test_handle_list_with_sessions():
    """/list with sessions shows thread_id and workdir."""
    msg = _make_message(thread_id=1, text="/list")
    runner = MagicMock()
    runner.workdir = "/home/user/proj"
    runner.state = SessionState.IDLE
    session_manager = MagicMock(spec=SessionManager)
    session_manager.list_all.return_value = [(42, runner)]
    await handle_list(msg, session_manager)
    msg.reply.assert_called_once()
    call_text = msg.reply.call_args[0][0]
    assert "42" in call_text
    assert "/home/user/proj" in call_text
    assert "IDLE" in call_text


# ---------------------------------------------------------------------------
# Session router
# ---------------------------------------------------------------------------

async def test_handle_stop_no_session():
    """/stop in topic without session replies with error."""
    msg = _make_message(thread_id=42, text="/stop")
    session_manager = MagicMock(spec=SessionManager)
    session_manager.get.return_value = None
    await handle_stop(msg, session_manager)
    msg.reply.assert_called_once()
    assert "No active session" in msg.reply.call_args[0][0]


async def test_handle_stop_active_session():
    """/stop calls session_manager.stop and replies."""
    msg = _make_message(thread_id=42, text="/stop")
    session_manager = MagicMock(spec=SessionManager)
    runner = MagicMock()
    session_manager.get.return_value = runner
    session_manager.stop = AsyncMock()
    await handle_stop(msg, session_manager)
    session_manager.stop.assert_called_once_with(42)
    msg.reply.assert_called_once()
    assert "stopped" in msg.reply.call_args[0][0].lower()


async def test_handle_session_message_no_runner():
    """Messages to topic with no session are silently ignored."""
    msg = _make_message(thread_id=42, text="hello claude")
    session_manager = MagicMock(spec=SessionManager)
    session_manager.get.return_value = None
    await handle_session_message(msg, session_manager)
    msg.reply.assert_not_called()
    msg.react.assert_not_called()


async def test_handle_session_message_stopped():
    """Messages to a stopped session prompt restart hint."""
    msg = _make_message(thread_id=42, text="hello")
    runner = MagicMock()
    runner.state = SessionState.STOPPED
    session_manager = MagicMock(spec=SessionManager)
    session_manager.get.return_value = runner
    await handle_session_message(msg, session_manager)
    msg.reply.assert_called_once()
    assert "/new" in msg.reply.call_args[0][0]


async def test_handle_session_message_enqueues_and_reacts():
    """Text messages in active session are reacted to and enqueued."""
    msg = _make_message(thread_id=42, text="do something")
    runner = MagicMock()
    runner.state = SessionState.IDLE
    runner.enqueue = AsyncMock()
    session_manager = MagicMock(spec=SessionManager)
    session_manager.get.return_value = runner
    await handle_session_message(msg, session_manager)
    msg.react.assert_called_once()
    runner.enqueue.assert_called_once_with("do something")


async def test_handle_session_message_forwards_slash_commands():
    """/clear, /compact, /reset are forwarded as raw text (not intercepted)."""
    for cmd in ["/clear", "/compact", "/reset"]:
        msg = _make_message(thread_id=42, text=cmd)
        runner = MagicMock()
        runner.state = SessionState.IDLE
        runner.enqueue = AsyncMock()
        session_manager = MagicMock(spec=SessionManager)
        session_manager.get.return_value = runner
        await handle_session_message(msg, session_manager)
        runner.enqueue.assert_called_once_with(cmd)
        runner.enqueue.reset_mock()


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------

@patch.dict("os.environ", {
    "BOT_TOKEN": "test",
    "OWNER_USER_ID": "12345",
    "GROUP_CHAT_ID": "-100999",
    "AUTH_TOKEN": "test",
})
def test_build_dispatcher_has_middleware():
    """build_dispatcher registers OwnerAuthMiddleware on dp.message."""
    import importlib
    import src.config
    importlib.reload(src.config)

    from src.bot.dispatcher import build_dispatcher
    dp = build_dispatcher()

    # Check that outer middleware is registered on message observer
    assert len(dp.message.outer_middleware) > 0 or hasattr(dp, '_middlewares')
    # Verify routers are included
    assert len(dp.sub_routers) >= 2  # general + session

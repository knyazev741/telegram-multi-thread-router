"""Shared test fixtures."""

import os

import pytest
from unittest.mock import AsyncMock, MagicMock

# Ensure config can be imported in tests without a real .env file.
# These values are set before any module-level Settings() instantiation.
os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OWNER_USER_ID", "12345")
os.environ.setdefault("CHAT_ID", "-100999")
os.environ.setdefault("AUTH_TOKEN", "test-auth-token")
os.environ.setdefault("DEFAULT_PROVIDER", "claude")
os.environ.setdefault("ENABLE_CODEX", "false")

OWNER_ID = 12345
CHAT_ID = -100999


@pytest.fixture
def owner_message():
    """Mock Message from the owner in the correct chat."""
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = OWNER_ID
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def stranger_message():
    """Mock Message from a non-owner user."""
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 99999
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def wrong_chat_message():
    """Mock Message from owner but in wrong chat."""
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = OWNER_ID
    msg.chat = MagicMock()
    msg.chat.id = -100111  # wrong chat
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def channel_post_message():
    """Mock Message with no from_user (channel post)."""
    msg = MagicMock()
    msg.from_user = None
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def handler():
    """Mock handler function."""
    return AsyncMock(return_value="handled")


@pytest.fixture
def permission_manager():
    from src.sessions.permissions import PermissionManager
    return PermissionManager()


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def session_runner(mock_bot, permission_manager):
    from src.sessions.runner import SessionRunner
    runner = SessionRunner(
        thread_id=42,
        workdir="/tmp/test",
        bot=mock_bot,
        chat_id=CHAT_ID,
        permission_manager=permission_manager,
    )
    return runner

"""Shared test fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock


OWNER_ID = 12345
GROUP_CHAT_ID = -100999


@pytest.fixture
def owner_message():
    """Mock Message from the owner in the correct group."""
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = OWNER_ID
    msg.chat = MagicMock()
    msg.chat.id = GROUP_CHAT_ID
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def stranger_message():
    """Mock Message from a non-owner user."""
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 99999
    msg.chat = MagicMock()
    msg.chat.id = GROUP_CHAT_ID
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
    msg.chat.id = GROUP_CHAT_ID
    msg.message_thread_id = 1
    return msg


@pytest.fixture
def handler():
    """Mock handler function."""
    return AsyncMock(return_value="handled")

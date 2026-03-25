"""Tests for OwnerAuthMiddleware."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.bot.middlewares import OwnerAuthMiddleware

OWNER_ID = 12345
CHAT_ID = -100999


@pytest.fixture
def middleware():
    return OwnerAuthMiddleware(owner_id=OWNER_ID)


async def test_owner_message_passes(middleware, owner_message, handler):
    with patch("src.config.settings") as mock_settings:
        mock_settings.chat_id = CHAT_ID
        result = await middleware(handler, owner_message, {})
        handler.assert_called_once_with(owner_message, {})
        assert result == "handled"


async def test_stranger_message_dropped(middleware, stranger_message, handler):
    result = await middleware(handler, stranger_message, {})
    handler.assert_not_called()
    assert result is None


async def test_channel_post_dropped(middleware, channel_post_message, handler):
    result = await middleware(handler, channel_post_message, {})
    handler.assert_not_called()
    assert result is None


async def test_wrong_chat_dropped(middleware, wrong_chat_message, handler):
    with patch("src.config.settings") as mock_settings:
        mock_settings.chat_id = CHAT_ID
        result = await middleware(handler, wrong_chat_message, {})
        handler.assert_not_called()
        assert result is None


async def test_auto_detect_chat_id(handler):
    """When chat_id is None, first owner message auto-detects it."""
    with patch("src.config.settings") as mock_settings:
        mock_settings.chat_id = None
        middleware = OwnerAuthMiddleware(owner_id=OWNER_ID)

        msg = MagicMock()
        msg.from_user = MagicMock()
        msg.from_user.id = OWNER_ID
        msg.chat = MagicMock()
        msg.chat.id = -100999
        msg.chat.type = "supergroup"
        msg.bot = MagicMock()

        mock_dispatcher = MagicMock()
        mock_dispatcher.get.return_value = None  # no session_manager yet

        with patch("src.db.queries.set_bot_setting", new_callable=AsyncMock):
            result = await middleware(handler, msg, {"dispatcher": mock_dispatcher})

        assert mock_settings.chat_id == -100999

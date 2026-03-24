"""Tests for OwnerAuthMiddleware."""

import pytest
from src.bot.middlewares import OwnerAuthMiddleware

OWNER_ID = 12345
GROUP_CHAT_ID = -100999


@pytest.fixture
def middleware():
    return OwnerAuthMiddleware(owner_id=OWNER_ID, group_chat_id=GROUP_CHAT_ID)


async def test_owner_message_passes(middleware, owner_message, handler):
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
    result = await middleware(handler, wrong_chat_message, {})
    handler.assert_not_called()
    assert result is None

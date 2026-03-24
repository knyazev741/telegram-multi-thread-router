"""Middleware for owner-only message filtering."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message


class OwnerAuthMiddleware(BaseMiddleware):
    """Drop all messages not from the owner in the configured group chat.

    Registered as outer middleware on dp.message so it fires before
    any router filters. Silent drop — no reply to non-owner users.
    """

    def __init__(self, owner_id: int, group_chat_id: int) -> None:
        self.owner_id = owner_id
        self.group_chat_id = group_chat_id

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        # Guard: from_user can be None for channel posts
        if not event.from_user:
            return None

        # Guard: only process messages from the configured group
        if event.chat.id != self.group_chat_id:
            return None

        # Guard: only process messages from the owner
        if event.from_user.id != self.owner_id:
            return None

        return await handler(event, data)

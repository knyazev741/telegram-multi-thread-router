"""Output utilities — message splitter and typing indicator for Telegram."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger(__name__)


def escape_markdown_html(text: str) -> str:
    """Escape angle brackets so Telegram's Markdown parser does not treat them as HTML tags.

    Telegram's legacy Markdown mode still tries to parse ``<tag>`` sequences as HTML
    entities and raises ``Bad Request: can't parse entities: Unsupported start tag``
    when it encounters unknown tags.  Replacing ``<`` / ``>`` with their HTML entity
    equivalents prevents this while leaving the visual output unchanged.
    """
    return text.replace("<", "&lt;").replace(">", "&gt;")


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split text into Telegram-safe chunks of at most max_len characters.

    Splitting priority:
      1. Last occurrence of "\\n```" before max_len boundary (code-block boundary)
      2. Last newline before max_len boundary
      3. Hard split at max_len (last resort)

    Applied recursively so each piece is guaranteed <= max_len.
    """
    if len(text) <= max_len:
        return [text]

    boundary = max_len

    # Strategy 1: split at last code-block boundary before boundary
    code_boundary = text.rfind("\n```", 0, boundary)
    if code_boundary != -1:
        # Keep the closing ``` on the first chunk; second chunk starts fresh
        split_at = code_boundary + 4  # include the trailing \n```
        first = text[:split_at]
        rest = text[split_at:]
        return [first] + split_message(rest, max_len)

    # Strategy 2: split at last newline before boundary
    newline_boundary = text.rfind("\n", 0, boundary)
    if newline_boundary != -1:
        first = text[:newline_boundary]
        rest = text[newline_boundary + 1:]
        return [first] + split_message(rest, max_len)

    # Strategy 3: hard split
    first = text[:boundary]
    rest = text[boundary:]
    return [first] + split_message(rest, max_len)


class TypingIndicator:
    """Sends "typing" chat action every 4 seconds while active.

    Telegram chat actions expire after ~5s, so 4s interval keeps the indicator alive
    without flooding the API.
    """

    def __init__(self, bot: Bot, chat_id: int, thread_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background typing loop."""
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        """Loop: send typing action then sleep 4s, forever until cancelled."""
        try:
            while True:
                try:
                    await self._bot.send_chat_action(
                        chat_id=self._chat_id,
                        action="typing",
                        message_thread_id=self._thread_id,
                    )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    continue
                except Exception as e:
                    logger.warning("TypingIndicator: send_chat_action failed: %s", e)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Cancel the typing loop and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

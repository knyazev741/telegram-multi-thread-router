"""StatusUpdater — manages one editable status message per session turn."""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

logger = logging.getLogger(__name__)


class StatusUpdater:
    """Manages one editable Telegram status message per session turn.

    Lifecycle:
      start_turn()  — sends initial "Working..." message, starts 30s refresh loop
      track_tool()  — updates current tool name and increments counter
      finalize()    — edits message to cost/duration summary, schedules 30s deletion
      stop()        — cancels background task, clears message_id
    """

    def __init__(self, bot: Bot, chat_id: int, thread_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id

        self._message_id: int | None = None
        self._current_tool: str | None = None
        self._tool_count: int = 0
        self._start_time: float | None = None
        self._update_task: asyncio.Task | None = None

    async def start_turn(self) -> None:
        """Send initial status message and start 30s background refresh loop."""
        self._start_time = time.monotonic()
        self._tool_count = 0
        self._current_tool = None

        sent = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=self._thread_id,
            text="⚡ Working...",
            parse_mode="HTML",
        )
        self._message_id = sent.message_id
        self._update_task = asyncio.create_task(self._refresh_loop())

    def track_tool(self, tool_name: str) -> None:
        """Record the currently executing tool and increment the call counter."""
        self._current_tool = tool_name
        self._tool_count += 1

    async def _refresh_loop(self) -> None:
        """Background loop: edit the status message every 30 seconds."""
        try:
            while True:
                await asyncio.sleep(30)
                await self._edit_status()
        except asyncio.CancelledError:
            pass

    async def _edit_status(self) -> None:
        """Edit the status message with current progress info."""
        if self._message_id is None:
            return

        elapsed = self._format_elapsed()
        status_text = (
            f"⚡ Working...\n"
            f"📁 Tool: {self._current_tool or '—'}\n"
            f"⏱ {elapsed} | {self._tool_count} tools"
        )

        for attempt in range(2):
            try:
                await self._bot.edit_message_text(
                    text=status_text,
                    chat_id=self._chat_id,
                    message_id=self._message_id,
                    message_thread_id=self._thread_id,
                    parse_mode="HTML",
                )
                return
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(e.retry_after)
                else:
                    logger.warning("StatusUpdater: retry after flood control failed, skipping edit")
                    return
            except TelegramBadRequest:
                # Message not modified — content unchanged, ignore silently
                return
            except Exception as e:
                logger.warning("StatusUpdater: unexpected error editing status: %s", e)
                return

    def _format_elapsed(self) -> str:
        """Format elapsed time as 'Xm Ys'."""
        if self._start_time is None:
            return "0m 0s"
        elapsed_s = int(time.monotonic() - self._start_time)
        minutes = elapsed_s // 60
        seconds = elapsed_s % 60
        return f"{minutes}m {seconds}s"

    async def finalize(self, cost_usd: float | None, duration_ms: int, tool_count: int) -> None:
        """Cancel refresh loop, show cost/duration summary, schedule deletion in 30s."""
        if self._update_task is not None:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            self._update_task = None

        if self._message_id is not None:
            cost_str = f"${cost_usd:.4f}" if cost_usd is not None else "n/a"
            duration_str = f"{duration_ms / 1000:.1f}s"
            summary_text = (
                f"Done\n"
                f"Cost: {cost_str} | Duration: {duration_str} | {tool_count} tools"
            )
            try:
                await self._bot.edit_message_text(
                    text=summary_text,
                    chat_id=self._chat_id,
                    message_id=self._message_id,
                    message_thread_id=self._thread_id,
                )
            except TelegramBadRequest:
                pass
            except Exception as e:
                logger.warning("StatusUpdater: failed to finalize status message: %s", e)

            # Schedule deletion after 30 seconds
            asyncio.get_running_loop().call_later(
                30, lambda: asyncio.create_task(self._delete_status())
            )

    async def _delete_status(self) -> None:
        """Delete the status message, ignoring any errors."""
        if self._message_id is not None:
            try:
                await self._bot.delete_message(self._chat_id, self._message_id)
            except Exception:
                pass
            self._message_id = None

    async def stop(self) -> None:
        """Cancel the refresh loop and clear the tracked message id."""
        if self._update_task is not None:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            self._update_task = None
        self._message_id = None

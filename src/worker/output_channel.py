"""WorkerOutputChannel — aiogram.Bot replacement for the worker side.

Instead of calling the Telegram API directly, this class forwards all bot calls
over the TCP connection to the central bot process using IPC protocol messages.
"""

from __future__ import annotations

import asyncio
import itertools
import logging

from src.ipc.protocol import (
    AssistantTextMsg,
    McpEditMessageMsg,
    McpReactMsg,
    McpSendFileMsg,
    McpSendMessageMsg,
    send_msg,
)

logger = logging.getLogger(__name__)

_message_id_counter = itertools.count(start=1)


class MockMessage:
    """Minimal message object returned by send_message so callers can read .message_id."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class WorkerOutputChannel:
    """Mimics the subset of aiogram.Bot methods used by SessionRunner, StatusUpdater,
    TypingIndicator, and MCP tools. Sends TCP messages instead of Telegram API calls.

    Constructor args:
        writer: asyncio.StreamWriter for the active IPC connection.
        chat_id: Telegram chat ID (unused on worker side but kept for API compatibility).
    """

    def __init__(self, writer: asyncio.StreamWriter | None, chat_id: int) -> None:
        self._writer = writer
        self._chat_id = chat_id

    def set_writer(self, writer: asyncio.StreamWriter) -> None:
        """Update the TCP writer after reconnection."""
        self._writer = writer

    @property
    def is_connected(self) -> bool:
        """True if the writer is set and the transport is not closing."""
        return self._writer is not None and not self._writer.is_closing()

    async def _send(self, msg) -> None:
        """Send a TCP message, logging but not raising on broken pipe."""
        if self._writer is None or self._writer.is_closing():
            logger.warning("WorkerOutputChannel: not connected, dropping %s", type(msg).__name__)
            return
        try:
            await send_msg(self._writer, msg)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.warning("WorkerOutputChannel: send failed (%s): %s", type(msg).__name__, e)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup=None,
        **kwargs,
    ) -> MockMessage:
        """Send a text message to the topic.

        Note: reply_markup (permission keyboards) is intentionally ignored here.
        Permission prompts are handled via WorkerClient._can_use_tool which sends
        PermissionRequestMsg directly — not through this method.
        """
        await self._send(AssistantTextMsg(topic_id=message_thread_id or 0, text=text))
        msg_id = next(_message_id_counter)
        return MockMessage(message_id=msg_id)

    async def edit_message_text(
        self,
        text: str,
        chat_id: int | None = None,
        message_id: int | None = None,
        message_thread_id: int | None = None,
        **kwargs,
    ) -> None:
        """Edit a previously sent message (used by StatusUpdater)."""
        # StatusUpdater passes message_id as positional-or-keyword; we need topic_id.
        # topic_id is not passed here, so we look it up from chat context via message_thread_id.
        # StatusUpdater stores thread_id internally but does not pass it to edit_message_text.
        # We use message_thread_id if present, else fall back to 0.
        topic_id = message_thread_id or 0
        await self._send(
            McpEditMessageMsg(
                topic_id=topic_id,
                message_id=message_id or 0,
                text=text,
            )
        )

    async def delete_message(self, chat_id: int, message_id: int, **kwargs) -> None:
        """Delete a message. No-op on worker — status message deletion is best-effort."""
        # Deletion not forwarded over TCP; the bot side handles status messages
        logger.debug("WorkerOutputChannel: delete_message called (no-op on worker)")

    async def send_chat_action(
        self,
        chat_id: int,
        action: str,
        message_thread_id: int | None = None,
        **kwargs,
    ) -> None:
        """Send a chat action (typing indicator). No-op — too chatty over TCP."""
        pass  # intentionally silent

    async def send_document(
        self,
        chat_id: int,
        document,
        message_thread_id: int | None = None,
        caption: str | None = None,
        **kwargs,
    ) -> None:
        """Send a file to the topic (used by MCP send_file tool).

        Reads the file content and sends it over TCP so the bot can forward
        it to Telegram even though the file is on the worker's filesystem.
        """
        from pathlib import Path

        # Handle FSInputFile and plain path strings
        if hasattr(document, "path"):
            file_path = str(document.path)
        else:
            file_path = str(document)

        p = Path(file_path)
        file_data = p.read_bytes()
        file_name = p.name

        await self._send(
            McpSendFileMsg(
                topic_id=message_thread_id or 0,
                file_path=file_path,
                file_name=file_name,
                file_data=file_data,
                caption=caption,
            )
        )

    async def set_message_reaction(
        self,
        chat_id: int,
        message_id: int,
        reaction=None,
        **kwargs,
    ) -> None:
        """Add an emoji reaction to a message (used by MCP react tool).

        `reaction` is expected to be a list of ReactionTypeEmoji objects.
        """
        emoji = ""
        if reaction:
            first = reaction[0]
            # aiogram ReactionTypeEmoji has .emoji attribute
            if hasattr(first, "emoji"):
                emoji = first.emoji
            else:
                emoji = str(first)

        # Derive topic_id from kwargs (MCP tools don't pass message_thread_id here).
        # We store the last known thread_id is unavailable at this level; use 0 as placeholder.
        # The bot-side handler resolves the correct topic from the message_id via Telegram.
        topic_id = kwargs.get("message_thread_id", 0)
        await self._send(
            McpReactMsg(
                topic_id=topic_id,
                message_id=message_id,
                emoji=emoji,
            )
        )

    async def download(self, file: str, destination: str, **kwargs) -> None:
        """File downloads are not supported on the worker.

        Voice/photo downloads happen bot-side only and are forwarded as text to Claude.
        """
        raise NotImplementedError(
            "WorkerOutputChannel.download() is not supported: "
            "file downloads must happen on the bot side and be forwarded as text."
        )

    # MCP tools also call send_message with just chat_id + thread_id + text
    # (the reply tool). That is handled by the regular send_message above.
    # The McpSendMessageMsg type is semantically the same as AssistantTextMsg for routing;
    # we use AssistantTextMsg for all worker->bot text to keep the bot-side handler simple.

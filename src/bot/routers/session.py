"""Session topic router — messages forwarded to Claude sessions."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, ReactionTypeEmoji

from src.sessions.manager import SessionManager
from src.sessions.state import SessionState

logger = logging.getLogger(__name__)

session_router = Router(name="sessions")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
    Command("stop"),
)
async def handle_stop(message: Message, session_manager: SessionManager) -> None:
    """Stop the Claude session in this topic."""
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)
    if runner is None:
        await message.reply("No active session in this topic.")
        return

    await session_manager.stop(thread_id)
    await message.reply("Session stopped.")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
)
async def handle_session_message(message: Message, session_manager: SessionManager) -> None:
    """Forward text messages to the Claude session, including /clear /compact /reset.

    Note: /clear, /compact, /reset are NOT intercepted by Command filters — they are
    forwarded as raw text via runner.enqueue(text). This lets Claude handle them internally.
    """
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)

    if runner is None:
        return  # No active session — silently ignore

    if runner.state == SessionState.STOPPED:
        await message.reply("Session is stopped. Use /new to create a new one.")
        return

    text = message.text or ""
    if not text:
        return  # Skip non-text messages for now (Phase 5 handles voice/files)

    # React with 👀 to confirm receipt
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])
    except Exception as e:
        logger.warning("Failed to add reaction: %s", e)

    # Enqueue to session (will wait if Claude is processing current turn)
    await runner.enqueue(text)

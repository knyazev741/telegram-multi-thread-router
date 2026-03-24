"""Session topic router — messages for Claude sessions."""

import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)

session_router = Router(name="sessions")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
)
async def handle_session_message(message: Message) -> None:
    """Handle messages in session topics.

    Currently logs the thread_id for routing verification.
    Phase 2 will forward to the correct Claude session.
    """
    thread_id = message.message_thread_id
    logger.info(
        "Session topic %d message: %s",
        thread_id,
        message.text or "(no text)",
    )
    await message.reply(f"Session topic {thread_id} received your message.")

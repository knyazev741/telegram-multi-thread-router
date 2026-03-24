"""General topic router — management commands (thread_id=1)."""

import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)

general_router = Router(name="general")


@general_router.message(F.message_thread_id.in_({1, None}))
async def handle_general_message(message: Message) -> None:
    """Handle messages in the General topic.

    Currently logs and echoes. Phase 2 will add /new, /list, /stop commands.
    """
    logger.info(
        "General topic message from %d: %s",
        message.from_user.id if message.from_user else 0,
        message.text or "(no text)",
    )
    await message.reply("General topic received your message.")

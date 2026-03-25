"""General topic router — minimal fallback for thread_id=1/None.

Messages to the General topic auto-create new topics, so these handlers
rarely fire in practice. The main interface is the Orchestrator thread.
"""

import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)

general_router = Router(name="general")


@general_router.message(F.message_thread_id.in_({1, None}))
async def handle_general_fallback(message: Message) -> None:
    """Catch-all for messages in General topic — redirect to Orchestrator."""
    logger.info("General topic message (ignored): %s", message.text or "(no text)")

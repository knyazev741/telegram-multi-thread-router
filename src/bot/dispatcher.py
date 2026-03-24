"""Dispatcher factory — assembles middleware, routers, and lifecycle hooks."""

import logging

from aiogram import Dispatcher

from src.bot.middlewares import OwnerAuthMiddleware
from src.bot.routers.general import general_router
from src.bot.routers.session import session_router
from src.config import settings

logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    """Create and configure the Dispatcher with all routers and middleware."""
    dp = Dispatcher()

    # Owner auth + chat filter — outer middleware fires before any router filters
    dp.message.outer_middleware(
        OwnerAuthMiddleware(
            owner_id=settings.owner_user_id,
            group_chat_id=settings.group_chat_id,
        )
    )

    # General topic handles management commands (thread_id=1 or None)
    dp.include_router(general_router)

    # Session topics handle Claude session messages (all other thread_ids)
    dp.include_router(session_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def on_startup() -> None:
    """Called when polling starts. Initialize database here in Plan 01-03."""
    logger.info("Bot startup complete")


async def on_shutdown() -> None:
    """Called when polling stops."""
    logger.info("Bot shutting down")

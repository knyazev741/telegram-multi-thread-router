"""Dispatcher factory — assembles middleware, routers, and lifecycle hooks."""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from src.bot.middlewares import OwnerAuthMiddleware
from src.bot.routers.general import general_router
from src.bot.routers.session import session_router
from src.config import settings
from src.db.schema import init_db
from src.ipc.server import WorkerRegistry, start_ipc_server
from src.sessions.manager import SessionManager
from src.sessions.permissions import PermissionManager

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


async def on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
    """Called when polling starts. Initialize database and SessionManager."""
    await init_db()
    permission_manager = PermissionManager()
    dispatcher["permission_manager"] = permission_manager
    manager = SessionManager()
    dispatcher["session_manager"] = manager

    # Resume sessions that were active before bot stopped
    resumed = await manager.resume_all(bot, settings.group_chat_id, permission_manager)
    if resumed:
        logger.info("Resumed %d session(s) from database", resumed)

    # Start health monitoring background task
    from src.sessions.health import health_check_loop
    health_task = asyncio.create_task(
        health_check_loop(manager, bot, settings.group_chat_id)
    )
    dispatcher["health_task"] = health_task

    # Start TCP IPC server for remote worker connections
    worker_registry = WorkerRegistry()
    dispatcher["worker_registry"] = worker_registry
    ipc_server = await start_ipc_server(
        settings.ipc_host,
        settings.ipc_port,
        settings.auth_token,
        bot,
        manager,
        permission_manager,
        worker_registry,
    )
    dispatcher["ipc_server"] = ipc_server

    logger.info("Bot startup complete — SessionManager initialized, health monitoring active")


async def on_shutdown(dispatcher: Dispatcher) -> None:
    """Called when polling stops. Cancel health task and stop all active sessions."""
    # Cancel health check
    health_task: asyncio.Task | None = dispatcher.get("health_task")
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass

    # Close IPC server before stopping sessions
    ipc_server: asyncio.Server | None = dispatcher.get("ipc_server")
    if ipc_server:
        ipc_server.close()
        await ipc_server.wait_closed()

    # Stop all active sessions
    manager: SessionManager | None = dispatcher.get("session_manager")
    if manager:
        for thread_id, runner in manager.list_all():
            try:
                await runner.stop()
            except Exception as e:
                logger.error("Error stopping session %d: %s", thread_id, e)

    logger.info("Bot shutting down — all sessions stopped")

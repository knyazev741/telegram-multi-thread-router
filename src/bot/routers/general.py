"""General topic router — management commands (thread_id=1)."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.methods import CreateForumTopic
from aiogram.types import Message

from src.config import settings
from src.db.queries import insert_session, insert_topic
from src.ipc.server import WorkerRegistry
from src.sessions.manager import SessionManager
from src.sessions.permissions import PermissionManager
from src.sessions.remote import RemoteSession

logger = logging.getLogger(__name__)

general_router = Router(name="general")


@general_router.message(F.message_thread_id.in_({1, None}), Command("new"))
async def handle_new(
    message: Message,
    bot: Bot,
    session_manager: SessionManager,
    permission_manager: PermissionManager,
    worker_registry: WorkerRegistry,
) -> None:
    """Create a new Claude session with a dedicated forum topic.

    Usage: /new <name> <workdir> [server-name]
    """
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        await message.reply("Usage: /new <name> <workdir> [server-name]")
        return

    name = args[1]
    workdir = args[2]
    server_name = args[3] if len(args) > 3 else "local"

    # Validate server connection for remote sessions
    if server_name != "local":
        if not worker_registry.is_connected(server_name):
            await message.reply(f"Server '{server_name}' is not connected.")
            return

    # Create forum topic
    topic = await bot(CreateForumTopic(
        chat_id=settings.group_chat_id,
        name=name,
    ))
    thread_id = topic.message_thread_id

    # Persist to DB
    model = "opus"
    await insert_topic(thread_id, name)
    await insert_session(thread_id, workdir, model=model, server=server_name)

    # Start session (local or remote)
    if server_name != "local":
        await session_manager.create_remote(
            thread_id=thread_id,
            workdir=workdir,
            worker_id=server_name,
            worker_registry=worker_registry,
            model=model,
        )
    else:
        await session_manager.create(
            thread_id=thread_id,
            workdir=workdir,
            bot=bot,
            chat_id=settings.group_chat_id,
            permission_manager=permission_manager,
            model=model,
        )

    await bot.send_message(
        chat_id=settings.group_chat_id,
        message_thread_id=thread_id,
        text=(
            f"✅ Session <b>{name}</b> started\n"
            f"Model: <code>{model}</code>\n"
            f"Thread: <code>{thread_id}</code>\n"
            f"Server: {server_name}\n"
            f"Workdir: <code>{workdir}</code>"
        ),
        parse_mode="HTML",
    )
    await message.reply(f"Session '{name}' created. Thread: <code>{thread_id}</code>", parse_mode="HTML")


@general_router.message(F.message_thread_id.in_({1, None}), Command("list"))
async def handle_list(message: Message, session_manager: SessionManager) -> None:
    """List all active sessions with server info."""
    sessions = session_manager.list_all()
    if not sessions:
        await message.reply("No active sessions.")
        return

    lines = []
    for thread_id, runner in sessions:
        if isinstance(runner, RemoteSession):
            server = runner.worker_id
            status = "(connected)" if runner.is_alive else "(disconnected)"
        else:
            server = "local"
            status = ""

        server_info = f"on <i>{server}</i> {status}".strip()
        auto = " 🤖auto" if getattr(runner, "auto_mode", False) else ""
        lines.append(
            f"- <b>{thread_id}</b>: {runner.workdir} [{runner.state.name}] {server_info}{auto}"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")


@general_router.message(F.message_thread_id.in_({1, None}), Command("restart"))
async def handle_restart(
    message: Message,
    bot: Bot,
    session_manager: SessionManager,
) -> None:
    """Restart the bot process to pick up new code. Sessions resume automatically."""
    import os
    import sys

    await message.reply("🔄 Restarting bot... Sessions will resume automatically.")
    logger.info("Restart requested by owner — stopping sessions before execv")

    # Stop all sessions BEFORE execv to avoid orphaned Claude subprocesses
    await _graceful_stop_all(session_manager)

    # Give Telegram time to send the reply
    import asyncio
    await asyncio.sleep(1)

    # Replace current process with a fresh one (same args)
    os.execv(sys.executable, [sys.executable, "-m", "src"])


async def _graceful_stop_all(session_manager: SessionManager) -> None:
    """Stop all sessions gracefully, marking them as idle for resume."""
    from src.db.queries import update_session_state

    for thread_id, runner in session_manager.list_all():
        try:
            await runner.stop()
            # Override to idle so resume_all picks them up on next startup
            await update_session_state(thread_id, "idle")
        except Exception as e:
            logger.error("Error stopping session %d before restart: %s", thread_id, e)


@general_router.message(F.message_thread_id.in_({1, None}))
async def handle_general_fallback(message: Message) -> None:
    """Catch-all for unrecognized messages in General topic."""
    logger.info("General topic message: %s", message.text or "(no text)")
    await message.reply(
        "Use /new <name> <workdir> [server-name] to create a session,\n"
        "/list to see active sessions,\n"
        "/close inside a topic to close the session and delete the topic."
    )

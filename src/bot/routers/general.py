"""General topic router — management commands (thread_id=1)."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.methods import CreateForumTopic
from aiogram.types import Message

from src.config import settings
from src.db.queries import insert_session, insert_topic
from src.sessions.manager import SessionManager

logger = logging.getLogger(__name__)

general_router = Router(name="general")


@general_router.message(F.message_thread_id.in_({1, None}), Command("new"))
async def handle_new(message: Message, bot: Bot, session_manager: SessionManager) -> None:
    """Create a new Claude session with a dedicated forum topic.

    Usage: /new <name> <workdir>
    """
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Usage: /new <name> <workdir>")
        return

    _, name, workdir = args

    # Create forum topic
    topic = await bot(CreateForumTopic(
        chat_id=settings.group_chat_id,
        name=name,
    ))
    thread_id = topic.message_thread_id

    # Persist to DB
    await insert_topic(thread_id, name)
    await insert_session(thread_id, workdir)

    # Start session runner
    await session_manager.create(
        thread_id=thread_id,
        workdir=workdir,
        bot=bot,
        chat_id=settings.group_chat_id,
    )

    await bot.send_message(
        chat_id=settings.group_chat_id,
        message_thread_id=thread_id,
        text=f"Session '{name}' started. Working directory: {workdir}",
    )
    await message.reply(f"Session '{name}' created in new topic.")


@general_router.message(F.message_thread_id.in_({1, None}), Command("list"))
async def handle_list(message: Message, session_manager: SessionManager) -> None:
    """List all active sessions."""
    sessions = session_manager.list_all()
    if not sessions:
        await message.reply("No active sessions.")
        return

    lines = []
    for thread_id, runner in sessions:
        lines.append(
            f"- <b>{thread_id}</b>: {runner.workdir} [{runner.state.name}]"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")


@general_router.message(F.message_thread_id.in_({1, None}))
async def handle_general_fallback(message: Message) -> None:
    """Catch-all for unrecognized messages in General topic."""
    logger.info("General topic message: %s", message.text or "(no text)")
    await message.reply(
        "Use /new <name> <workdir> to create a session, or /list to see active sessions."
    )

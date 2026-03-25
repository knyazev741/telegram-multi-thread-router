"""Orchestrator — auto-created Claude Code session (Sonnet) that manages other sessions."""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.methods import CreateForumTopic
from claude_agent_sdk import create_sdk_mcp_server, tool

from src.config import settings
from src.db.queries import insert_session, insert_topic, get_all_active_sessions
from src.sessions.manager import SessionManager
from src.sessions.permissions import PermissionManager

logger = logging.getLogger(__name__)

ORCHESTRATOR_TOPIC_NAME = "🎯 Orchestrator"
ORCHESTRATOR_SYSTEM_PROMPT = """You are a full Claude Code session with additional session management capabilities.

You have all standard Claude Code tools (Bash, Read, Write, Edit, Grep, Glob, etc.) plus orchestrator MCP tools:
- create_session(name, workdir, server): Create a new Claude Code session in a new Telegram thread. Server defaults to "local", or specify a remote worker name.
- list_sessions(): List all active sessions with status
- stop_session(thread_id): Stop a session

You can SSH into servers, browse filesystems, run commands — everything a normal Claude Code session can do.
When the user asks to work on a project on a specific server, use create_session to spawn a dedicated session for it.
"""

WELCOME_MESSAGE = """\
<b>🎯 Telegram Multi-Thread Router</b>

Claude Code sessions in Telegram — each thread is an isolated workspace.

<b>Commands (work from any thread):</b>
<code>/new &lt;name&gt; &lt;workdir&gt; [server]</code> — create a new session
<code>/list</code> — list active sessions
<code>/restart</code> — restart bot (sessions resume)
<code>/stop</code> — interrupt current turn
<code>/close</code> — stop session + delete thread

<b>Input types:</b>
💬 Text — forwarded to Claude
🎤 Voice — transcribed via Whisper, then forwarded
📷 Photo / 📎 Files — downloaded to workdir, path sent to Claude

<b>Orchestrator (this thread):</b>
I can create, manage, and stop sessions for you. Just ask in natural language!
"""


def create_orchestrator_mcp_server(
    bot: Bot,
    chat_id: int,
    session_manager: SessionManager,
    permission_manager: PermissionManager,
    worker_registry,
):
    """Create MCP server with session management tools for the orchestrator."""

    @tool(
        "create_session",
        "Create a new Claude Code session in a new Telegram thread. Returns the thread ID.",
        {"name": str, "workdir": str, "server": str},
    )
    async def create_session(args: dict) -> dict:
        name = args["name"]
        workdir = args["workdir"]
        server_name = args.get("server", "local")

        try:
            # Validate remote server
            if server_name != "local" and not worker_registry.is_connected(server_name):
                return {"content": [{"type": "text", "text": f"Error: Server '{server_name}' not connected"}]}

            # Create forum topic
            topic = await bot(CreateForumTopic(chat_id=chat_id, name=name))
            thread_id = topic.message_thread_id

            # Persist
            await insert_topic(thread_id, name)
            await insert_session(thread_id, workdir, server=server_name)

            # Start session
            if server_name != "local":
                await session_manager.create_remote(
                    thread_id=thread_id,
                    workdir=workdir,
                    worker_id=server_name,
                    worker_registry=worker_registry,
                )
            else:
                await session_manager.create(
                    thread_id=thread_id,
                    workdir=workdir,
                    bot=bot,
                    chat_id=chat_id,
                    permission_manager=permission_manager,
                )

            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=f"✅ Session <b>{name}</b> started\nThread: <code>{thread_id}</code>\nServer: {server_name}\nWorkdir: <code>{workdir}</code>",
                parse_mode="HTML",
            )

            return {"content": [{"type": "text", "text": f"Session '{name}' created. Thread ID: {thread_id}, server: {server_name}"}]}
        except Exception as e:
            logger.error("create_session error: %s", e)
            return {"content": [{"type": "text", "text": f"Error creating session: {e}"}]}

    @tool(
        "list_sessions",
        "List all active Claude Code sessions with their status, server, and working directory",
        {},
    )
    async def list_sessions(args: dict) -> dict:
        from src.sessions.remote import RemoteSession

        sessions = session_manager.list_all()
        if not sessions:
            return {"content": [{"type": "text", "text": "No active sessions."}]}

        lines = []
        for thread_id, runner in sessions:
            server = runner.worker_id if isinstance(runner, RemoteSession) else "local"
            lines.append(f"- Thread {thread_id}: {runner.workdir} [{runner.state.name}] on {server}")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "stop_session",
        "Stop an active Claude Code session by its thread ID",
        {"thread_id": int},
    )
    async def stop_session(args: dict) -> dict:
        thread_id = args["thread_id"]
        try:
            runner = session_manager.get(thread_id)
            if not runner:
                return {"content": [{"type": "text", "text": f"No session found for thread {thread_id}"}]}

            await session_manager.stop(thread_id)
            from src.db.queries import update_session_state
            await update_session_state(thread_id, "stopped")

            return {"content": [{"type": "text", "text": f"Session {thread_id} stopped."}]}
        except Exception as e:
            logger.error("stop_session error: %s", e)
            return {"content": [{"type": "text", "text": f"Error: {e}"}]}

    @tool(
        "auto_mode",
        "Toggle auto-mode for a session — auto-approves all permissions without prompting the user. "
        "Pass enable=true to enable, enable=false to disable.",
        {"thread_id": int, "enable": bool},
    )
    async def auto_mode(args: dict) -> dict:
        thread_id = args["thread_id"]
        enable = args["enable"]
        runner = session_manager.get(thread_id)
        if not runner:
            return {"content": [{"type": "text", "text": f"No session found for thread {thread_id}"}]}

        runner.auto_mode = enable
        from src.db.queries import update_auto_mode
        await update_auto_mode(thread_id, enable)
        status = "enabled" if enable else "disabled"

        try:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=f"🤖 Auto-mode {status}",
            )
        except Exception:
            pass

        return {"content": [{"type": "text", "text": f"Auto-mode {status} for thread {thread_id}"}]}

    return create_sdk_mcp_server(
        "orchestrator",
        tools=[create_session, list_sessions, stop_session, auto_mode],
    )


async def ensure_orchestrator(
    bot: Bot,
    chat_id: int,
    session_manager: SessionManager,
    permission_manager: PermissionManager,
    worker_registry,
) -> int | None:
    """Ensure the orchestrator thread and session exist. Returns thread_id or None on error."""
    from src.db.queries import get_orchestrator_topic, insert_topic, insert_session

    # Check if orchestrator topic already exists in DB
    orch = await get_orchestrator_topic()
    if orch:
        thread_id = orch["thread_id"]
        logger.info("Orchestrator topic exists: thread=%d", thread_id)
    else:
        # Create new orchestrator topic
        try:
            topic = await bot(CreateForumTopic(chat_id=chat_id, name=ORCHESTRATOR_TOPIC_NAME))
            thread_id = topic.message_thread_id
            await insert_topic(thread_id, ORCHESTRATOR_TOPIC_NAME, is_orchestrator=True)
            await insert_session(thread_id, str(Path.home()), server="local")
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=WELCOME_MESSAGE,
                parse_mode="HTML",
            )
            logger.info("Created orchestrator topic: thread=%d", thread_id)
        except Exception as e:
            logger.error("Failed to create orchestrator topic: %s", e)
            return None

    # Start orchestrator session if not already running
    if session_manager.get(thread_id):
        logger.info("Orchestrator session already running")
        return thread_id

    try:
        from src.sessions.runner import SessionRunner
        from src.db.queries import get_session_by_thread

        # Get existing session_id for resume (if orchestrator was running before)
        existing = await get_session_by_thread(thread_id)
        session_id = existing["session_id"] if existing else None

        # Create orchestrator with management MCP tools
        orch_mcp = create_orchestrator_mcp_server(
            bot, chat_id, session_manager, permission_manager, worker_registry,
        )

        # Build runner manually so we can set _extra_mcp BEFORE start()
        runner = SessionRunner(
            thread_id=thread_id,
            workdir=str(Path.home()),
            bot=bot,
            chat_id=chat_id,
            permission_manager=permission_manager,
            model="sonnet",
            session_id=session_id,
        )
        runner._extra_mcp = {"orchestrator": orch_mcp}
        runner._system_prompt_override = ORCHESTRATOR_SYSTEM_PROMPT

        # Register in session manager and start
        async with session_manager._lock:
            session_manager._sessions[thread_id] = runner
        await runner.start()

        # Send welcome on first creation, short status on restart
        if not orch:
            # First time — full welcome already sent above
            pass
        else:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text="🎯 Orchestrator restarted and ready.",
            )

        logger.info("Orchestrator session started in thread %d", thread_id)
        return thread_id
    except Exception as e:
        logger.error("Failed to start orchestrator session: %s", e)
        return None

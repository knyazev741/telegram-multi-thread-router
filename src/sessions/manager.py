"""SessionManager — maps thread_id to SessionRunner or RemoteSession instances."""

import asyncio
import logging
from typing import Optional

from aiogram import Bot

from src.sessions.permissions import PermissionManager
from src.sessions.remote import RemoteSession
from src.sessions.runner import SessionRunner

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages the lifecycle of all active SessionRunner and RemoteSession instances."""

    def __init__(self) -> None:
        self._sessions: dict[int, SessionRunner | RemoteSession] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
        permission_manager: PermissionManager,
        session_id: str | None = None,
        model: str | None = None,
    ) -> SessionRunner:
        """Create and start a new SessionRunner for the given thread_id.

        Raises ValueError if a session for that thread already exists.
        """
        async with self._lock:
            if thread_id in self._sessions:
                raise ValueError(f"Session for topic {thread_id} already exists")
            runner = SessionRunner(
                thread_id=thread_id,
                workdir=workdir,
                bot=bot,
                chat_id=chat_id,
                permission_manager=permission_manager,
                session_id=session_id,
                model=model,
            )
            self._sessions[thread_id] = runner
            await runner.start()
            return runner

    async def create_remote(
        self,
        thread_id: int,
        workdir: str,
        worker_id: str,
        worker_registry,
        session_id: str | None = None,
        model: str | None = None,
    ) -> RemoteSession:
        """Create a RemoteSession proxy and send StartSessionMsg to the worker.

        Raises ValueError if a session for that thread already exists.
        """
        async with self._lock:
            if thread_id in self._sessions:
                raise ValueError(f"Session for topic {thread_id} already exists")
            session = RemoteSession(
                thread_id=thread_id,
                workdir=workdir,
                worker_id=worker_id,
                worker_registry=worker_registry,
                session_id=session_id,
            )
            self._sessions[thread_id] = session
            await session.start()
            return session

    def get(self, thread_id: int) -> Optional[SessionRunner | RemoteSession]:
        """Return the runner/session for thread_id, or None if not found."""
        return self._sessions.get(thread_id)

    async def stop(self, thread_id: int) -> None:
        """Stop and remove the runner for thread_id. No-op if not found."""
        async with self._lock:
            runner = self._sessions.pop(thread_id, None)
            if runner:
                await runner.stop()

    def list_all(self) -> list[tuple[int, SessionRunner | RemoteSession]]:
        """Return all (thread_id, runner) pairs."""
        return list(self._sessions.items())

    def get_server(self, thread_id: int) -> str:
        """Return the server name for a session: worker_id for remote, 'local' for local."""
        runner = self._sessions.get(thread_id)
        if runner is None:
            return "local"
        return runner.worker_id if isinstance(runner, RemoteSession) else "local"

    async def resume_all(self, bot: Bot, chat_id: int, permission_manager: PermissionManager) -> int:
        """Resume all local sessions that were active when bot last stopped.

        Remote sessions are skipped — they re-register when the worker reconnects.
        Returns number of successfully resumed sessions.
        """
        from src.db.queries import get_resumable_sessions, update_session_state

        rows = await get_resumable_sessions()
        resumed = 0

        for row in rows:
            thread_id = row["thread_id"]
            session_id = row["session_id"]
            workdir = row["workdir"]
            model = row.get("model")
            server = row.get("server", "local")

            # Skip remote sessions — worker reconnect handles re-registration
            if server != "local":
                logger.info(
                    "Skipping remote session topic %d (server=%s) on resume", thread_id, server
                )
                continue

            try:
                await self.create(
                    thread_id=thread_id,
                    workdir=workdir,
                    bot=bot,
                    chat_id=chat_id,
                    permission_manager=permission_manager,
                    session_id=session_id,
                    model=model,
                )
                await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text="Session resumed after bot restart.",
                )
                resumed += 1
                logger.info("Resumed session %s in topic %d", session_id, thread_id)
            except Exception as e:
                logger.error(
                    "Failed to resume session %s in topic %d: %s", session_id, thread_id, e
                )
                # Mark as stopped in DB so it doesn't retry on next restart
                try:
                    await update_session_state(thread_id, "stopped")
                except Exception:
                    pass

        return resumed

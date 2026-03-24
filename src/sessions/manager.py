"""SessionManager — maps thread_id to SessionRunner instances."""

import asyncio
import logging
from typing import Optional

from aiogram import Bot

from src.sessions.runner import SessionRunner

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages the lifecycle of all active SessionRunner instances."""

    def __init__(self) -> None:
        self._sessions: dict[int, SessionRunner] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
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
                session_id=session_id,
                model=model,
            )
            self._sessions[thread_id] = runner
            await runner.start()
            return runner

    def get(self, thread_id: int) -> Optional[SessionRunner]:
        """Return the runner for thread_id, or None if not found."""
        return self._sessions.get(thread_id)

    async def stop(self, thread_id: int) -> None:
        """Stop and remove the runner for thread_id. No-op if not found."""
        async with self._lock:
            runner = self._sessions.pop(thread_id, None)
            if runner:
                await runner.stop()

    def list_all(self) -> list[tuple[int, SessionRunner]]:
        """Return all (thread_id, runner) pairs."""
        return list(self._sessions.items())

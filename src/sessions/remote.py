"""RemoteSession — bot-side proxy for a Claude session running on a remote worker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.ipc.protocol import StartSessionMsg, StopSessionMsg, UserMessageMsg
from src.sessions.state import SessionState

if TYPE_CHECKING:
    from src.ipc.server import WorkerRegistry


class RemoteSession:
    """Proxy for a session that runs on a remote worker process.

    Mimics the SessionRunner interface (enqueue, stop, state, is_alive, workdir,
    thread_id, session_id) so SessionManager can store both types transparently.
    """

    def __init__(
        self,
        thread_id: int,
        workdir: str,
        worker_id: str,
        worker_registry: WorkerRegistry,
        session_id: str | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.workdir = workdir
        self.worker_id = worker_id
        self.session_id = session_id
        self.state: SessionState = SessionState.IDLE
        self.auto_mode: bool = False
        self._registry = worker_registry

    @property
    def is_alive(self) -> bool:
        """True if the remote worker is currently connected."""
        return self._registry.is_connected(self.worker_id)

    async def start(self) -> None:
        """Send StartSessionMsg to the worker to begin the Claude session."""
        await self._registry.send_to(
            self.worker_id,
            StartSessionMsg(
                topic_id=self.thread_id,
                cwd=self.workdir,
                session_id=self.session_id,
            ),
        )

    async def enqueue(self, text: str, reply_to_message_id: int | None = None) -> None:
        """Forward a user message to the worker."""
        await self._registry.send_to(
            self.worker_id,
            UserMessageMsg(topic_id=self.thread_id, text=text),
        )

    async def interrupt(self) -> bool:
        """Interrupt not supported for remote sessions yet."""
        return False

    async def stop(self) -> None:
        """Instruct the worker to stop this session and mark state locally."""
        await self._registry.send_to(
            self.worker_id,
            StopSessionMsg(topic_id=self.thread_id),
        )
        self.state = SessionState.STOPPED

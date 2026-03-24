"""WorkerClient — TCP connection loop, session management, and permission bridge.

Connects to the central bot IPC server, authenticates with AUTH_TOKEN,
and manages local Claude sessions via SessionRunner instances.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from src.ipc.protocol import (
    AuthMsg,
    AuthOkMsg,
    PermissionRequestMsg,
    SessionStartedMsg,
    SessionEndedMsg,
    StartSessionMsg,
    StopSessionMsg,
    UserMessageMsg,
    PermissionResponseMsg,
    SlashCommandMsg,
    send_msg,
    recv_b2w,
)
from src.sessions.runner import SessionRunner
from src.sessions.permissions import PermissionManager
from src.sessions.state import SessionState
from src.worker.output_channel import WorkerOutputChannel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WorkerClient:
    """Manages the TCP connection to the bot and local Claude sessions.

    Lifecycle:
      run()  — main reconnect loop with exponential backoff; call with asyncio.run()
    """

    def __init__(
        self,
        host: str,
        port: int,
        auth_token: str,
        worker_id: str,
    ) -> None:
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._worker_id = worker_id

        self._sessions: dict[int, SessionRunner] = {}
        self._output_channel: WorkerOutputChannel | None = None
        self._writer: asyncio.StreamWriter | None = None
        # Pending permission request futures: request_id -> Future[str]
        self._permission_futures: dict[str, asyncio.Future] = {}

    async def run(self) -> None:
        """Main reconnect loop with exponential backoff (1s → 2s → 4s → … → 60s max)."""
        delay = 1.0
        while True:
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                self._writer = writer

                # Authentication handshake
                await send_msg(writer, AuthMsg(token=self._auth_token, worker_id=self._worker_id))
                response = await recv_b2w(reader)
                if not isinstance(response, AuthOkMsg):
                    logger.error(
                        "Worker %s: auth rejected by bot: %s", self._worker_id, response
                    )
                    writer.close()
                    await writer.wait_closed()
                    break  # permanent auth failure — do not retry

                delay = 1.0  # reset backoff on successful connection
                logger.info(
                    "Worker %s: connected to bot IPC at %s:%d",
                    self._worker_id,
                    self._host,
                    self._port,
                )

                # Create or update the shared output channel
                if self._output_channel is None:
                    self._output_channel = WorkerOutputChannel(writer, chat_id=0)
                else:
                    self._output_channel.set_writer(writer)

                # Re-register existing sessions so the bot knows we still have them
                for topic_id, runner in list(self._sessions.items()):
                    if runner.session_id:
                        try:
                            await send_msg(
                                writer,
                                SessionStartedMsg(
                                    topic_id=topic_id,
                                    session_id=runner.session_id,
                                ),
                            )
                        except OSError as e:
                            logger.warning(
                                "Worker %s: failed to re-register topic %d: %s",
                                self._worker_id,
                                topic_id,
                                e,
                            )

                # Run the receive loop until EOF or error
                await self._receive_loop(reader)

            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
                logger.warning(
                    "Worker %s: IPC connect failed: %s — retrying in %.0fs",
                    self._worker_id,
                    e,
                    delay,
                )
            finally:
                self._on_disconnected()

            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)

    async def _receive_loop(self, reader: asyncio.StreamReader) -> None:
        """Process messages from the bot until EOF."""
        while True:
            msg = await recv_b2w(reader)
            if msg is None:
                logger.info("Worker %s: IPC connection closed by bot (EOF)", self._worker_id)
                break

            if isinstance(msg, StartSessionMsg):
                await self._start_session(msg)
            elif isinstance(msg, StopSessionMsg):
                await self._stop_session(msg.topic_id)
            elif isinstance(msg, UserMessageMsg):
                runner = self._sessions.get(msg.topic_id)
                if runner:
                    await runner.enqueue(msg.text)
                else:
                    logger.warning(
                        "Worker %s: UserMessage for unknown topic %d",
                        self._worker_id,
                        msg.topic_id,
                    )
            elif isinstance(msg, PermissionResponseMsg):
                self._resolve_permission(msg.request_id, msg.action)
            elif isinstance(msg, SlashCommandMsg):
                runner = self._sessions.get(msg.topic_id)
                if runner:
                    await runner.enqueue(msg.command)
                else:
                    logger.warning(
                        "Worker %s: SlashCommand for unknown topic %d",
                        self._worker_id,
                        msg.topic_id,
                    )
            else:
                logger.warning("Worker %s: unknown message type: %s", self._worker_id, type(msg))

    async def _start_session(self, msg: StartSessionMsg) -> None:
        """Create and start a new SessionRunner for the given topic."""
        topic_id = msg.topic_id

        if topic_id in self._sessions:
            runner = self._sessions[topic_id]
            if runner.is_alive:
                logger.warning(
                    "Worker %s: StartSession for topic %d but session already running",
                    self._worker_id,
                    topic_id,
                )
                return
            # Dead session — replace it
            del self._sessions[topic_id]

        if self._output_channel is None:
            logger.error(
                "Worker %s: cannot start session — no output channel yet", self._worker_id
            )
            return

        perm_mgr = PermissionManager()

        runner = SessionRunner(
            thread_id=topic_id,
            workdir=msg.cwd,
            bot=self._output_channel,
            chat_id=0,  # unused on worker side
            permission_manager=perm_mgr,
            session_id=msg.session_id,
            model=msg.model,
        )

        # Replace _can_use_tool with our TCP permission bridge
        # We bind the bridge as a closure capturing runner, perm_mgr, and topic_id
        original_allowed_tools = runner._allowed_tools

        async def _worker_can_use_tool(tool_name: str, input_data: dict, context) -> PermissionResultAllow | PermissionResultDeny:
            # Auto-approve pre-approved tools (mirrors runner PERM-07)
            if tool_name in original_allowed_tools:
                return PermissionResultAllow(updated_input=input_data)

            # Transition state
            prev_state = runner.state
            runner.state = SessionState.WAITING_PERMISSION

            # Create a local future and send permission request over TCP
            request_id, future = perm_mgr.create_request()
            self._permission_futures[request_id] = future

            try:
                await self._output_channel._send(
                    PermissionRequestMsg(
                        topic_id=topic_id,
                        request_id=request_id,
                        tool_name=tool_name,
                        input_data=input_data,
                    )
                )

                action = await asyncio.wait_for(future, timeout=300.0)

            except asyncio.TimeoutError:
                perm_mgr.expire(request_id)
                self._permission_futures.pop(request_id, None)
                runner.state = prev_state
                return PermissionResultDeny(message="Timed out — user did not respond within 5 minutes")

            except asyncio.CancelledError:
                perm_mgr.expire(request_id)
                self._permission_futures.pop(request_id, None)
                runner.state = prev_state
                raise

            finally:
                runner.state = prev_state
                self._permission_futures.pop(request_id, None)

            if action == "allow":
                return PermissionResultAllow(updated_input=input_data)
            elif action == "always":
                original_allowed_tools.add(tool_name)
                return PermissionResultAllow(updated_input=input_data)
            else:  # "deny"
                return PermissionResultDeny(message="Denied by user")

        # Monkey-patch the runner's _can_use_tool with the TCP bridge
        runner._can_use_tool = _worker_can_use_tool  # type: ignore[method-assign]

        self._sessions[topic_id] = runner
        await runner.start()
        logger.info(
            "Worker %s: started session for topic %d (cwd=%s)",
            self._worker_id,
            topic_id,
            msg.cwd,
        )

    def _resolve_permission(self, request_id: str, action: str) -> None:
        """Resolve a pending permission future from a bot response."""
        future = self._permission_futures.pop(request_id, None)
        if future is None:
            logger.warning(
                "Worker %s: PermissionResponse for unknown request_id %s",
                self._worker_id,
                request_id,
            )
            return
        if not future.done():
            future.set_result(action)
        else:
            logger.warning(
                "Worker %s: PermissionResponse for already-resolved request_id %s",
                self._worker_id,
                request_id,
            )

    def _on_disconnected(self) -> None:
        """Called when the TCP connection drops. Cancel all pending permission futures."""
        if self._permission_futures:
            logger.info(
                "Worker %s: TCP disconnect — cancelling %d pending permission futures",
                self._worker_id,
                len(self._permission_futures),
            )
            for future in self._permission_futures.values():
                if not future.done():
                    # Resolve with "deny" so _can_use_tool unblocks cleanly
                    future.set_result("deny")
            self._permission_futures.clear()

        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None

        logger.info("Worker %s: disconnected from bot IPC", self._worker_id)

    async def _stop_session(self, topic_id: int) -> None:
        """Stop and remove a running session."""
        runner = self._sessions.pop(topic_id, None)
        if runner is None:
            logger.warning(
                "Worker %s: StopSession for unknown topic %d", self._worker_id, topic_id
            )
            return
        await runner.stop()
        logger.info("Worker %s: stopped session for topic %d", self._worker_id, topic_id)

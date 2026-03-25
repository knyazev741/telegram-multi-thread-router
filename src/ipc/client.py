"""IPC Worker Client — connects to bot server and runs Claude sessions on remote machines.

Usage:
    python -m src.ipc.client --host <bot-server-ip> --port 9800 --token <auth-token> --worker-id <name>

The worker connects to the bot's TCP IPC server, authenticates, and waits for
StartSessionMsg commands. Each session spawns a SessionRunner that runs Claude SDK
locally on this machine, with all output proxied back to the bot via IPC.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from src.ipc.protocol import (
    AuthMsg,
    AuthOkMsg,
    AuthFailMsg,
    AssistantTextMsg,
    PermissionRequestMsg,
    PermissionResponseMsg,
    SessionEndedMsg,
    SessionStartedMsg,
    StartSessionMsg,
    StatusUpdateMsg,
    StopSessionMsg,
    UserMessageMsg,
    send_msg,
    recv_b2w,
)

logger = logging.getLogger(__name__)

# Try to import Claude SDK — worker needs it
try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        PermissionResultAllow,
        PermissionResultDeny,
        HookMatcher,
    )
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


async def _dummy_pretool_hook(input_data, tool_use_id, context):
    return {"continue_": True}


def _build_system_prompt(workdir: str) -> str:
    """Read CLAUDE.md from workdir if present."""
    claude_md = Path(workdir) / "CLAUDE.md"
    base = ""
    try:
        base = claude_md.read_text()
    except (FileNotFoundError, PermissionError):
        pass
    return f"{base}\n\nYou are helping in directory {workdir}".strip()


class WorkerSession:
    """Manages one Claude session on the worker side, proxying messages to/from the bot."""

    def __init__(
        self,
        topic_id: int,
        cwd: str,
        writer: asyncio.StreamWriter,
        session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.topic_id = topic_id
        self.cwd = cwd
        self.session_id = session_id
        self.model = model
        self._writer = writer
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._client: ClaudeSDKClient | None = None
        self._pending_permissions: dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        """Start the session loop as an asyncio task."""
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """Main session loop — create Claude SDK client and process messages."""
        system_prompt = _build_system_prompt(self.cwd)
        options = ClaudeAgentOptions(
            cwd=self.cwd,
            model=self.model,
            system_prompt=system_prompt,
            can_use_tool=self._can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_dummy_pretool_hook])]},
            resume=self.session_id,
            include_partial_messages=True,
        )
        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                # Notify bot that session started
                await send_msg(self._writer, SessionStartedMsg(
                    topic_id=self.topic_id,
                    session_id=self.session_id or "",
                ))
                logger.info("Session started for topic %d in %s", self.topic_id, self.cwd)

                while True:
                    text = await self._message_queue.get()
                    if text is None:
                        break

                    await client.query(text)
                    await self._drain_response(client)

        except Exception as e:
            logger.error("Session error for topic %d: %s", self.topic_id, e)
            await send_msg(self._writer, SessionEndedMsg(
                topic_id=self.topic_id, error=str(e),
            ))
        else:
            await send_msg(self._writer, SessionEndedMsg(topic_id=self.topic_id))
        finally:
            self._client = None

    async def _can_use_tool(self, tool_name, input_data, context):
        """Permission callback — forwards permission requests to bot via IPC."""
        import uuid
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_permissions[request_id] = future

        await send_msg(self._writer, PermissionRequestMsg(
            topic_id=self.topic_id,
            request_id=request_id,
            tool_name=tool_name,
            input_data=input_data,
        ))

        try:
            action = await asyncio.wait_for(future, timeout=300.0)
        except asyncio.TimeoutError:
            self._pending_permissions.pop(request_id, None)
            return PermissionResultDeny(message="Timed out")

        if action in ("allow", "always"):
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message="Denied by user")

    def resolve_permission(self, request_id: str, action: str) -> None:
        """Resolve a pending permission future from bot response."""
        future = self._pending_permissions.pop(request_id, None)
        if future and not future.done():
            future.set_result(action)

    async def _drain_response(self, client: ClaudeSDKClient) -> None:
        """Receive all messages from current turn and forward to bot."""
        tool_count = 0
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        await send_msg(self._writer, AssistantTextMsg(
                            topic_id=self.topic_id, text=block.text,
                        ))
                    elif isinstance(block, ToolUseBlock):
                        tool_count += 1
                        await send_msg(self._writer, StatusUpdateMsg(
                            topic_id=self.topic_id,
                            tool_name=block.name,
                            elapsed_ms=0,
                            tool_calls=tool_count,
                        ))

            elif isinstance(msg, ResultMessage):
                if self.session_id is None and msg.session_id:
                    self.session_id = msg.session_id
                    await send_msg(self._writer, SessionStartedMsg(
                        topic_id=self.topic_id,
                        session_id=msg.session_id,
                    ))

    async def enqueue(self, text: str) -> None:
        """Queue a user message for this session."""
        await self._message_queue.put(text)

    async def stop(self) -> None:
        """Stop the session."""
        if self._client:
            await self._client.interrupt()
        await self._message_queue.put(None)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()


class WorkerClient:
    """Connects to the bot IPC server and manages local Claude sessions."""

    def __init__(self, host: str, port: int, token: str, worker_id: str) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.worker_id = worker_id
        self._sessions: dict[int, WorkerSession] = {}
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._running = True

    async def connect(self) -> bool:
        """Connect and authenticate with the bot server. Returns True on success."""
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except (OSError, ConnectionRefusedError) as e:
            logger.error("Cannot connect to %s:%d: %s", self.host, self.port, e)
            return False

        # Send auth
        await send_msg(self._writer, AuthMsg(token=self.token, worker_id=self.worker_id))

        # Wait for auth response
        msg = await recv_b2w(self._reader)
        if isinstance(msg, AuthOkMsg):
            logger.info("Authenticated as worker '%s'", self.worker_id)
            return True
        elif isinstance(msg, AuthFailMsg):
            logger.error("Authentication failed: %s", msg.reason)
            return False
        else:
            logger.error("Unexpected auth response: %r", msg)
            return False

    async def run(self) -> None:
        """Main message loop — dispatch incoming messages from bot."""
        assert self._reader is not None and self._writer is not None

        while self._running:
            msg = await recv_b2w(self._reader)
            if msg is None:
                logger.info("Bot disconnected")
                break

            if isinstance(msg, StartSessionMsg):
                logger.info(
                    "Starting session: topic=%d cwd=%s model=%s",
                    msg.topic_id, msg.cwd, msg.model,
                )
                session = WorkerSession(
                    topic_id=msg.topic_id,
                    cwd=msg.cwd,
                    writer=self._writer,
                    session_id=msg.session_id,
                    model=msg.model,
                )
                self._sessions[msg.topic_id] = session
                await session.start()

            elif isinstance(msg, StopSessionMsg):
                session = self._sessions.pop(msg.topic_id, None)
                if session:
                    logger.info("Stopping session topic=%d", msg.topic_id)
                    await session.stop()

            elif isinstance(msg, UserMessageMsg):
                session = self._sessions.get(msg.topic_id)
                if session:
                    await session.enqueue(msg.text)
                else:
                    logger.warning("UserMessage for unknown topic %d", msg.topic_id)

            elif isinstance(msg, PermissionResponseMsg):
                # Find session that has this pending permission
                for session in self._sessions.values():
                    if msg.request_id in session._pending_permissions:
                        session.resolve_permission(msg.request_id, msg.action)
                        break

            else:
                logger.warning("Unknown message from bot: %r", msg)

    async def shutdown(self) -> None:
        """Stop all sessions and close connection."""
        self._running = False
        for topic_id, session in list(self._sessions.items()):
            try:
                await session.stop()
            except Exception as e:
                logger.error("Error stopping session %d: %s", topic_id, e)
        self._sessions.clear()

        if self._writer and not self._writer.is_closing():
            self._writer.close()


async def main(host: str, port: int, token: str, worker_id: str) -> None:
    """Entry point — connect with auto-reconnect."""
    if not HAS_SDK:
        logger.error("claude_agent_sdk not installed. Install it: pip install claude-agent-sdk")
        sys.exit(1)

    client = WorkerClient(host, port, token, worker_id)

    # Handle signals for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(client.shutdown()))

    retry_delay = 1
    max_delay = 60

    while True:
        if await client.connect():
            retry_delay = 1  # Reset on successful connection
            try:
                await client.run()
            except Exception as e:
                logger.error("Worker loop error: %s", e)
            finally:
                await client.shutdown()

        if not client._running:
            break

        logger.info("Reconnecting in %ds...", retry_delay)
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_delay)
        client = WorkerClient(host, port, token, worker_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IPC Worker Client for Telegram Multi-Thread Router")
    parser.add_argument("--host", required=True, help="Bot server IP/hostname")
    parser.add_argument("--port", type=int, default=9800, help="Bot IPC port (default: 9800)")
    parser.add_argument("--token", required=True, help="Authentication token (must match bot's AUTH_TOKEN)")
    parser.add_argument("--worker-id", required=True, help="Unique name for this worker (e.g. 'mac', 'server-2')")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

    asyncio.run(main(args.host, args.port, args.token, args.worker_id))

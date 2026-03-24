"""SessionRunner — owns one ClaudeSDKClient per session with state machine and message queue."""

import asyncio
import logging
from pathlib import Path

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    PermissionResultAllow,
    HookMatcher,
)
from aiogram import Bot

from src.sessions.state import SessionState
from src.db.queries import update_session_id, update_session_state

logger = logging.getLogger(__name__)


async def _dummy_pretool_hook(input_data, tool_use_id, context):
    """Required PreToolUse hook — without this, can_use_tool never fires (SDK issue #18735)."""
    return {"continue_": True}


async def _auto_allow_tool(tool_name, input_data, context):
    """Phase 2 placeholder: auto-approve all tools. Phase 3 replaces with Telegram permission UI."""
    return PermissionResultAllow(updated_input=input_data)


def _build_system_prompt(workdir: str) -> str:
    """Read CLAUDE.md from workdir if present, append workdir context."""
    claude_md = Path(workdir) / "CLAUDE.md"
    base = ""
    try:
        base = claude_md.read_text()
    except (FileNotFoundError, PermissionError):
        pass
    return f"{base}\n\nYou are helping in directory {workdir}".strip()


class SessionRunner:
    """Owns one ClaudeSDKClient per session. Manages query/response lifecycle via asyncio task."""

    def __init__(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
        session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.workdir = workdir
        self.session_id = session_id
        self.model = model
        self._bot = bot
        self._chat_id = chat_id
        self.state = SessionState.IDLE
        self._client: ClaudeSDKClient | None = None
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()  # None is stop sentinel
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Launch the runner asyncio task."""
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """Main loop: own the ClaudeSDKClient context, process messages from queue."""
        system_prompt = _build_system_prompt(self.workdir)
        options = ClaudeAgentOptions(
            cwd=self.workdir,
            model=self.model,
            system_prompt=system_prompt,
            can_use_tool=_auto_allow_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_dummy_pretool_hook])]},
            resume=self.session_id,
            include_partial_messages=True,
        )
        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                while self.state != SessionState.STOPPED:
                    text = await self._message_queue.get()
                    if text is None:  # stop sentinel
                        break
                    self.state = SessionState.RUNNING
                    await client.query(text)
                    await self._drain_response(client)
                    if self.state == SessionState.INTERRUPTING:
                        self.state = SessionState.STOPPED
                        break
                    self.state = SessionState.IDLE
                    await update_session_state(self.thread_id, "idle")
        except Exception as e:
            logger.error("Session error for thread %d: %s", self.thread_id, e)
            self.state = SessionState.STOPPED
            try:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=self.thread_id,
                    text=f"Session error: {e}",
                )
            except Exception:
                logger.exception("Failed to send error message to thread %d", self.thread_id)
        finally:
            self._client = None

    async def _drain_response(self, client: ClaudeSDKClient) -> None:
        """Receive all messages from the current turn, forwarding text to Telegram."""
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        await self._bot.send_message(
                            chat_id=self._chat_id,
                            message_thread_id=self.thread_id,
                            text=block.text,
                        )
            elif isinstance(msg, ResultMessage):
                if self.session_id is None and msg.session_id:
                    self.session_id = msg.session_id
                    await update_session_id(self.thread_id, msg.session_id)
                logger.info(
                    "Turn complete for thread %d: cost=$%s, duration=%dms",
                    self.thread_id,
                    msg.total_cost_usd,
                    msg.duration_ms,
                )

    async def enqueue(self, text: str) -> None:
        """Queue a user message. Waits naturally if runner is already RUNNING."""
        await self._message_queue.put(text)

    async def stop(self) -> None:
        """Interrupt the running turn (if any) and stop the runner."""
        prev_state = self.state
        self.state = SessionState.INTERRUPTING
        if self._client and prev_state == SessionState.RUNNING:
            await self._client.interrupt()
            # Current _drain_response will complete and the loop checks state
        await self._message_queue.put(None)  # sentinel to unblock queue.get()
        await update_session_state(self.thread_id, "stopped")
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    @property
    def is_alive(self) -> bool:
        """True if the runner task is still running."""
        return self._task is not None and not self._task.done()

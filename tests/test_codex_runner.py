"""Unit tests for the local Codex CLI runner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.sessions.codex_runner import CodexRunner
from src.sessions.state import SessionState


class _FakeStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __aiter__(self):
        self._iter = iter(self._lines)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeProcess:
    def __init__(self, stdout_lines: list[str], stderr_lines: list[str] | None = None, returncode: int = 0) -> None:
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(stderr_lines or [])
        self.returncode = returncode
        self.terminated = False

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True


async def test_build_command_for_new_session():
    runner = CodexRunner(
        thread_id=1,
        workdir="/tmp",
        bot=AsyncMock(),
        chat_id=1,
        model="gpt-5.4",
    )
    command = runner._build_command("hello")
    assert command == [
        "codex",
        "exec",
        "--json",
        "--full-auto",
        "--skip-git-repo-check",
        "-m",
        "gpt-5.4",
        "hello",
    ]


async def test_build_command_for_resume():
    runner = CodexRunner(
        thread_id=1,
        workdir="/tmp",
        bot=AsyncMock(),
        chat_id=1,
        backend_session_id="thread-123",
        model="gpt-5.4",
    )
    command = runner._build_command("next turn")
    assert command == [
        "codex",
        "exec",
        "resume",
        "--json",
        "--full-auto",
        "--skip-git-repo-check",
        "-m",
        "gpt-5.4",
        "thread-123",
        "next turn",
    ]


async def test_run_turn_updates_backend_session_and_sends_text(monkeypatch):
    sent = []

    async def _send_message(**kwargs):
        sent.append(kwargs)
        return MagicMock(message_id=1)

    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=_send_message)
    runner = CodexRunner(thread_id=10, workdir="/tmp", bot=bot, chat_id=5)
    runner._current_reply_to = 99
    runner._status = MagicMock()
    runner._status.track_usage = MagicMock()
    runner._status.finalize = AsyncMock()

    fake_process = _FakeProcess([
        '{"type":"thread.started","thread_id":"thread-123"}\n',
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello from codex"}}\n',
        '{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":7,"output_tokens":3}}\n',
    ])

    create_subprocess_exec = AsyncMock(return_value=fake_process)
    update_backend_session_id = AsyncMock()
    monkeypatch.setattr("src.sessions.codex_runner.asyncio.create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr("src.sessions.codex_runner.update_backend_session_id", update_backend_session_id)

    await runner._run_turn("hello")

    create_subprocess_exec.assert_called_once()
    update_backend_session_id.assert_called_once_with(10, "thread-123")
    assert runner.backend_session_id == "thread-123"
    assert sent[-1]["text"] == "hello from codex"
    assert sent[-1]["reply_to_message_id"] == 99


async def test_interrupt_terminates_active_process():
    runner = CodexRunner(thread_id=1, workdir="/tmp", bot=AsyncMock(), chat_id=1)
    runner.state = SessionState.RUNNING
    runner._current_process = _FakeProcess([])

    interrupted = await runner.interrupt()

    assert interrupted is True
    assert runner._current_process.terminated is True

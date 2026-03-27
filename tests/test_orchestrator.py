"""Tests for orchestrator provider startup/fallback behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.sessions.manager import SessionManager
from src.sessions.permissions import PermissionManager


async def test_ensure_orchestrator_falls_back_to_second_provider(monkeypatch):
    """If the preferred provider fails during startup, ensure_orchestrator tries the next one."""
    from src.config import settings
    from src.sessions import orchestrator as orch
    from src.db import queries

    settings.enable_codex = True
    bot = AsyncMock()
    bot.return_value = SimpleNamespace(message_thread_id=777)
    bot.send_message = AsyncMock()

    monkeypatch.setattr(orch, "get_default_session_provider", lambda: "claude")
    monkeypatch.setattr(queries, "get_orchestrator_topic", AsyncMock(return_value=None))
    monkeypatch.setattr(queries, "insert_topic", AsyncMock())
    monkeypatch.setattr(queries, "insert_session", AsyncMock())
    monkeypatch.setattr(queries, "get_session_by_thread", AsyncMock(return_value=None))
    update_session_provider = AsyncMock()
    monkeypatch.setattr(queries, "update_session_provider", update_session_provider)

    started_providers = []

    async def fake_start_runner(**kwargs):
        started_providers.append(kwargs["provider"])
        if kwargs["provider"] == "claude":
            raise RuntimeError("claude exhausted")
        return SimpleNamespace(provider="codex", state=SimpleNamespace(name="IDLE"), is_alive=True)

    attached = []

    monkeypatch.setattr(orch, "_start_orchestrator_runner", fake_start_runner)
    monkeypatch.setattr(orch, "_attach_orchestrator_fallback", lambda **kwargs: attached.append(kwargs["current_provider"]))

    manager = SessionManager()
    thread_id = await orch.ensure_orchestrator(
        bot,
        -100999,
        manager,
        PermissionManager(),
        question_manager=None,
        worker_registry=SimpleNamespace(),
        orchestrator_mcp_url="http://127.0.0.1:9999/mcp",
    )

    assert thread_id == 777
    assert started_providers == ["claude", "codex"]
    update_session_provider.assert_awaited_once_with(777, "codex", None)
    assert attached == ["codex"]


def test_orchestrator_provider_candidates_prefers_default_then_fallback(monkeypatch):
    """Candidate ordering prefers the configured provider and then the other enabled one."""
    from src.config import settings
    from src.sessions.orchestrator import _orchestrator_provider_candidates

    settings.enable_codex = True
    monkeypatch.setenv("DEFAULT_PROVIDER", "claude")
    assert _orchestrator_provider_candidates("claude") == ["claude", "codex"]
    assert _orchestrator_provider_candidates("codex") == ["codex", "claude"]

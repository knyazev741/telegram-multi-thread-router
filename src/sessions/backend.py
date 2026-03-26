"""Shared session backend contract and provider constants."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from src.sessions.state import SessionState

SessionProvider = Literal["claude", "codex"]

DEFAULT_SESSION_PROVIDER: SessionProvider = "claude"
SUPPORTED_SESSION_PROVIDERS: tuple[SessionProvider, ...] = ("claude", "codex")


def is_supported_provider(provider: str | None) -> bool:
    """Return True if the value is one of the explicit supported providers."""
    return provider in SUPPORTED_SESSION_PROVIDERS


def normalize_provider(provider: str | None) -> SessionProvider:
    """Normalize a provider string, defaulting legacy/empty values to Claude."""
    if provider == "codex":
        return "codex"
    return DEFAULT_SESSION_PROVIDER


@runtime_checkable
class SessionBackend(Protocol):
    """Common contract implemented by local and remote session backends."""

    thread_id: int
    workdir: str
    provider: SessionProvider
    session_id: str | None
    backend_session_id: str | None
    state: SessionState
    auto_mode: bool

    @property
    def is_alive(self) -> bool: ...

    async def start(self) -> None: ...

    async def enqueue(self, text: str, reply_to_message_id: int | None = None) -> None: ...

    async def interrupt(self) -> bool: ...

    async def stop(self) -> None: ...

"""SessionManager — maps thread_id to SessionRunner or RemoteSession instances."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot

from src.config import settings
from src.db.queries import update_codex_account, get_active_codex_session_counts
from src.sessions.backend import (
    SessionBackend,
    SessionProvider,
    load_repo_local_instructions,
    normalize_provider,
)
from src.sessions.codex_accounts import get_codex_account_chain
from src.sessions.codex_runner import CodexRunner
from src.sessions.codex_usage import (
    fetch_all_accounts_usage,
    path_to_account_name,
    invalidate_cache,
)
from src.sessions.codex_selector import score_accounts, select_best
from src.sessions.permissions import PermissionManager
from src.sessions.questions import QuestionManager
from src.sessions.remote import RemoteSession
from src.sessions.runner import SessionRunner

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages the lifecycle of all active SessionRunner and RemoteSession instances."""

    def __init__(self, question_manager: QuestionManager | None = None) -> None:
        self._sessions: dict[int, SessionBackend] = {}
        self._lock = asyncio.Lock()
        self._question_manager = question_manager

    async def create(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
        permission_manager: PermissionManager,
        session_id: str | None = None,
        backend_session_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        codex_account: str | None = None,
    ) -> SessionBackend:
        """Create and start a new SessionRunner for the given thread_id.

        Args:
            codex_account: Explicit codex account path to use (from DB on resume).
                If None and provider is codex, the smart selector picks the best account.

        Raises ValueError if a session for that thread already exists.
        """
        normalized_provider = normalize_provider(provider)
        async with self._lock:
            if thread_id in self._sessions:
                raise ValueError(f"Session for topic {thread_id} already exists")
            runner: SessionBackend
            if normalized_provider == "codex":
                runner, chosen_account = await self._create_codex_runner(
                    thread_id=thread_id,
                    workdir=workdir,
                    bot=bot,
                    chat_id=chat_id,
                    permission_manager=permission_manager,
                    backend_session_id=backend_session_id,
                    model=model,
                    codex_account=codex_account,
                )
                # Persist which account was chosen for resume
                account_str = str(chosen_account) if chosen_account else "default"
                try:
                    await update_codex_account(thread_id, account_str)
                except Exception:
                    pass  # DB might not have the column yet during migration

                # Invalidate the usage cache for the chosen account so that the
                # next selection sees updated activity counts immediately.
                account_name = path_to_account_name(chosen_account)
                invalidate_cache(account_name)
            else:
                runner = SessionRunner(
                    thread_id=thread_id,
                    workdir=workdir,
                    bot=bot,
                    chat_id=chat_id,
                    permission_manager=permission_manager,
                    question_manager=self._question_manager,
                    session_id=session_id or backend_session_id,
                    model=model,
                )
            self._sessions[thread_id] = runner
            await runner.start()
            return runner

    async def _create_codex_runner(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
        permission_manager: PermissionManager,
        backend_session_id: str | None = None,
        model: str | None = None,
        codex_account: str | None = None,
    ) -> tuple[CodexRunner, Path | None]:
        """Create a CodexRunner, return (runner, chosen_codex_home).

        On resume (codex_account provided): honour the stored account exactly.
        On new session: use the smart selector to pick the best available account.
        """
        codex_home: Path | None

        if codex_account is not None:
            # ── Resume path: use the exact account stored in DB ───────────────
            # "default" means no CODEX_HOME override (system default ~/.codex)
            if codex_account == "default":
                codex_home = None
            else:
                codex_home = Path(codex_account)
            logger.info(
                "Resuming Codex session for topic %d with saved account %s",
                thread_id,
                codex_account,
            )
        else:
            # ── New session: smart selection ──────────────────────────────────
            codex_home = await self._pick_best_codex_account()

        runner = CodexRunner(
            thread_id=thread_id,
            workdir=workdir,
            bot=bot,
            chat_id=chat_id,
            permission_manager=permission_manager,
            question_manager=self._question_manager,
            backend_session_id=backend_session_id,
            model=model,
            base_instructions=load_repo_local_instructions(workdir),
            codex_home=codex_home,
        )
        return runner, codex_home

    async def _pick_best_codex_account(self) -> Path | None:
        """Select the best Codex account using live usage data + active session counts.

        Falls back gracefully to chain[0] if the usage API is unreachable or
        the account chain is empty.
        """
        account_chain = get_codex_account_chain(settings.codex_accounts)
        if not account_chain:
            return None

        # Only one account configured — skip the API round-trip
        if len(account_chain) == 1:
            chosen = account_chain[0]
            logger.info(
                "Single Codex account configured, using %s",
                str(chosen) if chosen else "default",
            )
            return chosen

        account_names = [path_to_account_name(p) for p in account_chain]

        try:
            # Fetch usage for all accounts in parallel
            usages = await fetch_all_accounts_usage(account_chain, account_names)

            # Get active session counts from DB
            active_counts = await get_active_codex_session_counts()

            # Score and pick best
            scores = score_accounts(usages, active_counts)
            best = select_best(scores)

            if best is not None:
                logger.info(
                    "Smart Codex account selection: chose '%s' "
                    "(score=%.1f, 5h=%.0f%%, weekly=%.0f%%, active=%d) "
                    "from chain %s",
                    best.account_name,
                    best.score,
                    best.adjusted_5h,
                    best.weekly_remaining,
                    best.active_count,
                    account_names,
                )
                return best.codex_home

        except Exception as exc:
            logger.warning(
                "Smart Codex account selection failed (%s); falling back to chain[0]",
                exc,
            )

        # Fallback: use the first entry in the chain (original behaviour)
        fallback = account_chain[0]
        logger.info(
            "Fallback Codex account: %s",
            str(fallback) if fallback else "default",
        )
        return fallback

    async def create_remote(
        self,
        thread_id: int,
        workdir: str,
        worker_id: str,
        worker_registry,
        session_id: str | None = None,
        backend_session_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        provider_options: dict | None = None,
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
                backend_session_id=backend_session_id,
                provider=provider,
                model=model,
                provider_options=provider_options,
            )
            self._sessions[thread_id] = session
            await session.start()
            return session

    def get(self, thread_id: int) -> Optional[SessionBackend]:
        """Return the runner/session for thread_id, or None if not found."""
        return self._sessions.get(thread_id)

    async def stop(self, thread_id: int) -> None:
        """Stop and remove the runner for thread_id. No-op if not found."""
        async with self._lock:
            runner = self._sessions.pop(thread_id, None)
            if runner:
                await runner.stop()

    def list_all(self) -> list[tuple[int, SessionBackend]]:
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
        Orchestrator is skipped — ensure_orchestrator() handles it with proper MCP tools.
        Returns number of successfully resumed sessions.
        """
        from src.db.queries import get_resumable_sessions, get_orchestrator_topic, update_session_state

        rows = await get_resumable_sessions()
        resumed = 0

        # Get orchestrator thread_id to skip it (ensure_orchestrator handles it)
        orch = await get_orchestrator_topic()
        orch_thread_id = orch["thread_id"] if orch else None

        for row in rows:
            thread_id = row["thread_id"]
            session_id = row["session_id"]
            backend_session_id = row.get("backend_session_id")
            workdir = row["workdir"]
            model = row.get("model")
            server = row.get("server", "local")
            provider = normalize_provider(row.get("provider"))

            # Skip remote sessions — worker reconnect handles re-registration
            if server != "local":
                logger.info(
                    "Skipping remote session topic %d (server=%s provider=%s) on resume",
                    thread_id,
                    server,
                    provider,
                )
                continue

            # Skip orchestrator — ensure_orchestrator() handles it with proper MCP tools
            if thread_id == orch_thread_id:
                logger.info("Skipping orchestrator topic %d on resume (handled separately)", thread_id)
                continue

            try:
                runner = await self.create(
                    thread_id=thread_id,
                    workdir=workdir,
                    bot=bot,
                    chat_id=chat_id,
                    permission_manager=permission_manager,
                    session_id=session_id,
                    backend_session_id=backend_session_id,
                    model=model,
                    provider=provider,
                    codex_account=row.get("codex_account"),
                )
                # Restore auto_mode and goal_text from DB
                if row.get("auto_mode"):
                    runner.auto_mode = True
                if row.get("goal_text"):
                    runner.goal_text = row["goal_text"]
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

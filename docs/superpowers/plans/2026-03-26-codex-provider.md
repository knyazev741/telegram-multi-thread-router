# Codex Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Codex as a second session executor alongside the existing Claude Code path without changing default Claude behavior.

**Architecture:** Keep the current Claude runner behavior intact and introduce a provider-aware session backend contract. Add a local Codex CLI-backed runner as the first Codex backend, guarded by a feature flag, while extending DB and IPC schemas in a backward-compatible way for future remote Codex workers.

**Tech Stack:** Python 3.11, aiogram 3, aiosqlite, msgspec, claude-agent-sdk, Codex CLI

---

### Task 1: Provider Persistence And Compatibility

**Files:**
- Modify: `src/db/schema.py`
- Modify: `src/db/queries.py`
- Test: `tests/test_db.py`
- Test: `tests/test_session_routing.py`

- [ ] Add `provider TEXT NOT NULL DEFAULT 'claude'` and `backend_session_id TEXT` to `sessions`, plus idempotent migrations for existing DBs.
- [ ] Make every session read/write query include `provider` and `backend_session_id`, with default behavior remaining `provider='claude'`.
- [ ] Keep existing `session_id` semantics untouched for Claude resume.
- [ ] Extend DB tests to verify new columns, defaults, and resumable session rows.

### Task 2: Session Backend Contract

**Files:**
- Add: `src/sessions/backend.py`
- Modify: `src/sessions/runner.py`
- Modify: `src/sessions/remote.py`
- Modify: `src/sessions/manager.py`
- Test: `tests/test_session_routing.py`

- [ ] Introduce a shared `SessionBackend` protocol exposing `thread_id`, `workdir`, `provider`, `session_id`, `backend_session_id`, `state`, `auto_mode`, `is_alive`, `start()`, `enqueue()`, `interrupt()`, and `stop()`.
- [ ] Keep the current Claude implementation behavior intact by making `SessionRunner` explicitly represent `provider='claude'`.
- [ ] Extend `RemoteSession` to carry `provider`, `model`, and future provider options without changing its current behavior for Claude workers.
- [ ] Update `SessionManager` typing and construction paths to target the backend contract rather than a concrete Claude runner.

### Task 3: Config And Provider-Aware UX

**Files:**
- Modify: `src/config.py`
- Modify: `src/bot/routers/session.py`
- Modify: `src/sessions/orchestrator.py`
- Test: `tests/test_router.py`

- [ ] Add `enable_codex: bool = False` to settings.
- [ ] Extend `/new` to accept optional provider while preserving `/new <name> <workdir> [server]` as implicit Claude.
- [ ] Show provider in start confirmations, `/list`, and orchestrator-created sessions.
- [ ] Reject `provider=codex` cleanly when the feature flag is disabled.
- [ ] Extend orchestrator MCP tool schema and system prompt so it can create `provider='claude'|'codex'` sessions.

### Task 4: Local Codex CLI Runner

**Files:**
- Add: `src/sessions/codex_runner.py`
- Modify: `src/sessions/manager.py`
- Test: `tests/test_codex_runner.py`

- [ ] Implement a queue-driven runner that shells out to `codex exec --json` for new turns and `codex exec resume --json <thread_id> <prompt>` for resumed turns.
- [ ] Parse JSONL events at minimum for `thread.started`, `item.completed` with `agent_message`, `turn.completed`, and `error`.
- [ ] Persist the Codex conversation/thread id into `backend_session_id`.
- [ ] Support interrupt by terminating the active subprocess.
- [ ] Treat Codex MVP as auto-execution only; do not attempt Claude-style per-tool approval parity yet.

### Task 5: IPC Compatibility For Future Remote Codex Workers

**Files:**
- Modify: `src/ipc/protocol.py`
- Modify: `src/ipc/server.py`
- Modify: `src/worker/client.py`
- Test: `tests/test_ipc.py`
- Test: `tests/test_worker.py`

- [ ] Extend `StartSessionMsg` with optional `provider` and optional `provider_options`.
- [ ] Include provider in remote-session creation and resume paths, defaulting to Claude when absent.
- [ ] Keep existing worker behavior valid when new fields are omitted.

### Task 6: Verification

**Files:**
- Test: `tests/test_db.py`
- Test: `tests/test_session_routing.py`
- Test: `tests/test_router.py`
- Test: `tests/test_ipc.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_codex_runner.py`

- [ ] Run targeted tests for DB, routing, IPC, worker, and new Codex runner behavior.
- [ ] Record any known Codex MVP limitations: no Telegram inline per-tool approvals, local CLI dependency, resume based on Codex thread id.

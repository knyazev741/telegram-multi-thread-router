# Codex Parity Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Codex provider from an MVP CLI runner to an app-server-backed session backend that matches the current Claude session UX as closely as Codex protocol capabilities allow.

**Architecture:** Replace the local `codex exec --json` runner with a persistent `codex app-server` JSON-RPC session per Telegram thread. Keep the provider abstraction and DB shape from phase 1, but move Codex execution to a long-lived thread with turn lifecycle control (`turn/start`, `turn/steer`, `turn/interrupt`) and server-request bridges for approvals and user input.

**Tech Stack:** Python 3.14, asyncio, aiogram 3, aiosqlite, msgspec, Codex app-server JSON-RPC v2

---

### Task 1: Protocol Plan And Runtime Surface

**Files:**
- Create: `docs/superpowers/plans/2026-03-26-codex-parity-phase2.md`
- Inspect: OpenAI Codex official docs and upstream protocol sources

- [ ] Lock the parity architecture on top of `codex app-server`, not `codex exec --json`.
- [ ] Use official protocol sources to cover notifications, approvals, and request-user-input semantics.
- [ ] Keep Claude-path unchanged.

### Task 2: App-Server Client

**Files:**
- Add: `src/sessions/codex_app_server.py`
- Test: `tests/test_codex_app_server.py`

- [ ] Implement an async stdio JSON-RPC client for `codex app-server`.
- [ ] Support `initialize`, `thread/start`, `thread/resume`, `turn/start`, `turn/steer`, `turn/interrupt`, and `thread/compact/start`.
- [ ] Route responses, notifications, and server-initiated requests separately.
- [ ] Preserve thread id for DB resume.

### Task 3: Codex Runner Parity Layer

**Files:**
- Modify: `src/sessions/codex_runner.py`
- Test: `tests/test_codex_runner.py`

- [ ] Convert the runner to use the persistent app-server client.
- [ ] Maintain one Codex thread per Telegram topic and one active turn at a time.
- [ ] Re-enable mid-turn message injection using `turn/steer`.
- [ ] Support interrupt via `turn/interrupt`.
- [ ] Consume streaming notifications for agent messages, command output, file change output, plan deltas, token usage, and model reroutes.

### Task 4: Permission And Question Bridges

**Files:**
- Modify: `src/sessions/codex_runner.py`
- Test: `tests/test_codex_runner.py`

- [ ] Map `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, and `item/permissions/requestApproval` onto the current Telegram approval UX.
- [ ] Map `item/tool/requestUserInput` onto the existing Telegram question flow.
- [ ] Resolve pending requests correctly on completion, interrupt, and timeout.

### Task 5: Command Compatibility

**Files:**
- Modify: `src/sessions/codex_runner.py`
- Modify: `src/bot/routers/session.py`
- Test: `tests/test_router.py`

- [ ] Handle the highest-value Claude-style slash commands directly for Codex sessions.
- [ ] `/compact` should call thread compaction.
- [ ] `/model <name>` should update the session’s default model for future turns.
- [ ] `/clear` and `/reset` should rotate to a fresh Codex thread while keeping the Telegram topic.

### Task 6: Verification

**Files:**
- Test: `tests/test_codex_app_server.py`
- Test: `tests/test_codex_runner.py`
- Test: `tests/test_router.py`
- Test: `tests/test_session_routing.py`

- [ ] Add unit coverage for protocol routing, request handling, slash compatibility, and steer/interrupt semantics.
- [ ] Run the relevant pytest suite with fresh evidence.

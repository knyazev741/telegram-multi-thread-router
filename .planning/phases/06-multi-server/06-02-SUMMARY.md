---
phase: 06-multi-server
plan: 02
subsystem: worker
tags: [worker, ipc, tcp, session-runner, permission-bridge, exponential-backoff]
dependency_graph:
  requires: [06-01]
  provides: [worker-process, worker-output-channel, worker-client]
  affects: [src/sessions/runner.py, src/ipc/protocol.py]
tech_stack:
  added: []
  patterns:
    - Monkey-patching SessionRunner._can_use_tool with TCP permission bridge closure
    - WorkerOutputChannel as aiogram.Bot drop-in replacement forwarding over TCP
    - Exponential backoff reconnect loop (1s -> 60s max) with auth-failure permanent exit
key_files:
  created:
    - src/worker/__init__.py
    - src/worker/output_channel.py
    - src/worker/client.py
    - src/worker/__main__.py
  modified: []
decisions:
  - Permission bridge implemented via monkey-patching runner._can_use_tool instead of WorkerOutputChannel.send_message reply_markup detection — avoids parsing keyboard data, cleaner separation of concerns
  - Permission futures resolved with "deny" on TCP disconnect (not cancel) — allows _can_use_tool to unblock cleanly without propagating CancelledError into SessionRunner
  - WorkerOutputChannel.send_message sends AssistantTextMsg for all text (not McpSendMessageMsg) — simplifies bot-side routing since both convey the same information
  - delete_message is no-op on worker — status message deletion is best-effort and chatty over TCP
  - send_chat_action is no-op on worker — typing indicators are too frequent to forward over TCP economically
metrics:
  duration_minutes: 3
  completed_date: "2026-03-25"
  tasks_completed: 2
  files_created: 4
  files_modified: 0
---

# Phase 6 Plan 02: Worker Process Summary

**One-liner:** Remote worker process with TCP output channel adapter and permission bridge that runs SessionRunner locally while forwarding all Claude events to the central bot.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | WorkerOutputChannel — Bot-replacement adapter for TCP output | 75998f9 | src/worker/__init__.py, src/worker/output_channel.py |
| 2 | WorkerClient — TCP connection loop, session management, permission bridge | e6d5152 | src/worker/client.py, src/worker/__main__.py |

## What Was Built

### WorkerOutputChannel (`src/worker/output_channel.py`)

Drop-in replacement for `aiogram.Bot` used by SessionRunner, StatusUpdater, TypingIndicator, and MCP tools. Instead of calling the Telegram API, it forwards calls over the existing TCP connection via IPC protocol messages:

- `send_message` → `AssistantTextMsg` + returns `MockMessage(message_id)` so StatusUpdater's `.message_id` reads don't crash
- `edit_message_text` → `McpEditMessageMsg`
- `send_document` → `McpSendFileMsg`, handles `FSInputFile.path` extraction
- `set_message_reaction` → `McpReactMsg`, extracts emoji from `ReactionTypeEmoji`
- `delete_message` → no-op (status deletions are best-effort)
- `send_chat_action` → no-op (typing indicators too chatty over TCP)
- `download` → raises `NotImplementedError` (file downloads are bot-side only)
- `set_writer(writer)` for updating the writer on reconnect
- `is_connected` property to check transport state

All `send_msg` calls wrapped in `try/except` for `BrokenPipeError`, `ConnectionResetError`, `OSError` — logs warning, does not crash the SessionRunner.

### WorkerClient (`src/worker/client.py`)

Manages the lifecycle of the TCP connection and local Claude sessions:

**Reconnect loop** — exponential backoff (1s → 2s → 4s → max 60s), resets to 1s on successful authentication. Auth failures (non-`AuthOkMsg` response) exit the loop permanently.

**Session management** — `_sessions: dict[int, SessionRunner]` keyed by topic_id. On reconnect, re-registers existing sessions with `SessionStartedMsg` so the bot knows they survived.

**Permission bridge** — replaces `SessionRunner._can_use_tool` with a closure that:
1. Auto-approves tools in `_allowed_tools` (preserves PERM-07)
2. Sends `PermissionRequestMsg` over TCP
3. Awaits a local `asyncio.Future` with 300s timeout
4. `PermissionResponseMsg` from bot resolves the future
5. On TCP disconnect: futures resolved with "deny" (not cancelled) so `_can_use_tool` unblocks cleanly

**Disconnect handling** — `_on_disconnected()` resolves all pending permission futures with "deny" and clears the futures dict. Does NOT stop sessions — they survive reconnection.

**Message routing** — handles `StartSessionMsg`, `StopSessionMsg`, `UserMessageMsg`, `PermissionResponseMsg`, `SlashCommandMsg` from the receive loop.

### Entry Point (`src/worker/__main__.py`)

`python -m src.worker` reads env vars:
- `IPC_HOST` (default: 127.0.0.1)
- `IPC_PORT` (default: 9800)
- `AUTH_TOKEN` (required)
- `WORKER_ID` (required — becomes the server name in `/new ... server-name`)

Exits with error message if required vars are missing.

## Decisions Made

1. **Permission bridge via monkey-patch** — Patching `runner._can_use_tool` directly rather than detecting `reply_markup` in `WorkerOutputChannel.send_message`. This avoids parsing keyboard callback data on the output channel and keeps the permission logic centralized in `WorkerClient`.

2. **Resolve futures with "deny" on disconnect** — Instead of cancelling permission futures, they are resolved with `"deny"` action. This allows `_can_use_tool` to return `PermissionResultDeny` cleanly without `CancelledError` propagating into `SessionRunner._run()`.

3. **AssistantTextMsg for all text output** — `send_message` sends `AssistantTextMsg` rather than `McpSendMessageMsg`. Both convey text to a topic; using one type simplifies the bot-side routing handler.

4. **Sessions survive TCP disconnect** — `_on_disconnected()` does not stop sessions. On reconnect, existing sessions are re-registered and can continue receiving messages. This matches the plan design for disconnect resilience.

## Deviations from Plan

None — plan executed exactly as written. The "revised cleaner approach for permissions" described in the plan (monkey-patching `_can_use_tool`) was implemented as specified.

## Self-Check

- [x] `src/worker/__init__.py` exists
- [x] `src/worker/output_channel.py` exists, `WorkerOutputChannel` importable
- [x] `src/worker/client.py` exists, `WorkerClient` importable
- [x] `src/worker/__main__.py` exists, valid Python, `main()` function present
- [x] Commit 75998f9 exists (Task 1)
- [x] Commit e6d5152 exists (Task 2)

---
phase: 06-multi-server
plan: "01"
subsystem: ipc
tags: [ipc, protocol, msgspec, tcp, worker-registry]
dependency_graph:
  requires: []
  provides: [ipc-protocol, ipc-server, worker-registry, ipc-config]
  affects: [dispatcher, config]
tech_stack:
  added: [msgspec>=0.18.0]
  patterns: [msgspec-tagged-union, length-prefix-framing, asyncio-start-server, worker-registry-pattern]
key_files:
  created:
    - src/ipc/__init__.py
    - src/ipc/protocol.py
    - src/ipc/server.py
  modified:
    - pyproject.toml
    - src/config.py
    - src/bot/dispatcher.py
key_decisions:
  - "Explicit tag strings (tag=\"auth\", tag=\"auth_ok\", etc.) used instead of tag=True — required for discriminated Union decoding with msgspec msgpack"
  - "asyncio.IncompleteReadError caught (not EOFError) in recv_w2b/recv_b2w per research Pitfall 1"
  - "PermissionResponseMsg uses orig msg.request_id (worker-assigned) not the local future key — futures keyed by local ID, response carries worker-originating ID back"
  - "asyncio.create_task used in handle_connection so accept loop is never blocked by slow auth"
metrics:
  duration: 2 min
  completed: "2026-03-25"
  tasks_completed: 2
  files_changed: 6
---

# Phase 06 Plan 01: TCP IPC Protocol Layer and Bot-Side Server Summary

**One-liner:** msgspec msgpack TCP IPC protocol with 17 typed Struct messages, 4-byte length-prefix framing, and bot-side WorkerRegistry server for remote worker connections.

## What Was Built

The TCP communication foundation between the central Telegram bot and remote worker processes. This enables Phase 6's multi-server architecture: workers on remote hosts connect over TCP, authenticate with a shared auth_token, and exchange typed protocol messages in both directions.

### src/ipc/protocol.py
Defines all protocol message types as `msgspec.Struct` subclasses with explicit wire tag strings. Split into two groups:

**Worker-to-Bot (10 types):** AuthMsg, SessionStartedMsg, AssistantTextMsg, PermissionRequestMsg, StatusUpdateMsg, SessionEndedMsg, McpSendMessageMsg, McpReactMsg, McpEditMessageMsg, McpSendFileMsg

**Bot-to-Worker (7 types):** AuthOkMsg, AuthFailMsg, StartSessionMsg, StopSessionMsg, UserMessageMsg, PermissionResponseMsg, SlashCommandMsg

`WorkerToBot` and `BotToWorker` Union types enable discriminated decoding. Module-level `_enc`, `_w2b_dec`, `_b2w_dec` singletons avoid repeated encoder/decoder construction. Framing helpers `send_msg`, `recv_w2b`, `recv_b2w` use `readexactly()` for clean, non-blocking stream reads.

### src/ipc/server.py
`WorkerRegistry` — dictionary-backed tracker for live worker connections keyed by `worker_id`. Methods: `register`, `unregister`, `send_to` (async, returns bool), `is_connected`, `list_workers`.

`start_ipc_server` — creates `asyncio.start_server` with a non-blocking accept callback (`asyncio.create_task` per connection). Returns the `asyncio.Server` object for lifecycle management.

`_handle_worker` — full auth handshake + message dispatch loop handling all 10 WorkerToBot variants. Permission requests spawn a background task that awaits the future with a 300-second timeout, then sends `PermissionResponseMsg` back via TCP.

### src/config.py
Added `ipc_host: str = "0.0.0.0"` and `ipc_port: int = 9800` to Settings with sensible defaults.

### src/bot/dispatcher.py
`on_startup`: creates `WorkerRegistry`, starts IPC server, stores both in dispatcher dict under `"worker_registry"` and `"ipc_server"` keys.

`on_shutdown`: closes IPC server (`server.close()` + `await server.wait_closed()`) before stopping active sessions.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files Created/Modified
- src/ipc/__init__.py: exists
- src/ipc/protocol.py: exists
- src/ipc/server.py: exists
- pyproject.toml: modified (msgspec added)
- src/config.py: modified (ipc_host, ipc_port added)
- src/bot/dispatcher.py: modified (IPC lifecycle wired)

### Commits
- e351ecc: feat(06-01): IPC protocol module — msgspec Structs, framing helpers, msgspec dep
- b413a59: feat(06-01): IPC server, WorkerRegistry, config fields, dispatcher wiring

## Self-Check: PASSED

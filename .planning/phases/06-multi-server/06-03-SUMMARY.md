---
phase: 06-multi-server
plan: 03
subsystem: session-routing
tags: [remote-session, session-manager, ipc, tests, msrv]
dependency_graph:
  requires: [06-01, 06-02]
  provides: [bot-side-routing, remote-session-proxy, msrv-tests]
  affects: [src/sessions, src/bot/routers, src/db]
tech_stack:
  added: []
  patterns:
    - RemoteSession duck-typing SessionRunner interface for transparent routing
    - TYPE_CHECKING import to avoid circular dependency (RemoteSession → ipc.server)
    - asyncio.StreamReader.feed_data() for synchronous framing tests (no network)
    - pytest-asyncio AUTO mode for all async tests
key_files:
  created:
    - src/sessions/remote.py
    - tests/test_ipc.py
    - tests/test_worker.py
    - tests/test_session_routing.py
  modified:
    - src/sessions/manager.py
    - src/bot/routers/general.py
    - src/db/queries.py
    - tests/test_router.py
decisions:
  - "TYPE_CHECKING guard used in remote.py to import WorkerRegistry — avoids circular import through ipc.server → config → settings at module load time"
  - "asyncio.StreamReader.feed_data() used for framing tests instead of TCP loopback — loopback server approach caused indefinite hang due to server accept task not completing before server.close()"
  - "handle_new now requires worker_registry as DI parameter — passed via dispatcher dict like session_manager and permission_manager"
metrics:
  duration: 11 min
  completed: 2026-03-25
  tasks_completed: 2
  files_changed: 8
---

# Phase 06 Plan 03: Bot-Side Routing and Tests Summary

Bot-side session routing wired: RemoteSession proxy, SessionManager extended with create_remote() and get_server(), /new updated to accept optional server-name arg, /list shows server + connection status, insert_session stores server field, and comprehensive tests added covering all MSRV-01 through MSRV-08 requirements.

## Tasks Completed

### Task 1: RemoteSession proxy, SessionManager routing, /new /list updates, DB server field
**Commit:** b6bec00

Created `src/sessions/remote.py` — `RemoteSession` proxies enqueue/stop/start calls to worker via `WorkerRegistry.send_to`. Uses `TYPE_CHECKING` guard to avoid circular imports through `ipc.server`.

Extended `SessionManager`:
- `_sessions` typed as `dict[int, SessionRunner | RemoteSession]`
- `create_remote()` — acquires lock, creates RemoteSession, sends StartSessionMsg to worker
- `get_server()` — returns `worker_id` for remote sessions, `"local"` for local
- `resume_all()` — skips remote sessions (server != "local"); worker reconnect handles re-registration

Updated `handle_new` in `general.py`:
- Parses optional `[server-name]` arg with `maxsplit=3`
- Validates worker connectivity via `worker_registry.is_connected()`
- Routes to `create_remote()` or `create()` based on server arg
- Passes `worker_registry: WorkerRegistry` as DI parameter

Updated `handle_list`: shows `on <i>server</i> (connected|disconnected)` per session.

Updated `insert_session` in `queries.py`:
- Added `server: str = "local"` parameter
- SQL includes `server` column
- `get_resumable_sessions` and `get_all_active_sessions` include `server` in SELECT

### Task 2: Tests for all MSRV requirements
**Commit:** df6bef3

**tests/test_ipc.py** (27 tests):
- Protocol round-trip for all 20 message types (12 W2B + 8 B2W) via parametrize
- Framing: `recv_w2b`/`recv_b2w` via `StreamReader.feed_data()` — no network needed
- EOF: `recv_w2b` returns None on `feed_eof()`
- Auth handshake success/failure via real `start_ipc_server` on port 0
- `test_worker_forwards_text` and `test_bot_forwards_user_message` via authenticated TCP

**tests/test_worker.py** (9 tests):
- `WorkerOutputChannel.send_message` encodes `AssistantTextMsg` correctly
- `SessionRunner` instantiates with `WorkerOutputChannel` as bot
- Reconnect backoff: mocked `open_connection` + `asyncio.sleep`, verifies 1→2→4→8 pattern with max 60
- `_resolve_permission`: resolves future with action string
- `_on_disconnected`: resolves all pending futures with "deny", clears writer

**tests/test_session_routing.py** (13 tests):
- `create_remote()` stores RemoteSession with correct `worker_id`
- `create()` returns SessionRunner (not RemoteSession)
- `get_server()` returns `worker_id` for remote, `"local"` for local
- `list_all()` returns both session types correctly
- `enqueue()` sends `UserMessageMsg`, `stop()` sends `StopSessionMsg` + sets STOPPED state
- `is_alive` reflects `WorkerRegistry.is_connected()`
- DB: `insert_session` stores server field, defaults to "local"; `get_resumable_sessions` includes server

Also fixed `tests/test_router.py` to pass `worker_registry` to `handle_new`.

## Verification

Full suite: **104 passed** in 2.39s. No regressions.

```
python -m pytest tests/test_ipc.py tests/test_worker.py tests/test_session_routing.py -v
# 49 passed in 1.54s

python -m pytest tests/ -x
# 104 passed in 2.39s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used TYPE_CHECKING guard in remote.py instead of direct import**
- **Found during:** Task 1
- **Issue:** `from src.ipc.server import WorkerRegistry` triggers module-level `src.config.settings = Settings()` instantiation, failing without `GROUP_CHAT_ID` env var
- **Fix:** Moved `WorkerRegistry` import under `TYPE_CHECKING` — runtime isinstance checks use duck typing, not the class
- **Files modified:** `src/sessions/remote.py`
- **Commit:** b6bec00

**2. [Rule 3 - Blocking] Used StreamReader.feed_data() for framing tests**
- **Found during:** Task 2
- **Issue:** Loopback TCP server approach for framing tests caused indefinite hang — server's `_accept` callback ran as a background task that didn't complete before `server.wait_closed()`, leaving the coroutine blocked
- **Fix:** Used `asyncio.StreamReader` with `feed_data()` / `feed_eof()` — synchronous data injection, no network required, tests complete instantly
- **Files modified:** `tests/test_ipc.py`
- **Commit:** df6bef3

**3. [Rule 1 - Bug] Fixed _w2b_dec vs _b2w_dec in worker output channel test**
- **Found during:** Task 2
- **Issue:** `AssistantTextMsg` is a WorkerToBot message but test used `_b2w_dec` to decode
- **Fix:** Changed to `_w2b_dec` in the assertion
- **Files modified:** `tests/test_worker.py`
- **Commit:** df6bef3

## Self-Check: PASSED

- FOUND: b6bec00 (Task 1 commit)
- FOUND: df6bef3 (Task 2 commit)
- FOUND: src/sessions/remote.py
- FOUND: tests/test_ipc.py
- FOUND: tests/test_worker.py
- FOUND: tests/test_session_routing.py
- FOUND: .planning/phases/06-multi-server/06-03-SUMMARY.md

---
phase: 02-session-lifecycle
plan: "03"
subsystem: sessions
tags: [session-persistence, health-monitoring, startup-recovery, zombie-detection]
dependency_graph:
  requires: [02-02]
  provides: [session-persistence, zombie-detection]
  affects: [dispatcher-startup, dispatcher-shutdown]
tech_stack:
  added: []
  patterns:
    - asyncio background task for health monitoring
    - startup recovery pattern via DB query + runner recreation
key_files:
  created:
    - src/sessions/health.py
  modified:
    - src/sessions/manager.py
    - src/bot/dispatcher.py
decisions:
  - "resume_all uses deferred imports for get_resumable_sessions/update_session_state to avoid circular imports"
  - "health_check_loop uses runner.is_alive (checks task.done()) rather than internal SDK attributes for zombie detection"
  - "health_task stored in dispatcher dict keyed 'health_task' for clean cancellation on shutdown"
metrics:
  duration: 3 min
  completed_date: "2026-03-24"
  tasks_completed: 2
  files_changed: 3
---

# Phase 02 Plan 03: Session Persistence and Health Monitoring Summary

Session persistence via startup resume + background zombie detection using asyncio task lifecycle checks.

## What Was Built

**Task 1 — SessionManager.resume_all + health_check_loop**

Added `resume_all(bot, chat_id) -> int` to `SessionManager`: queries `get_resumable_sessions()` from SQLite, recreates `SessionRunner` instances with stored `session_id` and `workdir` for each previously active session, sends "Session resumed after bot restart." to each topic. Failed resumes log the error and mark the session as stopped in DB to prevent infinite retry loops.

Created `src/sessions/health.py` with `health_check_loop(manager, bot, chat_id, interval=60)`: background asyncio coroutine that wakes every 60 seconds, iterates all active runners, checks `runner.is_alive` (which checks `task.done()`), detects any runner whose task completed but state is not STOPPED (zombie), then stops it via `manager.stop()`, marks it stopped in DB via `update_session_state()`, and sends a notification to the topic. All operations wrapped in individual try/except blocks so the loop never crashes from a single failure.

**Task 2 — Dispatcher wiring**

Updated `on_startup` in `src/bot/dispatcher.py`:
- calls `manager.resume_all(bot, settings.group_chat_id)` after SessionManager init
- creates health check background task via `asyncio.create_task(health_check_loop(...))`
- stores task as `dispatcher["health_task"]` for lifecycle management

Updated `on_shutdown`:
- cancels `health_task` and awaits its `CancelledError` before proceeding
- stops all active sessions via `manager.list_all()` (existing behavior retained)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Deferred imports in resume_all | Avoids circular import between manager.py and queries.py at module load time |
| `runner.is_alive` for zombie check | Public property checks `task.done()` — no dependency on internal SDK attributes |
| health_task stored in dispatcher | Enables clean cancellation in on_shutdown without global state |
| Failed resume marks session stopped | Prevents retry loops on next restart if session_id is stale or workdir missing |

## Verification

- `from src.sessions.health import health_check_loop` — imports successfully
- `SessionManager.resume_all` has correct `bot` and `chat_id` parameters
- `dispatcher.py` contains `resume_all`, `health_check_loop`, `health_task`, `cancel()` — 9 occurrences
- All 22 tests pass (`uv run pytest tests/ -x`)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | a38b990 | feat(02-03): add resume_all to SessionManager and health check loop |
| Task 2 | 338f98e | feat(02-03): wire resume_all and health_check_loop into dispatcher lifecycle |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- src/sessions/health.py: FOUND
- src/sessions/manager.py: FOUND
- src/bot/dispatcher.py: FOUND
- Commit a38b990: FOUND
- Commit 338f98e: FOUND

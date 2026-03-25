---
phase: 01-foundation
plan: 02
subsystem: bot
tags: [aiogram, middleware, router, pytest, asyncio]

# Dependency graph
requires:
  - phase: 01-foundation/01-01
    provides: src/config.py Settings with owner_user_id and group_chat_id fields
provides:
  - OwnerAuthMiddleware silently dropping non-owner/wrong-chat/channel-post messages
  - general_router handling General topic (thread_id=1 or None)
  - session_router handling session topics (all other thread_ids)
  - build_dispatcher() assembling middleware+routers with lifecycle hooks
  - 8 passing unit tests covering auth filtering and topic isolation
affects: [01-03, phase-2-session-lifecycle]

# Tech tracking
tech-stack:
  added: [pytest, pytest-asyncio]
  patterns: [outer-middleware-auth-gate, router-per-concern, tdd-red-green]

key-files:
  created:
    - src/bot/middlewares.py
    - src/bot/routers/__init__.py
    - src/bot/routers/general.py
    - src/bot/routers/session.py
    - src/bot/dispatcher.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_middleware.py
    - tests/test_router.py
  modified:
    - src/__main__.py

key-decisions:
  - "General topic filter uses F.message_thread_id.in_({1, None}) to handle both thread_id=1 and None defensively — Telegram client versions differ; Phase 2 live testing will confirm actual value"
  - "OwnerAuthMiddleware registered as outer_middleware on dp.message (not per-router) so auth fires before any filter evaluation"

patterns-established:
  - "Outer middleware pattern: dp.message.outer_middleware() for bot-wide guards"
  - "Router-per-concern: separate Router instances for General and Session topics"
  - "TDD with pytest-asyncio auto mode: async tests run directly without decorators"

requirements-completed: [FOUND-02, FOUND-04, FOUND-05]

# Metrics
duration: 8min
completed: 2026-03-24
---

# Phase 1 Plan 2: Auth Middleware and Forum Topic Routing Summary

**aiogram outer middleware auth gate + two forum topic routers (General/session) with dispatcher factory and 8 passing unit tests**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-24T10:01:43Z
- **Completed:** 2026-03-24T10:09:00Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- OwnerAuthMiddleware silently drops non-owner, wrong-chat, and channel-post messages
- general_router filters thread_id=1/None, session_router filters all other non-null thread_ids
- build_dispatcher() wires middleware+routers+lifecycle hooks into a single factory
- src/__main__.py updated to use build_dispatcher() instead of bare Dispatcher()
- 8 unit tests prove auth filtering and topic routing isolation

## Task Commits

Each task was committed atomically:

1. **Task 1: OwnerAuthMiddleware with chat_id guard and unit tests** - `87ba4bd` (feat)
2. **Task 2: Forum topic routers, dispatcher assembly, and routing tests** - `b290715` (feat)

**Plan metadata:** (docs commit follows)

_Note: Both tasks followed TDD red-green protocol_

## Files Created/Modified
- `src/bot/middlewares.py` - OwnerAuthMiddleware with from_user, chat_id, and owner_id guards
- `src/bot/routers/__init__.py` - Empty package marker
- `src/bot/routers/general.py` - general_router with F.message_thread_id.in_({1, None}) filter
- `src/bot/routers/session.py` - session_router with is_not(None) and != 1 filters
- `src/bot/dispatcher.py` - build_dispatcher() factory with middleware+routers+lifecycle hooks
- `src/__main__.py` - Updated to import and call build_dispatcher()
- `tests/__init__.py` - Empty package marker
- `tests/conftest.py` - Shared fixtures: owner_message, stranger_message, wrong_chat_message, channel_post_message, handler
- `tests/test_middleware.py` - 4 middleware unit tests
- `tests/test_router.py` - 4 routing tests including dispatcher middleware registration check

## Decisions Made
- `F.message_thread_id.in_({1, None})` defensive filter for General topic: handles both thread_id=1 and None across Telegram client versions. Phase 2 live testing will confirm actual value and can narrow the filter.
- Outer middleware registered at dispatcher level (not per-router) so auth fires before any filter evaluation — consistent with the plan's design.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Message pipeline complete: every incoming message is auth-checked then routed to correct handler
- Plan 01-03 (database setup) can proceed independently
- Phase 2 session lifecycle can build on general_router (add /new, /list, /stop commands) and session_router (forward to Claude sessions)

## Self-Check: PASSED

- All 9 implementation/test files found on disk
- Both task commits (87ba4bd, b290715) found in git log
- All 8 tests pass (pytest exit code 0)

---
*Phase: 01-foundation*
*Completed: 2026-03-24*

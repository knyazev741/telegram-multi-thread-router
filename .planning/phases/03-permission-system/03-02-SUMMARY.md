---
phase: 03-permission-system
plan: 02
subsystem: bot/permissions
tags: [permissions, aiogram, di, callback-query]
dependency_graph:
  requires: [03-01]
  provides: [permission-callback-handler, permission-manager-di]
  affects: [session-router, dispatcher, session-manager, general-router]
tech_stack:
  added: []
  patterns: [aiogram-di, callback-query-handler, future-resolution]
key_files:
  created: []
  modified:
    - src/bot/routers/session.py
    - src/bot/dispatcher.py
    - src/sessions/manager.py
    - src/bot/routers/general.py
decisions:
  - "In-handler owner guard for callbacks instead of OwnerAuthMiddleware — middleware was designed for Message events; CallbackQuery has different attribute paths"
  - "query.answer() called before edit_text to dismiss Telegram spinner immediately (Pitfall 1)"
metrics:
  duration: 2 min
  completed: 2026-03-24
---

# Phase 3 Plan 2: Wire PermissionManager DI and Callback Handler Summary

**One-liner:** Inline button handler resolves permission futures via PermissionManager wired through aiogram DI from dispatcher startup to every SessionRunner.

## What Was Built

Connected the permission bridge (from Plan 01) to Telegram by adding:
1. A `handle_permission_callback` handler in `session_router` that resolves pending `asyncio.Future` objects when the owner taps an inline button
2. Full DI chain: `PermissionManager` created in `on_startup`, stored in dispatcher dict, passed through `SessionManager.create()` and `resume_all()` to every `SessionRunner`

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add callback query handler to session router | 8e7b67f | src/bot/routers/session.py |
| 2 | Thread PermissionManager through DI | faf2813 | src/bot/dispatcher.py, src/sessions/manager.py, src/bot/routers/general.py |

## Decisions Made

1. **In-handler owner guard for callbacks** — `OwnerAuthMiddleware` was designed for `Message` events and accesses `event.chat.id` which doesn't exist on `CallbackQuery`. Added a direct `query.from_user.id != settings.owner_user_id` check inside the handler instead. Cleaner and avoids middleware AttributeError.

2. **query.answer() before edit_text** — Per Pitfall 1 in research, `query.answer()` must be called before any other awaits to dismiss the loading spinner in Telegram. The implementation calls `answer()` immediately after resolving the future.

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

- `python -c "from src.bot.dispatcher import build_dispatcher; dp = build_dispatcher(); print('Dispatcher builds OK')"` — PASSED
- `grep -c "permission_manager" src/bot/dispatcher.py` — 3 (>= 3 threshold met)
- `grep -c "permission_manager" src/sessions/manager.py` — 4 (>= 4 threshold met)
- `grep -c "permission_manager" src/bot/routers/general.py` — 2 (>= 2 threshold met)
- `grep -c "handle_permission_callback" src/bot/routers/session.py` — 1
- `grep -c "PermissionCallback.filter" src/bot/routers/session.py` — 1

## Self-Check: PASSED

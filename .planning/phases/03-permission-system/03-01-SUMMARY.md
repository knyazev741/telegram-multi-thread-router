---
phase: 03-permission-system
plan: 01
subsystem: permissions
tags: [asyncio, aiogram, claude-agent-sdk, inline-keyboard, futures]

requires:
  - phase: 02-session-lifecycle
    provides: SessionRunner with _dummy_pretool_hook and WAITING_PERMISSION state stub

provides:
  - PermissionManager class (asyncio.Future store) in src/sessions/permissions.py
  - PermissionCallback (aiogram CallbackData) for inline button routing
  - build_permission_keyboard() returning 3-button InlineKeyboardMarkup
  - format_permission_message() producing HTML-escaped permission prompts
  - SessionRunner._can_use_tool replacing _auto_allow_tool placeholder
  - SessionRunner._allowed_tools set pre-seeded with safe tools

affects:
  - 03-02 (callback query handler registration in session router)
  - 03-03 (dispatcher wiring — passes PermissionManager to runners at startup)

tech-stack:
  added: []
  patterns:
    - "asyncio.Future-based bridge: can_use_tool creates Future, callback handler resolves it"
    - "PermissionCallback(CallbackData, prefix='perm') for type-safe 64-byte callback data"
    - "Two-track allow-always: Python-side _allowed_tools set + PermissionResultAllow(updated_permissions=...)"
    - "State guard pattern: save prev_state, set WAITING_PERMISSION, restore in finally"

key-files:
  created:
    - src/sessions/permissions.py
  modified:
    - src/sessions/runner.py

key-decisions:
  - "PermissionRuleValue imported from claude_agent_sdk.types (not top-level __init__) — not exported at package level in 0.1.50"
  - "asyncio.get_running_loop().create_future() used per Python 3.14 requirement (Pitfall 3)"
  - "State always restored to prev_state in finally block regardless of timeout or deny outcome"

patterns-established:
  - "Permission Future lifecycle: create_request() -> send Telegram message -> wait_for(300s) -> resolve/expire"
  - "Safe tools bypass the Future entirely — checked in _can_use_tool before any async work"

requirements-completed: [PERM-01, PERM-05, PERM-06, PERM-07, PERM-09]

duration: 2min
completed: 2026-03-24
---

# Phase 3 Plan 01: Permission Bridge Summary

**asyncio.Future-based permission bridge with PermissionManager, inline keyboard UI, and SessionRunner._can_use_tool replacing the auto-allow placeholder**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-24T10:58:17Z
- **Completed:** 2026-03-24T11:00:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `src/sessions/permissions.py` with PermissionManager (Future store), PermissionCallback (CallbackData), keyboard builder, and HTML message formatter
- Replaced `_auto_allow_tool` placeholder in SessionRunner with real `_can_use_tool` that awaits user input via Telegram
- Wired WAITING_PERMISSION state, 5-minute timeout auto-deny, and "allow always" two-track mechanism (Python set + SDK PermissionUpdate)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create PermissionManager, PermissionCallback, keyboard builder, and message formatter** - `daa001e` (feat)
2. **Task 2: Replace _auto_allow_tool with real _can_use_tool in SessionRunner** - `c2818a5` (feat)

## Files Created/Modified

- `src/sessions/permissions.py` - PermissionManager, PermissionCallback, build_permission_keyboard, format_permission_message
- `src/sessions/runner.py` - SessionRunner with _can_use_tool, permission_manager param, _allowed_tools set; _auto_allow_tool deleted

## Decisions Made

- `PermissionRuleValue` is not exported from `claude_agent_sdk` top-level `__init__` in version 0.1.50 — must import from `claude_agent_sdk.types` directly. This contradicts the RESEARCH.md import path but was discovered during Task 2 verification and fixed immediately (Rule 3 auto-fix).
- `asyncio.get_running_loop().create_future()` used in PermissionManager.create_request() per Python 3.14 requirement (deprecated `get_event_loop()` path avoided per Pitfall 3).
- State restoration in `finally` block ensures WAITING_PERMISSION is never left set regardless of whether timeout fires or future resolves normally.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PermissionRuleValue not in claude_agent_sdk top-level exports**
- **Found during:** Task 2 (runner.py import verification)
- **Issue:** `from claude_agent_sdk import PermissionRuleValue` raises ImportError — not exported from package `__init__.py` in 0.1.50
- **Fix:** Changed import to `from claude_agent_sdk.types import PermissionRuleValue`
- **Files modified:** src/sessions/runner.py
- **Verification:** Module imports successfully, all plan verification checks pass
- **Committed in:** c2818a5 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking import error)
**Impact on plan:** Necessary fix for the module to import. No scope creep, no behavior change.

## Issues Encountered

None beyond the PermissionRuleValue import path documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PermissionManager and _can_use_tool are fully implemented and verified
- Ready for Phase 3 Plan 02: callback query handler in session router to resolve futures when buttons are tapped
- Ready for Phase 3 Plan 03: dispatcher wiring to pass PermissionManager to SessionRunner at construction time
- Known concern from STATE.md still applies: GitHub issue #227 (can_use_tool may be skipped in multi-turn sessions) — validate during Phase 3 integration testing

---
*Phase: 03-permission-system*
*Completed: 2026-03-24*

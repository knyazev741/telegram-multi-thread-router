---
phase: 04-status-and-ux
plan: "02"
subsystem: sessions
tags: [aiogram, claude-sdk, status, typing, output-splitting]

# Dependency graph
requires:
  - phase: 04-01
    provides: StatusUpdater, TypingIndicator, split_message utilities

provides:
  - SessionRunner._drain_response with full status/output pipeline
  - Live typing indicator per turn via TypingIndicator
  - StatusUpdater lifecycle (start_turn → track_tool → finalize) per turn
  - Smart message splitting via split_message on all TextBlock output
  - ToolUseBlock events tracked for status display
  - ResultMessage triggers finalize() with cost/duration/tool_count
  - Error messages formatted with HTML and emoji prefix (STAT-07)
  - TelegramRetryAfter retry logic on outbound messages

affects:
  - 05-voice-file
  - Phase 5 (voice/file I/O) — SessionRunner is the core output path

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-turn StatusUpdater + TypingIndicator created in _run(), finalized in _drain_response
    - TelegramRetryAfter caught at message send site with single retry
    - Markdown parse_mode with fallback to plain text on parse failure
    - Cleanup of UX helpers in except block to avoid zombie tasks

key-files:
  created: []
  modified:
    - src/sessions/runner.py

key-decisions:
  - "StatusUpdater and TypingIndicator created per-turn in _run() before client.query(), finalized inside _drain_response on ResultMessage"
  - "TelegramRetryAfter retry logic in _drain_response — one retry attempt per message part before giving up"
  - "Markdown parse_mode with silent fallback to plain text (catches all TelegramBadRequest variants)"

patterns-established:
  - "UX helpers (status/typing) allocated per-turn, not per-session"
  - "Error cleanup always in except block — typing.stop() + status.stop() before error message send"

requirements-completed: [STAT-03, STAT-06, STAT-07]

# Metrics
duration: 4min
completed: 2026-03-24
---

# Phase 4 Plan 02: Status and UX Pipeline Summary

**SessionRunner._drain_response rewritten with live typing indicator, status tracking, split_message output, ResultMessage cost summary, and STAT-07 error formatting**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-24T11:55:13Z
- **Completed:** 2026-03-24T11:59:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Rewrote `_drain_response` to split TextBlock output via `split_message` before sending
- Integrated `StatusUpdater` lifecycle: `start_turn()` before query, `track_tool()` on ToolUseBlock, `finalize()` on ResultMessage
- `TypingIndicator` starts before `client.query()`, stops after drain completes
- `TelegramRetryAfter` caught and retried once per message part
- Markdown parse_mode with silent fallback to plain text on failure
- Exception handler in `_run()` cleans up typing/status and sends formatted `❌ Error:` message with HTML

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite _drain_response with full status/output pipeline** - `e923d70` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `src/sessions/runner.py` - Full status/output pipeline in _drain_response; TypingIndicator + StatusUpdater per-turn lifecycle in _run()

## Decisions Made
- StatusUpdater and TypingIndicator created per-turn in `_run()` (not per-session) so each query gets a fresh status message
- `_status = None` after `finalize()` prevents double-finalize if drain is called again
- Typing indicator stopped in `_run()` after drain (not inside drain) to keep drain focused on message handling

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness
- Phase 4 complete: all three UX utilities (StatusUpdater, TypingIndicator, split_message) wired into SessionRunner
- Phase 5 (Voice/File I/O) can begin: SessionRunner output path is stable and tested

---
*Phase: 04-status-and-ux*
*Completed: 2026-03-24*

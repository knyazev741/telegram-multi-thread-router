---
phase: 04-status-and-ux
plan: 01
subsystem: ui
tags: [aiogram, telegram, asyncio, status-message, typing-indicator]

requires:
  - phase: 02-session-lifecycle
    provides: SessionRunner with bot/chat_id/thread_id pattern for Telegram messaging
  - phase: 03-permission-system
    provides: aiogram Bot usage patterns (send_message, edit_message_text)
provides:
  - StatusUpdater class managing one editable Telegram status message per session turn
  - split_message utility splitting long text at code-block/newline boundaries
  - TypingIndicator class sending chat action every 4s in background task
affects: [04-status-and-ux, 05-voice-file-io]

tech-stack:
  added: []
  patterns:
    - "StatusUpdater lifecycle: start_turn → track_tool → finalize/stop"
    - "30s background asyncio.Task refresh loop with CancelledError exit"
    - "TelegramRetryAfter: sleep e.retry_after and retry once, then skip"
    - "TelegramBadRequest (message not modified): ignore silently"
    - "call_later(30, lambda: asyncio.create_task(...)) for deferred cleanup"

key-files:
  created:
    - src/bot/status.py
    - src/bot/output.py
  modified: []

key-decisions:
  - "StatusUpdater stores _start_time via time.monotonic() for drift-resistant elapsed calculation"
  - "finalize() uses call_later(30, ...) to schedule deletion without blocking the caller"
  - "split_message prefers \\n``` boundary to keep code blocks intact, then newline, then hard split"
  - "TypingIndicator catches all Exception (not just TelegramRetryAfter) to avoid crashing on transient errors"

patterns-established:
  - "Background task lifecycle: create_task in start, cancel+await in stop, CancelledError swallowed"
  - "Retry-once pattern for TelegramRetryAfter in edit loops"

requirements-completed: [STAT-01, STAT-02, STAT-04, STAT-05]

duration: 2min
completed: 2026-03-24
---

# Phase 4 Plan 01: Status and Output Utilities Summary

**StatusUpdater class with 30s-refresh editable Telegram status message, plus split_message and TypingIndicator utilities for aiogram**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-24T11:51:05Z
- **Completed:** 2026-03-24T11:53:22Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- StatusUpdater manages one editable Telegram message per session turn with start_turn/track_tool/finalize/stop lifecycle
- 30s background refresh loop updates tool name and elapsed time; TelegramRetryAfter handled with sleep+retry-once
- split_message splits text at code-block (`\n\`\`\``) then newline then hard-cut, recursively, guaranteeing all chunks <= 4096 chars
- TypingIndicator sends "typing" chat action every 4s as a background asyncio.Task

## Task Commits

Each task was committed atomically:

1. **Task 1: Create StatusUpdater class** - `f49ae8f` (feat)
2. **Task 2: Create message splitter and typing indicator** - `f45e727` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `src/bot/status.py` - StatusUpdater class with create/update/finalize/stop lifecycle
- `src/bot/output.py` - split_message function and TypingIndicator class

## Decisions Made
- StatusUpdater uses `time.monotonic()` (not `datetime.now()`) for elapsed — monotonic is drift-resistant
- `finalize()` schedules message deletion with `call_later(30, lambda: asyncio.create_task(...))` to avoid blocking caller with `await asyncio.sleep(30)`
- split_message splits at `\n\`\`\`` to keep code block closings on first chunk; second chunk starts fresh without an opening fence (callers may need to track whether they are mid-block if needed in future)
- TypingIndicator catches bare `Exception` (not just TelegramRetryAfter) and logs a warning so transient network issues don't crash the typing loop

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- StatusUpdater and output utilities are standalone importable modules
- Ready to be wired into SessionRunner in plan 04-02
- No blockers

---
*Phase: 04-status-and-ux*
*Completed: 2026-03-24*

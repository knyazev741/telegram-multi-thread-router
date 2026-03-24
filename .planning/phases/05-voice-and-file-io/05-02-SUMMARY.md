---
phase: 05-voice-and-file-io
plan: 02
subsystem: bot
tags: [aiogram, voice, whisper, mcp, faster-whisper, claude-agent-sdk]

requires:
  - phase: 05-01
    provides: transcribe_voice function and create_telegram_mcp_server factory
  - phase: 02-session-lifecycle
    provides: SessionRunner, SessionManager, enqueue() API
provides:
  - Voice messages transcribed and forwarded to Claude sessions as text
  - Photo and document messages downloaded to workdir and forwarded as path descriptions
  - Claude sessions equipped with 4 Telegram output MCP tools (reply, send_file, react, edit_message)
affects:
  - 06-multi-server (session runner shape is now established)

tech-stack:
  added: []
  patterns:
    - Content-type specific handlers placed before catch-all in aiogram router (handler order matters)
    - Temp file pattern with try/finally cleanup for voice OGG downloads
    - MCP server created per session run (closure-bound to bot/chat_id/thread_id)

key-files:
  created: []
  modified:
    - src/bot/routers/session.py
    - src/sessions/runner.py

key-decisions:
  - "Voice handlers use tempfile.NamedTemporaryFile + finally block for safe OGG cleanup even on transcription error"
  - "Specific content-type handlers (voice/photo/document) registered before catch-all text handler — aiogram evaluates handlers in registration order"
  - "MCP server created at _run() start, not at SessionRunner.__init__, so it is always fresh per session"

patterns-established:
  - "Content-type routing: register F.content_type == ContentType.X handlers before catch-all"
  - "File download pattern: download to Path(runner.workdir) / filename, enqueue 'User sent file: {name} at {path}'"

requirements-completed: [INPT-02, INPT-03, INPT-04, FILE-01, FILE-02, FILE-03, FILE-04]

duration: 2min
completed: 2026-03-24
---

# Phase 5 Plan 02: Voice/File Handlers and MCP Wiring Summary

**Voice messages transcribed via faster-whisper, photos/documents downloaded to workdir, and all Claude sessions given 4 Telegram MCP output tools wired end-to-end through session router and runner.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-24T12:42:06Z
- **Completed:** 2026-03-24T12:43:33Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `handle_voice`, `handle_photo`, `handle_document` handlers to session router — all placed before the catch-all text handler with proper content-type filters
- Voice handler downloads OGG to temp file, calls `transcribe_voice`, cleans up in finally, enqueues transcribed text
- Photo and document handlers download to `runner.workdir`, enqueue descriptive path messages for Claude to act on
- Wired `create_telegram_mcp_server` into `SessionRunner._run()` — Claude now has reply, send_file, react, edit_message tools in every session
- Removed stale "Phase 5 handles voice/files" placeholder comment from text handler

## Task Commits

Each task was committed atomically:

1. **Task 1: Add voice, photo, document handlers to session router** - `74cb88c` (feat)
2. **Task 2: Wire MCP tools into SessionRunner** - `c1df79f` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/bot/routers/session.py` — Added 3 content-type handlers plus new imports (ContentType, transcribe_voice, tempfile, os, Path)
- `src/sessions/runner.py` — Added mcp_tools import, mcp_server creation, mcp_servers kwarg to ClaudeAgentOptions

## Decisions Made

- Voice handlers use `tempfile.NamedTemporaryFile` with `delete=False` and a `finally` block for safe OGG cleanup — ensures temp files are removed even when transcription raises an exception
- Content-type specific handlers registered before catch-all — aiogram evaluates handlers in registration order, so specificity must come first
- MCP server created inside `_run()` (not `__init__`) so it is always bound to the current bot/chat_id/thread_id context and fresh per session invocation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 7 Phase 5 requirements are now implemented (INPT-02/03/04 via handlers, FILE-01/02/03/04 via MCP tools)
- Phase 5 is complete — the bot handles voice, photo, and document inputs, and Claude can send messages, files, reactions, and edits via MCP tools
- Phase 6 (multi-server) can begin when single-server workflow is validated in daily use

---
*Phase: 05-voice-and-file-io*
*Completed: 2026-03-24*

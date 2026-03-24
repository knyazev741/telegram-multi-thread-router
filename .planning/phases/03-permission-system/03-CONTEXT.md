# Phase 3: Permission System - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers the permission system: replace the auto-allow placeholder in SessionRunner with a real can_use_tool callback that bridges to Telegram inline buttons via asyncio.Future. Includes message formatting, timeout handling, stale button cleanup, and configurable auto-allow rules.

</domain>

<decisions>
## Implementation Decisions

### Permission Message Format
- Tool name + input summary (first 500 chars, "..." if truncated) + numbered options in message body
- 3 inline buttons: 1️⃣ Allow once, 2️⃣ Allow always, 3️⃣ Deny
- HTML parse mode for code formatting in tool input display
- Options text written in message body, buttons only show numbers

### Permission Lifecycle
- asyncio.Future per permission request — can_use_tool awaits future, callback query handler resolves it
- Timeout 5 min → auto-deny + "⏱ Permission timed out — denied" message + edit original to show expired
- Stale button taps → answer_callback_query with "This permission has expired" alert (never leave spinner)
- Pending permissions in memory only (asyncio.Future) — don't survive bot restart

### Auto-Allow Rules
- Default auto-allow: Read, Glob, Grep, Agent (Explore subagent) — safe read-only tools
- "Allow always" adds tool name to session's allowed_tools list — checked before can_use_tool fires
- Per-session allowed_tools — different projects have different risk profiles
- No revoke in v1 — restart session to reset

### Claude's Discretion
- PermissionManager internal data structures
- Callback data encoding scheme for inline buttons
- Exact HTML formatting template for permission messages
- How to handle rapid sequential permission requests (queue vs display all)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sessions/runner.py` — SessionRunner with can_use_tool placeholder (currently auto-allows all)
- `src/sessions/state.py` — SessionState enum (already has WAITING_PERMISSION state)
- `src/bot/dispatcher.py` — build_dispatcher() with on_startup, ready for PermissionManager init
- `src/bot/routers/session.py` — session router, add callback query handler here

### Established Patterns
- aiogram 3 CallbackData factory for type-safe callback data
- aiogram 3 callback_query handler with `@router.callback_query()`
- asyncio.Future with asyncio.wait_for for timeout
- SessionRunner state transitions via `self._state = SessionState.X`

### Integration Points
- SessionRunner.can_use_tool — replace auto-allow with real callback
- SessionRunner needs reference to PermissionManager to create permission requests
- Callback query handler in session router resolves PermissionManager futures
- build_dispatcher() wires PermissionManager into DI

</code_context>

<specifics>
## Specific Ideas

- The dummy PreToolUse hook MUST remain registered (SDK requirement)
- can_use_tool is async — can safely await the asyncio.Future with timeout
- PermissionResultAllow() to approve, PermissionResultDeny(message="...") to deny
- When "Allow always" is selected, return PermissionResultAllow(updated_permissions=[...]) to update SDK's internal allowlist
- CallbackData class: `PermissionCallback(action=str, request_id=str)` — action is "allow"/"always"/"deny"

</specifics>

<deferred>
## Deferred Ideas

- Batched permission display for rapid requests (v2)
- Per-session permission profiles stored in SQLite (v2)
- /revoke command to reset allowed_tools (v2)

</deferred>

# Phase 4: Status and UX - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers real-time status updates, typing indicator, Claude output message handling with smart splitting, and error display. Enhances the session experience with live feedback while Claude works.

</domain>

<decisions>
## Implementation Decisions

### Status Message Display
- One persistent status message per session, edited in-place every 30s
- Shows: current tool + elapsed time + tool call count
- Format: `⚡ Working...\n📁 Tool: Read (src/main.py)\n⏱ 1m 30s | 5 tools`
- When Claude finishes: edit to final summary (cost, duration, tools), delete after 30s

### Output & Error Handling
- Long messages split at 4096 chars, prefer splitting at code block boundaries (``` markers)
- Markdown parse mode for Claude output (native to Claude's response format)
- TelegramRetryAfter: catch, wait specified seconds, retry once
- Error format: `❌ Error: {type}\n{message}` sent to thread, status message cleared

### Claude's Discretion
- StatusUpdater internal task management
- Exact timing of status message creation vs first update
- How to track tool calls from SDK events
- Typing indicator renewal implementation

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sessions/runner.py` — SessionRunner with _drain_response() iterating SDK events
- `src/bot/dispatcher.py` — build_dispatcher() with DI pattern
- `src/bot/routers/session.py` — session router for message handlers

### Established Patterns
- aiogram Bot.send_message / edit_message / send_chat_action
- asyncio background tasks for periodic operations (see health.py pattern)
- SessionRunner iterates AssistantMessage, SystemMessage, ResultMessage

### Integration Points
- SessionRunner._drain_response() — hook into message events for output forwarding
- SessionRunner needs to pass Bot reference for sending messages
- Status updater needs to track current tool from ToolUseBlock events
- ResultMessage provides duration_ms, total_cost_usd for final summary

</code_context>

<specifics>
## Specific Ideas

- StatusUpdater should be a per-session background task created when query starts
- Typing indicator: sendChatAction("typing") every 4s in a background task
- Message splitter: find last ``` before 4096 boundary, split there
- ResultMessage fields: session_id, duration_ms, total_cost_usd, is_error, num_turns

</specifics>

<deferred>
## Deferred Ideas

- Streaming partial text (edit message as Claude generates) — v2
- Cost/token tracking dashboard — v2

</deferred>

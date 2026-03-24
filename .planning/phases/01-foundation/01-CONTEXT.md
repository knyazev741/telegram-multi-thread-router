# Phase 1: Foundation - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers the bot scaffold: aiogram 3 long polling, owner-only auth middleware, forum topic routing by message_thread_id, SQLite persistence with WAL mode. This is the base layer everything else builds on.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase. Key constraints from research:
- Python 3.11+ with uvloop event loop
- aiogram 3.26+ with Router + middleware pattern
- aiosqlite for async SQLite with WAL mode enabled at init
- Project structure: `src/` package with `bot/`, `db/`, `config.py`
- Delete all old Node.js code (proxy/, plugin/, scripts/, orchestrator/)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — clean rewrite, old Node.js code will be deleted

### Established Patterns
- .env for secrets (BOT_TOKEN, OWNER_USER_ID, GROUP_CHAT_ID, AUTH_TOKEN)
- Forum topics in Telegram group chat with message_thread_id routing

### Integration Points
- New Python project replaces entire existing codebase
- .env format preserved for continuity

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>
